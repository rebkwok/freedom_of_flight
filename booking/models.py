# -*- coding: utf-8 -*-
import calendar
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
import logging
import pytz
from shortuuid import ShortUUID

from django.db import models
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_delete
from django.dispatch import receiver

from delorean import Delorean
from django_extensions.db.fields import AutoSlugField
from dateutil.relativedelta import relativedelta

from activitylog.models import ActivityLog
from common.utils import start_of_day_in_utc, end_of_day_in_utc, end_of_day_in_local_time
from payments.models import Invoice

from .email_helpers import send_user_and_studio_emails


logger = logging.getLogger(__name__)

COMMON_LABEL_PLURALS = {
    "class": "es",
    "workshop": "s",
    "event": "s",
    "party": "y,ies",
    "private": "s",
}


class Track(models.Model):
    """Categorises events.  Used for grouping onto separate pages/schedules"""
    name = models.CharField(max_length=255, unique=True)
    slug = AutoSlugField(populate_from=['name'], max_length=40, unique=True)
    default = models.BooleanField(default=False, help_text="Set one track to default to use as landing page for site")

    def __str__(self):
        return self.name

    @classmethod
    def get_default(cls):
        default = Track.objects.filter(default=True)
        if default:
            return default[0]
        else:
            # returns the first one, or None
            return Track.objects.first()

    @property
    def event_type_label(self):
        most_common = self.event_types.values("label").annotate(count=models.Count('label')).order_by("-count")
        return most_common.first() or "class"

    @property
    def pluralized_event_type_label(self):
        event_type_with_label = self.event_types.filter(label=self.event_type_label).first()
        return event_type_with_label.pluralized_label if event_type_with_label else "classes"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.default:
            Track.objects.all().exclude(id=self.id).update(default=False)


class EventType(models.Model):
    """
    Categorises and configures events.
    Used for assigning to courses and cost categories (see Block Type)
    Also defines some common fields
    """
    name = models.CharField(max_length=255, help_text='Name for this event type (lowercase)')
    label = models.CharField(
        max_length=255,
        default="class",
        help_text='How an instance of this event type will be referred to, e.g. "class", "workshop"'
    )
    plural_suffix = models.CharField(
        max_length=10, default="es",
        help_text="A suffix to pluralize the label. E.g. 'es' for class -> classes.  If the label does not "
                  "pluralise with a simple suffix, enter single and plural suffixes separated by a comma, e.g. "
                  "'y,ies' for party -> parties"
    )
    description = models.TextField(help_text="Description", null=True, blank=True)
    track = models.ForeignKey(Track, on_delete=models.SET_NULL, null=True, related_name="event_types")
    contact_email = models.EmailField(default=settings.DEFAULT_STUDIO_EMAIL)
    booking_restriction = models.PositiveIntegerField(
        default=15, help_text="Time (minutes) to prevent booking prior to event start. Set to 0 to allow unrestricted booking "
                              "up to the event start time",
    )
    cancellation_period = models.PositiveIntegerField(default=24)
    email_studio_when_booked = models.BooleanField(default=False)
    allow_booking_cancellation = models.BooleanField(default=True)
    is_online = models.BooleanField(default=False)

    minimum_age_for_booking = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Minimum age allowed for booking (inclusive - i.e. 16 allows booking from the student's 16th birthday)"
    )
    maximum_age_for_booking = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Maximum age allowed for booking (inclusive - i.e. 16 allows booking up to the student's 17th birthday)"
    )

    class Meta:
        unique_together = ("name", "track")

    def __str__(self):
        return f"{self.name.title()} - {self.track}"

    @property
    def pluralized_label(self):
        suffix = self.plural_suffix.split(',')
        if len(suffix) == 2:
            plural_label = self.label.replace(suffix[0], suffix[1])
        else:
            plural_label = self.label + suffix[0]
        return plural_label

    def valid_for_user(self, user):
        if not any([self.maximum_age_for_booking, self.minimum_age_for_booking]):
            return True
        if user.age is None:
            return False
        if self.maximum_age_for_booking and user.age > self.maximum_age_for_booking:
            return False
        if self.minimum_age_for_booking and user.age < self.minimum_age_for_booking:
            return False
        return True

    @property
    def age_restrictions(self):
        if self.minimum_age_for_booking:
            return f"age {self.minimum_age_for_booking} and over only"
        if self.maximum_age_for_booking:
            return f"age {self.maximum_age_for_booking} and under only"

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        self.name = self.name.lower()
        self.label = self.label.lower()
        self.plural_suffix = self.plural_suffix.lower().replace(" ", "")
        self.plural_suffix = COMMON_LABEL_PLURALS.get(self.label.split()[-1], self.plural_suffix)
        super().save()


class Course(models.Model):
    """A collection of specific Events of the same EventType"""
    name = models.CharField(
        max_length=255, help_text="A short identifier that will be displayed to users on the event list.  "
    )
    description = models.TextField(blank=True, default="")
    event_type = models.ForeignKey(EventType, on_delete=models.CASCADE)
    number_of_events = models.PositiveIntegerField(default=4)
    slug = AutoSlugField(populate_from=["name", "event_type", "number_of_events"], max_length=40, unique=True)
    cancelled = models.BooleanField(default=False)
    max_participants = models.PositiveIntegerField(default=10, help_text="Overrides any value set on individual linked events")
    show_on_site = models.BooleanField(default=False, help_text="Overrides any value set on individual linked events")
    allow_drop_in = models.BooleanField(
        default=False,
        help_text="Users can book individual events with a drop-in credit block valid for this event type"
    )

    @property
    def full(self):
        # A course is full if its events are full, INCLUDING no-shows and cancellations (although
        # a course event never really gets cancelled, only set to no-show)
        # Only need to check the first event
        return self.booking_count() >= self.max_participants

    @property
    def all_events_full(self):
        return not any(not event.full for event in self.events_left)

    @property
    def spaces_left(self):
        return self.max_participants - self.booking_count()

    @property
    def has_available_payment_plan(self):
        return valid_course_block_configs(self) is not None

    def booking_count(self):
        # Find the distinct users from all booking on this course.  We don't just look at the first event, in case
        # a course's events have been updated after start
        # Only count open bookings, which will inlcude no-shows but not fully cancelled ones
        # A booking should only be fully cancelled if the user has been manually cancelled out by an admin, and it
        # should apply to all bookings in the course.

        # Find the max count of open bookings against any single event
        # There may be drop in bookings by different users
        if not self.uncancelled_events.exists():
            return 0
        return max([
            event.bookings.filter(status="OPEN").count() for event in self.uncancelled_events
        ])

    @property
    def start(self):
        if self.uncancelled_events:
            return self.uncancelled_events.first().start

    @property
    def has_started(self):
        return self.start and self.start < timezone.now()

    @property
    def last_event_date(self):
        last_event = self.uncancelled_events.last()
        if last_event:
            return last_event.start

    @property
    def uncancelled_events(self):
        return self.events.filter(cancelled=False).order_by("start")

    @property
    def events_left(self):
        if not self.has_started:
            return self.uncancelled_events
        events_left_ids = [event.id for event in self.uncancelled_events if not event.is_past]
        return self.uncancelled_events.filter(id__in=events_left_ids)

    def is_configured(self):
        """A course is configured if it has the right number of un-cancelled events"""
        return self.uncancelled_events.count() == self.number_of_events

    def can_be_visible(self):
        """
        A course can be visible if it has at least the required number of events (it could have more if some are
        cancelled)
        """
        return self.events.count() >= self.number_of_events

    def __str__(self):
        return f"{self.name} ({self.event_type} - {self.number_of_events})"

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        super().save()
        for event in self.events.all():
            if event.max_participants != self.max_participants:
                event.max_participants = self.max_participants
            if self.show_on_site != event.show_on_site:
                event.show_on_site = self.show_on_site
                ActivityLog.objects.create(
                    log=f"Course {self} updated; show_on_site for linked events has been adjusted to match"
                )
            if self.cancelled and not event.cancelled:
                # Only cancel events if course is cancelled.  Don't reset cancelled events to the course status if the
                # course is still open
                event.cancelled = True
            event.save()
        if self.events.exists():
            ActivityLog.objects.create(
                log=f"Course {self} updated; show_on_site and max participants for linked events have been adjusted to match"
            )
            if self.cancelled:
                ActivityLog.objects.create(
                    log=f"Course {self} cancelled; linked events have been cancelled also"
                )


class Event(models.Model):
    """A single bookable Event"""
    name = models.CharField(max_length=255)
    event_type = models.ForeignKey(EventType, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True, related_name="events")
    description = models.TextField(blank=True, default="")
    start = models.DateTimeField(help_text="Start date and time")
    duration = models.PositiveIntegerField(help_text="Duration in minutes", default=90)
    max_participants = models.PositiveIntegerField(default=10)
    slug = AutoSlugField(populate_from=['name', 'start'], max_length=40, unique=True)
    cancelled = models.BooleanField(default=False)
    video_link = models.URLField(null=True, blank=True, help_text="Zoom/Video URL (for online classes only)")
    video_link_available_after_class = models.BooleanField(
        default=False,
        help_text="Zoom/Video URL available after class is past (for online classes only)"
    )
    show_on_site = models.BooleanField(default=False)

    class Meta:
        ordering = ['-start']
        indexes = [
            models.Index(fields=['event_type', 'start', 'cancelled']),
            models.Index(fields=['event_type', 'name', 'start', 'cancelled']),
        ]

    @property
    def end(self):
        return self.start + timedelta(minutes=self.duration)

    @property
    def spaces_left(self):
        if self.course:
            # No-shows count for course event spaces
            booked_number = self.bookings.filter(status='OPEN').count()
        else:
            booked_number = self.bookings.filter(status='OPEN', no_show=False).count()
        return self.max_participants - booked_number

    @property
    def has_space(self):
        return self.spaces_left > 0

    @property
    def full(self):
        return self.spaces_left <= 0

    @property
    def can_cancel(self):
        time_until_event = self.start - timezone.now()
        time_until_event = time_until_event.total_seconds() / 3600
        return time_until_event > self.event_type.cancellation_period

    def course_order(self):
        if self.course and self.course.events.exists():
            if not self.cancelled:
                events_in_order = self.course.uncancelled_events.values_list("id", flat=True)
                return f"{list(events_in_order).index(self.id) + 1}/{events_in_order.count()}"
            return "-"

    def booking_restricted_pre_start(self):
        return self.event_type.booking_restriction > 0 and (
                self.start - timedelta(
            minutes=self.event_type.booking_restriction) < timezone.now()
        )

    def is_bookable(self, booking_restricted=None):
        """The event can be booked by a user with a valid payment method"""
        if self.cancelled:
            return False
        if self.full:
            return False
        # allow for passing in the value if it's already been calculated, to avoid
        # repeated database calls
        booking_restricted = booking_restricted or self.booking_restricted_pre_start()
        if booking_restricted:
            return False
        if self.course:
            # this event is not full; if the course is full or the course has started,
            # can only book single event if drop in is allowed
            if self.course.full or self.course.has_started:
                if not self.course.allow_drop_in:
                    return False
        return True

    @property
    def show_video_link(self):
        return self.event_type.is_online and (timezone.now() > self.start - timedelta(minutes=20))

    def get_absolute_url(self):
        return reverse("booking:event", kwargs={'slug': self.slug})

    @property
    def is_past(self):
        return self.start < timezone.now()

    @property
    def name_and_date(self):
        return f"{self.name} - {self.start.astimezone(pytz.timezone('Europe/London')).strftime('%d %b %Y, %H:%M')}"

    @property
    def cost_str(self):
        cost = ""
        if self.course and not self.course.has_started:
            course_booking_block = add_to_cart_course_block_config(self.course)
            if course_booking_block:
                cost += f"{course_booking_block.cost_str} (course)"
        cart_booking_block = add_to_cart_drop_in_block_config(self)
        if cart_booking_block:
            if cost:
                cost += " / "
            cost += f"{cart_booking_block.cost_str} (drop-in)"
        return cost

    def __str__(self):
        course_str = f" ({self.course.name})" if self.course else ""
        return f"{self.name}{course_str} - {self.start.astimezone(pytz.timezone('Europe/London')).strftime('%d %b %Y, %H:%M')} " \
               f"({self.event_type.track})"

    def clean(self):
        if self.course and not self.course.event_type == self.event_type:
            raise ValidationError({'course': _('Cannot add this course - event types do not match.')})
        if self.course and self.course.is_configured() and not self.cancelled and self not in self.course.uncancelled_events:
            raise ValidationError({'course': _('Cannot add this course - course is already configured with all its events.')})

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        self.full_clean()
        if self.course:
            if self.max_participants != self.course.max_participants:
                self.max_participants = self.course.max_participants
                ActivityLog.objects.create(
                    log=f"Event {self} max participants does not match course; event has been adjusted to match course"
                )
            if self.show_on_site != self.course.show_on_site:
                self.show_on_site = self.course.show_on_site
                ActivityLog.objects.create(
                    log=f"Event {self} show_on_course does not match course; event has been adjusted to match course"
                )
        super().save()


class BlockConfig(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    cost = models.DecimalField(max_digits=8, decimal_places=2)
    duration = models.PositiveIntegerField(help_text="Number of weeks until block expires (from first use)", default=4,
                                           null=True, blank=True)
    size = models.PositiveIntegerField(
        help_text="Number of events in block. For a course block, the number of events in the course"
    )
    event_type = models.ForeignKey(EventType, on_delete=models.SET_NULL, null=True)
    course = models.BooleanField(default=False)
    active = models.BooleanField(default=False, help_text="Purchasable by users")

    def __str__(self):
        return self.name

    def blocks_purchased(self):
        return self.block_set.filter(paid=True).count()

    def available_to_user(self, user):
        return self.event_type.valid_for_user(user)

    @property
    def age_restrictions(self):
        if self.event_type.age_restrictions:
            return f"Valid for {self.event_type.age_restrictions}"

    @property
    def cost_str(self):
        cost = int(self.cost) if int(self.cost) == self.cost else self.cost
        return f"£{cost}"

class BaseVoucher(models.Model):
    code = models.CharField(max_length=255, unique=True)
    discount = models.PositiveIntegerField(
        verbose_name="Percentage discount", help_text="Discount value as a % of the purchased item cost. Enter a number between 1 and 100",
        null=True, blank=True
    )
    discount_amount = models.DecimalField(
        verbose_name="Exact amount discount", help_text="Discount as an exact amount off the purchased item cost",
        null=True, blank=True, decimal_places=2, max_digits=6
    )
    start_date = models.DateTimeField(default=timezone.now)
    expiry_date = models.DateTimeField(null=True, blank=True)
    max_vouchers = models.PositiveIntegerField(
        null=True, blank=True, verbose_name='Maximum available vouchers',
        help_text="Maximum uses across all users")
    max_per_user = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name="Maximum uses per user",
        help_text="Maximum times this voucher can be used by a single user"
    )

    # for gift vouchers
    is_gift_voucher = models.BooleanField(default=False)
    activated = models.BooleanField(default=True)
    name = models.CharField(null=True, blank=True, max_length=255, help_text="Name of recipient")
    message = models.TextField(null=True, blank=True, max_length=500, help_text="Message (max 500 characters)")
    purchaser_email = models.EmailField(null=True, blank=True)

    @property
    def has_expired(self):
        if self.expiry_date and self.expiry_date < timezone.now():
            return True
        return False

    @property
    def has_started(self):
        return bool(self.start_date < timezone.now() and self.activated)

    def clean(self):
        if not (self.discount or self.discount_amount):
            raise ValidationError("One of discount (%) or discount_amount (fixed amount) is required")
        if self.discount and self.discount_amount:
            raise ValidationError("Only one of discount (%) or discount_amount (fixed amount) may be specified (not both)")

    def _generate_code(self):
        return slugify(ShortUUID().random(length=12))

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_code()
            while BaseVoucher.objects.filter(code=self.code).exists():
                self.code = self._generate_code()
        self.full_clean()
        # replace start time with very start of day
        self.start_date = start_of_day_in_utc(self.start_date)
        if self.expiry_date:
            self.expiry_date = end_of_day_in_utc(self.expiry_date)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.code


class BlockVoucher(BaseVoucher):
    block_configs = models.ManyToManyField(BlockConfig)
    item_count = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name="Number of items",
        help_text="Required number of items that must be purchased at one time with "
                  "this voucher. Set to 1 if the voucher applies to a single purchased "
                  "block/course.  Set to more than 1 if it ONLY applies if the user purchases a "
                  "set number of items (e.g. if you want a 10% discount when a user purchases "
                  "2 blocks/courses at a time)",
        default=1
    )

    def check_block_config(self, block_config):
        return block_config in self.block_configs.all()

    def uses(self):
        return self.blocks.filter(paid=True).count() / self.item_count


class TotalVoucher(BaseVoucher):
    """A voucher that applies to the overall checkout total, not linked to any specific block"""

    def uses(self):
        return Invoice.objects.filter(paid=True, total_voucher_code=self.code).count()


class Block(models.Model):
    """
    Block booking
    """
    user = models.ForeignKey(User, related_name='blocks', on_delete=models.CASCADE)
    block_config = models.ForeignKey(BlockConfig, on_delete=models.CASCADE)
    purchase_date = models.DateTimeField(default=timezone.now)
    created_date = models.DateTimeField(default=timezone.now)
    start_date = models.DateTimeField(null=True, blank=True)
    paid = models.BooleanField(default=False, help_text='Payment has been made by user')

    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name="blocks")
    voucher = models.ForeignKey(BlockVoucher, on_delete=models.SET_NULL, null=True, blank=True, related_name="blocks")

    manual_expiry_date = models.DateTimeField(blank=True, null=True)
    expiry_date = models.DateTimeField(blank=True, null=True)

    # Flag to set when cart total is checked to avoid deleting when payment activity may be in progress
    time_checked = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['user__username']
        indexes = [
                models.Index(fields=['user', 'paid']),
                models.Index(fields=['user', 'expiry_date']),
                models.Index(fields=['user', '-start_date']),
            ]

    def __str__(self):
        return f"{self.user.username} -- {self.block_config} -- created {self.created_date.strftime('%d %b %Y')}"

    @property
    def cost_with_voucher(self):
        if not self.voucher:
            return self.block_config.cost
        block_cost = Decimal(float(self.block_config.cost))
        if self.voucher.discount_amount:
            if self.voucher.discount_amount > block_cost:
                return 0
            return block_cost - Decimal(self.voucher.discount_amount)
        percentage_to_pay = Decimal((100 - self.voucher.discount) / 100)
        return (block_cost * percentage_to_pay).quantize(Decimal('.01'))

    def get_expiry_date(self):
        # if a manual extended expiry date has been set, use that instead
        # (unless it's been set to be earlier than the calculated expiry date)
        # extended_expiry_date is set to end of day on save, so just return it
        if self.manual_expiry_date:
            return self.manual_expiry_date

        if self.block_config.duration is None:
            return None

        if self.start_date:
            # replace block expiry date with very end of day in local time
            # move forwards 1 day and set hrs/min/sec/microsec to 0, then move
            # back 1 sec
            duration = self.block_config.duration
            expiry_datetime = self.start_date + relativedelta(weeks=duration)
            return end_of_day_in_local_time(expiry_datetime)
        else:
            self.expiry_date = None

    def set_start_date(self):
        # called when a booking is made to ensure block start/expiry is updated to the
        # date of the first open booked event
        # Check for ANY open booking - no-shows still count towards start dates
        open_bookings = self.bookings.filter(status="OPEN").order_by("event__start")
        # set to the earliest start date, including no-shows
        if open_bookings.exists():
            self.start_date = open_bookings.first().event.start
        else:
            self.start_date = None
        self.expiry_date = self.get_expiry_date()
        self.save()

    @property
    def expired(self):
        if self.expiry_date and self.expiry_date < timezone.now():
            return True
        return False

    @property
    def full(self):
        if self.bookings.exists():
            return self.bookings.count() >= self.block_config.size
        return False

    @property
    def active_block(self):
        """
        A block is active if its not full and has been paid for.  This doesn't mean it
        is valid for a specific event (dependent on event date)
        """
        return not self.expired and (not self.full and self.paid)

    @property
    def remaining_count(self):
        return self.block_config.size - self.bookings.count()

    def _valid_and_active_for_event(self, event):
        # hasn't started yet OR event is within block date range
        # Note we've already checked it's active and the right type
        return self.expiry_date is None or event.start < self.expiry_date

    def valid_for_event(self, event):
        # if it's not active we don't care about anything else
        if not self.active_block:
            return False
        if event.course:
            # if the event is part of a course, check if this block is valid for the course
            valid_for_course = self.valid_for_course(course=event.course, event=event)
            if valid_for_course:
                return True
        if not self.block_config.course and self.block_config.event_type == event.event_type:
            # We still get here for an event that's part of a course if this is a non-course block,
            # in case of a course that allows drop-in booking for individual classes
            if event.course and not event.course.allow_drop_in:
                return False
            # event type matches and it's not a course block, check it's valid for this event (hasn't expired)
            return self._valid_and_active_for_event(event)
        return False

    def valid_for_course(self, course, event=None):
        # if it's not active we don't care about anything else
        if not self.active_block:
            return False
        valid_for_course = False
        if self.block_config.course and self.block_config.event_type == course.event_type:
            # it's valid for courses, event type matches
            # check the number of events
            # It's always valid if it's for the full course
            valid_for_course = self.block_config.size == course.number_of_events

        if valid_for_course:
            # it's valid for courses, event type matches, and it's the right size for the course
            # check it's valid for the earliest uncancelled event (hasn't expired)
            # For partial course blocks we can still just check the first uncancelled event;
            # _valid_and_active_for_event only checks that the block expiry date is after the start of the first
            # course event
            event = event or course.uncancelled_events.first()
            valid_for_event = True
            if event:
                # If there's no uncancelled events yet, the block is so far valid for the course in general
                valid_for_event = self._valid_and_active_for_event(event)

            if valid_for_event:
                # make sure it hasn't been used to book events on a different course
                has_bookings_on_other_courses = self.bookings.exclude(event__course=course).exists()
                return not has_bookings_on_other_courses
        return False

    def mark_checked(self):
        self.time_checked = timezone.now()
        self.save()

    @classmethod
    def cleanup_expired_blocks(cls, user=None, use_cache=False):
        if use_cache:
            # check cache to see if we cleaned up recently
            if cache.get("expired_blocks_cleaned"):
                logger.info("Expired blocks cleaned up within past 2 mins; no cleanup required")
                return

        # timeout defaults to 15 mins
        timeout = settings.CART_TIMEOUT_MINUTES
        if user:
            # If we have a user, we're at the checkout, so get all unpaid purchases for
            # this user only
            unpaid_blocks = Block.objects.filter(
                user__in=user.managed_users_including_self, paid=False
            )
        else:
            # no user, doing a general cleanup.  Don't delete anything that was time-checked
            # (done at final checkout stage) within the past 5 mins, in case we delete something
            # that's in the process of being paid
            unpaid_blocks = cls.objects.filter(paid=False).filter(
                models.Q(time_checked__lt=timezone.now() - timedelta(seconds=60 * 5)) | models.Q(time_checked__isnull=True)
            )
        # filter unpaid blocks to those created before the allowed timeout
        expired_blocks = unpaid_blocks.filter(
            created_date__lt=timezone.now() - timedelta(seconds=60 * timeout)
        ).annotate(count=models.Count('bookings__id')).filter(count__gt=0)
        
        if expired_blocks.exists():
            if user is not None:
                ActivityLog.objects.create(
                    log=f"{expired_blocks.count()} unpaid blocks with bookings in cart "
                        f"(ids {','.join(str(block.id) for block in expired_blocks.all())} "
                        f"for user {user} expired and were deleted"
                )
            else:
                ActivityLog.objects.create(
                    log=f"{expired_blocks.count()} unpaid blocks with bookings "
                        f"(ids {','.join(str(block.id) for block in expired_blocks.all())} "
                        f"expired and were deleted"
                )
            # delete individually to ensure save method is called and associated bookings are 
            # deleted
            for block in expired_blocks:
                block.delete()

        if use_cache:
            logger.info("Expired blocks with bookings cleaned up")
            # cache for 2 mins
            cache.set("expired_blocks_cleaned", True, timeout=60*2)

    def delete(self, *args, **kwargs):
        bookings = self.bookings.all() if hasattr(self, "bookings") else []
        if not self.paid:
            booking_ids = "".join([str(bk_id) for bk_id in bookings.values_list("id", flat=True)])
            bookings.delete()
            ActivityLog.objects.create(
                log=f'Booking ids {booking_ids} booked with deleted unpaid block {self.id} have been deleted'
            )
        else:
            for booking in bookings:
                booking.block = None
                booking.save()
                ActivityLog.objects.create(
                    log=f'Booking id {booking.id} booked with deleted block {self.id} has been reset'
                )
        super().delete(*args, **kwargs)

    def save(self, *args, **kwargs):
        self.full_clean()
        # for an existing block, if changed to paid, update purchase date to now
        # (in case a user leaves a block sitting in basket for a while)
        if self.id:
            pre_save_block = Block.objects.get(id=self.id)
            if not pre_save_block.paid and self.paid:
                self.purchase_date = timezone.now()

        # make manual expiry date end of day
        if self.manual_expiry_date:
            self.manual_expiry_date = end_of_day_in_local_time(self.manual_expiry_date)
            self.expiry_date = self.manual_expiry_date

        # start date is set to the first date the block is used and used to generate expiry date
        if self.start_date:
            self.expiry_date = self.get_expiry_date()
        super().save(*args, **kwargs)


class WaitingListUser(models.Model):
    """
    A model to represent a single user on a waiting list for an event
    """
    user = models.ForeignKey(
        User, related_name='waitinglists', on_delete=models.CASCADE
    )
    event = models.ForeignKey(
        Event, related_name='waitinglistusers', on_delete=models.CASCADE
    )
    # date user joined the waiting list
    date_joined = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'event'])
        ]


class GiftVoucherConfig(models.Model):
    """
    Defines configuration for gift vouchers that are available for purchase.
    Each one is associated with EITHER:
    1) one Block config and will be used to generate voucher codes for 100%, one-time use vouchers (BlockVoucher)for one block of the
    specified block config.
    OR:
    2) a discount amount, and will be used to generate voucher codes for one-time use vouchers (TotalVoucher) of that discount
    amount, valid against the user's total checkout amount, irresepctive of items
    """
    block_config = models.ForeignKey(
        BlockConfig, null=True, blank=True, on_delete=models.SET_NULL, related_name="gift_vouchers",
    )
    discount_amount = models.DecimalField(
        verbose_name="Exact amount discount",
        null=True, blank=True, decimal_places=2, max_digits=6
    )
    active = models.BooleanField(default=True, help_text="Display on site; set to False instead of deleting unused gift vouchers")
    duration = models.PositiveIntegerField(default=6, help_text="How many months will this gift voucher last?")

    class Meta:
        ordering = ("block_config", "discount_amount")

    @property
    def cost(self):
        return self.block_config.cost if self.block_config else self.discount_amount

    def __str__(self):
        if self.block_config:
            return f"{self.block_config} -  £{self.cost}"
        return f"Voucher - £{self.cost}"

    def name(self):
        return str(self)

    def clean(self):
        if not (self.block_config or self.discount_amount):
            raise ValidationError("One of credit block or a fixed voucher value is required")
        if self.block_config and self.discount_amount:
            raise ValidationError("Select either a credit block or a fixed voucher value (not both)")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class GiftVoucher(models.Model):
    """Holds information about a gift voucher purchase"""
    gift_voucher_config = models.ForeignKey(GiftVoucherConfig, on_delete=models.CASCADE)
    block_voucher = models.ForeignKey(BlockVoucher, null=True, blank=True, on_delete=models.SET_NULL, related_name="gift_voucher")
    total_voucher = models.ForeignKey(TotalVoucher, null=True, blank=True, on_delete=models.SET_NULL, related_name="gift_voucher")

    invoice = models.ForeignKey(Invoice, null=True, blank=True, on_delete=models.SET_NULL, related_name="gift_vouchers")
    paid = models.BooleanField(default=False)
    slug = models.SlugField(max_length=40, null=True, blank=True)

    @property
    def voucher(self):
        if self.block_voucher:
            return self.block_voucher
        elif self.total_voucher:
            return self.total_voucher

    @property
    def purchaser_email(self):
        if self.voucher:
            return self.voucher.purchaser_email

    @property
    def code(self):
        if self.voucher:
            return self.voucher.code

    @property
    def name(self):
        if self.block_voucher:
            return f"Gift Voucher: {self.gift_voucher_config.block_config.name}"
        elif self.total_voucher:
            return f"Gift Voucher: £{self.total_voucher.discount_amount}"

    def __str__(self):
        return f"{self.code} - {self.name} - {self.purchaser_email}"

    def activate(self):
        """Activate a voucher that isn't already activated, and reset start/expiry dates if necessary"""
        if self.voucher and not self.voucher.activated:
            self.voucher.activated = True
            if self.voucher.start_date < timezone.now():
                self.voucher.start_date = timezone.now()
            if self.gift_voucher_config.duration:
                self.voucher.expiry_date = end_of_day_in_utc(
                    self.voucher.start_date + relativedelta(months=self.gift_voucher_config.duration)
                )
            self.voucher.save()

    def send_voucher_email(self):
        context = {"gift_voucher": self}
        send_user_and_studio_emails(
            context,
            user=None,
            send_to_studio=False,
            subjects={"user": "Gift Voucher"},
            template_short_name="gift_voucher",
            user_email=self.voucher.purchaser_email
        )

    def save(self, *args, **kwargs):
        if not self.id:
            # New gift voucher, create voucher.  Name, message and purchaser will be added by the purchase
            # view after the GiftVoucher is created.
            if self.gift_voucher_config.block_config:
                if self.block_voucher is None:
                    self.block_voucher = BlockVoucher.objects.create(
                        max_per_user=1,
                        max_vouchers=1,
                        discount=100,
                        activated=False,
                        is_gift_voucher=True,
                    )
                    self.block_voucher.block_configs.add(self.gift_voucher_config.block_config)
                    self.total_voucher = None
                elif not self.block_voucher.is_gift_voucher:
                        self.block_voucher.is_gift_voucher = True
                        self.block_voucher.save()
            elif self.gift_voucher_config.discount_amount:
                if self.total_voucher is None:
                    self.total_voucher = TotalVoucher.objects.create(
                        discount_amount=self.gift_voucher_config.discount_amount,
                        max_per_user=1,
                        max_vouchers=1,
                        activated=False,
                        is_gift_voucher=True,
                    )
                    self.block_voucher = None
                elif not self.total_voucher.is_gift_voucher:
                        self.total_voucher.is_gift_voucher = True
                        self.total_voucher.save()
        else:
            # check for changes to voucher type (before payment processed)
            if self.gift_voucher_config.block_config:
                if self.block_voucher and (self.gift_voucher_config.block_config not in self.block_voucher.block_configs.all()):
                    # changing a block voucher to a different block
                    assert not self.paid
                    self.block_voucher.block_configs.clear()
                    self.block_voucher.block_configs.add(self.gift_voucher_config.block_config)
                elif self.block_voucher is None:
                    # changing a total voucher to a block voucher
                    assert not self.paid
                    self.block_voucher = BlockVoucher.objects.create(
                        max_per_user=1,
                        max_vouchers=1,
                        discount=100,
                        activated=False,
                        is_gift_voucher=True,
                    )
                    self.block_voucher.block_configs.add(self.gift_voucher_config.block_config)
                if self.total_voucher:
                    to_delete = self.total_voucher
                    self.total_voucher = None
                    to_delete.delete()
            elif self.gift_voucher_config.discount_amount:
                if self.total_voucher and (self.total_voucher.discount_amount != self.gift_voucher_config.discount_amount):
                    # changing a total voucher to a different amount
                    assert not self.paid
                    self.total_voucher.discount_amount = self.gift_voucher_config.discount_amount
                elif self.total_voucher is None:
                    assert not self.paid
                    # changing a block voucher to a total voucher
                    self.total_voucher = TotalVoucher.objects.create(
                        discount_amount=self.gift_voucher_config.discount_amount,
                        max_per_user=1,
                        max_vouchers=1,
                        activated=False,
                        is_gift_voucher=True,
                    )
                if self.block_voucher:
                    to_delete = self.block_voucher
                    self.block_voucher = None
                    to_delete.delete()
        if self.voucher and not self.slug:
            self.slug = slugify(self.voucher.code[:40])
        super().save(*args, **kwargs)


class SubscriptionConfig(models.Model):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(null=True, blank=True)
    cost = models.DecimalField(max_digits=8, decimal_places=2)
    duration = models.PositiveIntegerField(
        help_text="How long does the subscription run for (weeks/months)?", default=1
    )
    duration_units = models.CharField(max_length=255, default="months", choices=(("weeks", "weeks"), ("months", "months")))
    start_date = models.DateTimeField(
        default=timezone.now,
        null=True, blank=True,
        help_text="Date that this subscription first starts.  If subscription recurs monthly, set to a date 1st-28th to "
                  "ensure consistent recurral."
    )
    recurring = models.BooleanField(default=True, help_text="Subscription automatically renews and bills students")
    start_options = models.CharField(
        max_length=255,
        default="start_date",
        choices=(
            ("start_date", "Start from the specified start date"),
            ("signup_date", "Start from the date students sign up"),
            ("first_booking_date", "Start from date of first booked event"),
        ),
        help_text="Control when subscriptions start.  Choose start date to run the subscription for a set "
                  "time period (e.g. from the 1st of each month).  The first subscription period will start on the start date "
                  "you specify, and subsequent subscription period will recur from that date. Choose sign up date to have the "
                  "subscription start individually for each student from the date they sign up and purchase."
    )
    active = models.BooleanField(default=True, help_text="Visible on site and available to purchase")
    advance_purchase_allowed = models.BooleanField(
        default=True,
        help_text="Allow students to purchase the next period's subscription before the current one has finished. This is "
                  "recommended if this subscription allows students to make bookings for scheduled events."
    )
    partial_purchase_allowed = models.BooleanField(
        default=False,
        help_text="For subscriptions with a specific start date, allow purchase of the current subscription period at "
                  "a reduced price after the first week."
    )
    cost_per_week = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="For subscriptions allowing partial purchase.  The price that will be charged per week/partial "
                  "week remaining in the current subscription period"
    )

    current_subscriber_info = models.TextField(
        null=True, blank=True, help_text="Information that will be displayed in the details for "
                                         "active subscriptions only.  Use this for information that may "
                                         "change with each subscription period, e.g. passwords to content on other sites"
    )

    # dicts, keyed by event type id
    # indicates event types this subscription can be used for, and restrictions on use
    # {
    #   <event_type_id>: {"number_allowed": <int> or None, "allowed_unit": day/week/month}
    # }
    # NOT VALID FOR COURSES
    # Can find valid event types for a single config with EventType.objects.filter(id__in=config.bookable_event_types.keys())
    # find user's subscriptions that are valid for an event type
    # order by next expiry date first (in case of None values, secondary ordering by start and purchase dates
    # subscriptions = user.subscriptions.filter(config__bookable_event_types__has_key(event.event_type.id)).order_by("expiry_date", "start_date", "purchase_date")
    # Then check usages, get the next subscription that is allowed.  Usually there'll only be one, but just in case
    bookable_event_types = models.JSONField(null=True, blank=True, default=dict)
    include_no_shows_in_usage = models.BooleanField(
        default=False,
        help_text="For subscription with limits on bookings: count no-shows "
                  "(i.e. cancellations after the cancellation period has passed) in subscription usage")

    def __str__(self):
        return f"{self.name} ({'active' if self.active else 'inactive'})"

    @property
    def event_types(self):
        if self.bookable_event_types:
            return EventType.objects.filter(id__in=self.bookable_event_types.keys())
        return []

    @property
    def age_restrictions(self):
        for event_type in self.event_types:
            # Return the first age restriction only; we prohibit adding multiple event types with different age
            # restrictions
            if event_type.age_restrictions:
                return f"Valid for {event_type.age_restrictions}"

    def available_to_user(self, user):
        """Check the min/max age limits for event_types on the subscription"""
        for event_type in self.event_types:
            if not event_type.valid_for_user(user):
                return False
        return True

    def is_purchaseable(self):
        """
        A subscription is purchaseable if:
          - it's active
          - it starts from sign up or booking date
          - it starts from a start date AND
            - advance purchase is allowed OR
            - has a current period which hasn't exipred yet OR
            - has a next period which starts within the next 3 days
        """
        if self.active:
            if self.start_options in ["signup_date", "first_booking_date"]:
                return True
            if self.expired():
                # one-off and past now
                return False
            if self.advance_purchase_allowed:
                return True
            current_period_start = self.get_subscription_period_start_date()
            # if advance purchase not allowed, the subscription is purchaseable if there's a
            # there's a current period...
            if current_period_start:
                return True
            # ...or if the next period starts within the next 3 days
            next_period_start = self.get_subscription_period_start_date(next=True)
            return (next_period_start - start_of_day_in_utc(timezone.now())).days <= 3
        return False

    def expired(self):
        # An expired config is a one-off config that's past
        if not self.recurring:
            expiry = self.calculate_next_start_date(self.start_date)
            return expiry < timezone.now()
        return False

    def subscriptions_purchased(self):
        return self.subscription_set.filter(paid=True).count()

    def get_start_options_for_user(self, user, ignore_unpaid=False):
        """
        Get the purchasable subscriptions for this user
        start_options = signup_date:
           check for current subscription - one that is paid, has started and hasn't expired yet
           no current subscription: show option to purchase with start date today
           current subscription AND advance purchase allowed: show option to purchase with start date next period
        start_options = first_booking_date
            check for current active subscription: paid, has start date (i.e. has been used) and hasn't expired yet
            check for pending subscriptions: paid, no start date
            if user has no active or pending subscriptions, show option to purchase
            if user has active, no pending subscriptions AND advance purchase allowed, show option to purchase
        start_options = start_date
            Find current and next start dates based on config start date
            Return both if user doesn't have them yet AND advance purchase allowed
        """
        # Find the non-expired user subscription for this config
        start_date_options = []
        # ignore_unpaid = check for existing subscription that are paid ONLY
        user_subscriptions = user.subscriptions.filter(config=self, expiry_date__gt=timezone.now(), paid=ignore_unpaid)
        if not self.recurring:
            # Not recurring, only one subscription period, start on config start date
            if not user_subscriptions.exists():
                start_date_options.append(self.start_date)

        elif self.start_options == "signup_date":
            # ignore_unpaid = check for existing subscription that are paid ONLY
            active_user_subscriptions = user.subscriptions.filter(
                config=self, start_date__lt=timezone.now(), expiry_date__gt=timezone.now(), paid=ignore_unpaid
            )
            if not active_user_subscriptions:
                start_date_options.append(start_of_day_in_utc(timezone.now()))
            elif self.advance_purchase_allowed or active_user_subscriptions.first().expires_soon():
                current_subscription = active_user_subscriptions.first()
                next_start = self.calculate_next_start_date(current_subscription.start_date)
                start_date_options.append(next_start)

        elif self.start_options == "first_booking_date":
            # ignore_unpaid = check for existing subscription that are paid ONLY
            pending_user_subscriptions = user.subscriptions.filter(config=self, start_date__isnull=True, paid=ignore_unpaid)
            active_user_subscriptions = user.subscriptions.filter(
                config=self, start_date__isnull=False, expiry_date__gt=timezone.now(), paid=ignore_unpaid
            )
            if not active_user_subscriptions.exists() and not pending_user_subscriptions.exists():
                # no subscriptions
                start_date_options.append(None)
            elif active_user_subscriptions.exists() and not pending_user_subscriptions.exists():
                # has an active subscription but no pending, check if allowed to buy another
                if self.advance_purchase_allowed or active_user_subscriptions.first().expires_soon():
                    start_date_options.append(None)

        elif self.start_options == "start_date":
            current_subscription_start_date = self.get_subscription_period_start_date()
            next_subscription_start_date = self.get_subscription_period_start_date(next=True)
            if current_subscription_start_date is not None:
                user_has_current = user_subscriptions.filter(start_date=current_subscription_start_date).exists()
                if not user_has_current and current_subscription_start_date >= self.start_date:
                    start_date_options.append(current_subscription_start_date)

            if next_subscription_start_date is not None:
                user_has_next = user_subscriptions.filter(start_date=next_subscription_start_date).exists()
                if not user_has_next:
                    # can purchase in advance, or next subscription start is within 3 days
                    if self.advance_purchase_allowed or ((next_subscription_start_date - start_of_day_in_utc(timezone.now())).days <= 3):
                        start_date_options.append(next_subscription_start_date)
        return start_date_options

    def calculate_next_start_date(self, input_datetime):
        if self.duration_units == "weeks":
            return start_of_day_in_utc(input_datetime + timedelta(weeks=self.duration))
        else:
            return start_of_day_in_utc(input_datetime + relativedelta(months=self.duration))

    def get_subscription_period_start_date(self, next=False):
        if not self.recurring:
            return self.start_date if not next else None
        # replace expiry date with very end of day in local time
        if self.start_options == "start_date":
            # TODO this is a workaround for Delorean, which currently can't deal with
            # latest tzinfo
            # https://github.com/myusuf3/delorean/issues/110
            naive_now = timezone.now().replace(tzinfo=None)
            # find most recent matching start date from config
            if self.duration_units == "weeks":
                # recurs on the same day of the week
                weekday = self.start_date.weekday()
                if timezone.now().weekday() == weekday:
                    if next:
                        calculated_start = getattr(
                            Delorean(naive_now, timezone="utc"), f"{'next'}_{calendar.day_name[weekday].lower()}"
                        )()
                        calculated_start = start_of_day_in_utc(calculated_start.datetime)
                    else:
                        calculated_start = start_of_day_in_utc(Delorean(timezone.now().replace(tzinfo=pytz.utc), timezone="utc").datetime)
                else:
                    weekday_method = f"{'next' if next else 'last'}_{calendar.day_name[weekday].lower()}"
                    calculated_start = getattr(Delorean(naive_now, timezone="utc"), weekday_method)()
                    calculated_start = start_of_day_in_utc(calculated_start.datetime)
                # get time in weeks between calculated weekday and start
                time_diff = (calculated_start - self.start_date).days / 7
                remainder = time_diff % self.duration
                if next:
                    # we calculated the next weekday already
                    if self.duration > 1:
                        remainder = self.duration - remainder
                    result = calculated_start + timedelta(weeks=remainder)
                else:
                    result = calculated_start - timedelta(weeks=remainder)
            else:
                # recurs monthly
                now = timezone.now()
                day_of_month = self.start_date.day
                datetime_this_month = datetime(day=day_of_month, month=now.month, year=now.year, tzinfo=dt_timezone.utc)
                if now.day >= day_of_month:
                    calculated_start = datetime_this_month + relativedelta(months=1) if next else datetime_this_month
                else:
                    calculated_start = datetime_this_month if next else datetime_this_month - relativedelta(months=1)
                calculated_start = start_of_day_in_utc(calculated_start)
                time_diff = relativedelta(calculated_start, self.start_date)
                remainder = time_diff.months % self.duration
                if next:
                    result = calculated_start + relativedelta(months=remainder)
                else:
                    result = calculated_start - relativedelta(months=remainder)
            return result if result >= self.start_date else None

    def calculate_current_period_cost_as_of_today(self):
        if self.start_options == "start_date" and self.partial_purchase_allowed:
            purchase_datetime = timezone.now()
            current_start = self.get_subscription_period_start_date()
            # current start could be None if the config hasn't started yet
            if current_start and current_start < (purchase_datetime - timedelta(days=6)):
                # purchasing the current period more than a week after the start date
                # calculate the number of weeks/partial weeks left in the subscription period
                time_to_expiry = relativedelta(self.calculate_next_start_date(current_start), purchase_datetime)
                weeks = time_to_expiry.weeks
                remaining_days = time_to_expiry.days % 7
                if weeks > 0 and remaining_days == 0:
                    # if there's less than one full day in a partial week, don't charge a full week for it
                    # (unless it's the last week)
                    weeks_to_charge = weeks
                else:
                    weeks_to_charge = weeks + 1
                return weeks_to_charge * self.cost_per_week
        return self.cost

    def clean(self):
        # 1. if partial_purchase_allowed, cost per week is required
        # 2. if partial_purchase_allowed, start_options must be start_date
        # 3. if start_options is start_date, start date is required
        # 4. if recurring is False, start date is required and start_options must be start_date
        # 5. check no conflicting age restrictions in bookable event types
        if not self.recurring:
            if self.start_options != "start_date":
                raise ValidationError({'start_options': _('Must be start_date for one-off subscriptions.')})
            if not self.start_date:
                raise ValidationError({'start_date': _('This field is required for one-off subscription.')})

        if self.start_options == "start_date" and not self.start_date:
            raise ValidationError({'start_date': _('This field is required for subscriptions starting from a specific date.')})
        if self.partial_purchase_allowed and self.start_options != "start_date":
            raise ValidationError({'partial_purchase_allowed': _('Only valid for subscriptions starting from a specific date.')})
        if self.partial_purchase_allowed and not self.cost_per_week:
            raise ValidationError({'cost_per_week': _('Must be greater than 0 when partial purchase is allowed.')})

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.start_date:
            if self.recurring and self.start_options == "start_date" and self.duration_units == "months" and self.start_date.day > 28:
                self.start_date = self.start_date.replace(day=28)
            # Keep the start date in UTC, otherwise calculating the current/next subscription periods is insanely compilcated
            self.start_date = start_of_day_in_utc(self.start_date)
        if not self.partial_purchase_allowed and self.cost_per_week is not None:
            self.cost_per_week = None
        super(SubscriptionConfig, self).save(*args, **kwargs)


class Subscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="subscriptions")
    config = models.ForeignKey(SubscriptionConfig, on_delete=models.CASCADE)
    invoice = models.ForeignKey(
        Invoice, null=True, blank=True, on_delete=models.SET_NULL, related_name="subscriptions"
    )
    invoiced_amount = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    paid = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        default="active",
        choices=(("pending", "pending"), ("active", "active"), ("paused", "paused"), ("cancelled", "cancelled"))
    )
    purchase_date = models.DateTimeField(default=timezone.now)
    # start date should be specified on instantiation
    start_date = models.DateTimeField(null=True, blank=True)
    # set during save
    expiry_date = models.DateTimeField(null=True, blank=True)

    reminder_sent = models.BooleanField(default=False)

    def __str__(self):
        if self.start_date:
            dates_string = f"starts {self.start_date.strftime('%d %b %Y')} -- expires {self.expiry_date.strftime('%d %b %Y')}"
        else:
            dates_string = "not started yet"
        return f"{self.user.username} -- {self.config.name} -- {dates_string} ({'paid' if self.paid else 'unpaid'})"

    def valid_for_event(self, event):
        if event.course:
            return False
        if not self.paid:
            return False
        if self.config.bookable_event_types:
            bookable_event_type = self.config.bookable_event_types.get(str(event.event_type.id))
            if not bookable_event_type:
                # jsonfield keys should always be strings, but check for the int anyway, just in case
                bookable_event_type = self.config.bookable_event_types.get(event.event_type.id)
            if bookable_event_type:
                # check event date is within subscription dates
                if self.start_date and self.start_date > event.start:
                    # subscription starts after event
                    return False
                if self.expiry_date and self.expiry_date < event.start:
                    # subscription expires before event
                    return False
                # check usages
                allowed_number = bookable_event_type.get("allowed_number")
                if not allowed_number:  # can be None or empty string
                    # no max
                    return True

                this_event_booking = self.bookings.filter(event_id=event.id).first()
                # An OPEN, not no-show booking for this event already is automatically valid
                if this_event_booking is not None and this_event_booking.status == "OPEN" and not this_event_booking.no_show:
                    return True

                allowed_unit = bookable_event_type["allowed_unit"]
                # find existing open bookings on this subscription for same event type
                # OPEN and NOT no-show
                # We include bookings for the current event here - we'll already have returned above if an existing
                # booking is fully open, and we want to keep any no-show/cancelled ones in the counts for usage checks
                existing_open_bookings = self.bookings.filter(event__event_type=event.event_type, status="OPEN")
                # If no existing open bookings, no-show or no no-show, then it's definitely valid
                if not existing_open_bookings.exists():
                    return True

                # If DON'T include no-shows in usage (the default), we remove the no-shows here before we
                # count uses
                existing_bookings = existing_open_bookings
                if not self.config.include_no_shows_in_usage:
                    existing_bookings = existing_open_bookings.filter(no_show=False)

                if event.id in existing_bookings.values_list("event_id", flat=True):
                    allowed_number += 1

                if allowed_unit == "day":
                    # find bookings on same day
                    existing_bookings = existing_bookings.filter(event__start__date=event.start.date())
                    return len(existing_bookings) < allowed_number
                else:
                    start, end = self.subscription_usage_period_dates_for_event(event.start, allowed_unit)
                    # find bookings within dates
                    existing_bookings = existing_bookings.filter(event__start__gte=start, event__start__lt=end)
                    return len(existing_bookings) < allowed_number
        return False

    def subscription_usage_period_dates_for_event(self, event_start_date, allowed_unit):
        if allowed_unit == "week":
            # calculate start and end dates for the week of the event, starting on the start_weekday
            # we always use the day of the week that the subscription starts on as the start point
            subscription_start_weekday = self.start_date.weekday()
            days_from_start = subscription_start_weekday - event_start_date.weekday()
            start = start_of_day_in_utc(event_start_date + timedelta(days_from_start))
            end = start_of_day_in_utc(start + timedelta(weeks=1))
        elif allowed_unit == "month":
            subscription_start_day = self.start_date.day
            # calculate start and end dates for the month of the event, starting on the start_day
            if event_start_date.day >= subscription_start_day:
                start = event_start_date.replace(day=subscription_start_day)
            else:
                start = event_start_date.replace(day=subscription_start_day) - relativedelta(months=1)
            start = start_of_day_in_utc(start)
            end = start_of_day_in_utc(start + relativedelta(months=1))
        return start, end

    def usage_limits(self, event_type):
        # None means either the it's not valid for the event type (but we expect to have checked that already)
        # or usage is unlimited
        usage = self.config.bookable_event_types.get(str(event_type.id), {})
        if usage.get("allowed_number"):
            return usage.get("allowed_number"), usage.get("allowed_unit")

    def usage_for_event_type_and_date(self, event_type, event_date):
        bookable_event_type = self.config.bookable_event_types.get(str(event_type.id))
        existing_open_bookings = self.bookings.filter(event__event_type=event_type, status="OPEN", no_show=False)
        # If no existing fully open bookings at all then usage is 0
        if not existing_open_bookings.exists():
            return 0

        # If DON'T include no-shows in usage (the default), we remove the no-shows here before we
        # count uses
        existing_bookings = existing_open_bookings
        if not self.config.include_no_shows_in_usage:
            existing_bookings = existing_open_bookings.filter(no_show=False)
        if not existing_bookings.exists():
            return 0

        allowed_number = bookable_event_type.get("allowed_number")
        allowed_unit = bookable_event_type.get("allowed_unit")
        if allowed_unit == "day":
            # find bookings on same day
            existing_bookings = existing_bookings.filter(event__start__date=event_date.date())
        else:
            start, end = self.subscription_usage_period_dates_for_event(event_date, allowed_unit)
            # find bookings within dates
            existing_bookings = existing_bookings.filter(event__start__gte=start, event__start__lt=end)
        return existing_bookings.count()

    def set_start_date_from_bookings(self):
        """For subscriptions that start on the date of first booking"""
        # called when a booking is made to ensure subscription start/expiry is updated to the
        # date of the first open booked event
        # Check for ANY open booking - no-shows still count towards start dates
        if self.config.start_options == "first_booking_date":
            open_bookings = self.bookings.filter(status="OPEN").order_by("event__start")
            if open_bookings.exists():
                self.start_date = start_of_day_in_utc(open_bookings.first().event.start)
            else:
                self.start_date = None
            self.save()

    def has_expired(self):
        if self.expiry_date:
            return self.expiry_date < timezone.now()
        return False

    def has_started(self):
        if self.start_date:
            return self.start_date < timezone.now()
        return False

    def is_current(self):
        return self.paid and self.has_started() and not self.has_expired()

    def expires_soon(self):
        if self.expiry_date:
            return (self.expiry_date - timezone.now()).days <= 3
        return False

    def get_expiry_date(self):
        if self.start_date:
            return self.config.calculate_next_start_date(self.start_date)

    def cost_as_of_today(self):
        if self.start_date and self.start_date == self.config.get_subscription_period_start_date():
            # it's for the current period. This will return the calculated current period costs for any
            # config with a start_date start_option and which allows partial purchase
            return self.config.calculate_current_period_cost_as_of_today()
        return self.config.cost

    def save(self, *args, **kwargs):
        self.full_clean()
        # for an existing subscription, if changed to paid, update purchase date and start date to now
        # start date will be re-calculated
        # (in case a user leaves it sitting in basket for a while)
        if self.id:
            pre_save_subscription = Subscription.objects.get(id=self.id)
            if not pre_save_subscription.paid and self.paid:
                self.purchase_date = timezone.now()
                # only reset the start date for signup start options where the start date hasn't been explicitly
                # set to a future date
                if self.config.start_options == "signup_date" and (not self.start_date or self.start_date < timezone.now()):
                    self.start_date = start_of_day_in_utc(timezone.now())
                self.status = "active"

        if not self.paid:
            self.status = "pending"

        self.expiry_date = self.get_expiry_date()
        super().save(*args, **kwargs)


class Booking(models.Model):
    STATUS_CHOICES = (
        ('OPEN', 'Open'),
        ('CANCELLED', 'Cancelled')
    )

    user = models.ForeignKey(
        User, related_name='bookings', on_delete=models.CASCADE
    )
    event = models.ForeignKey(
        Event, related_name='bookings', on_delete=models.CASCADE
    )

    date_booked = models.DateTimeField(default=timezone.now)
    date_rebooked = models.DateTimeField(null=True, blank=True)

    block = models.ForeignKey(
        Block, related_name='bookings', null=True, blank=True, on_delete=models.SET_NULL
    )
    subscription = models.ForeignKey(
        Subscription, related_name='bookings', null=True, blank=True, on_delete=models.SET_NULL
    )
    status = models.CharField(max_length=255, choices=STATUS_CHOICES, default='OPEN')
    attended = models.BooleanField(default=False, help_text='Student has attended this event')
    no_show = models.BooleanField(default=False, help_text='Student booked but did not attend, or cancelled after the allowed cancellation period')
    notes = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        unique_together = ('user', 'event')
        permissions = (
            ("can_view_registers", "Can view registers"),
        )
        indexes = [
            models.Index(fields=['event', 'user', 'status']),
            models.Index(fields=['block']),
        ]
        ordering = ("event__start",)

    def __str__(self):
        return f"{self.event.name} - {self.user.username} - {self.event.start.strftime('%d%b%Y %H:%M')}"

    @cached_property
    def can_cancel(self):
        if not self.event.event_type.allow_booking_cancellation:
            return False
        if self.event.event_type.cancellation_period and \
            self.event.start < (timezone.now() + timedelta(hours=self.event.event_type.cancellation_period)):
            return False
        return True

    @property
    def has_available_block(self):
        return has_available_block(self.user, self.event)

    @property
    def has_available_subscription(self):
        return has_available_subscription(self.user, self.event)

    def is_in_basket(self):
        return self.block is not None and not self.block.paid

    def assign_next_available_subscription_or_block(self, dropin_only=True):
        """
        Checks for and assigns next available subscription or block.
        NOTE: Does not save booking now
        """
        available_subscription = get_available_user_subscription(self.user, self.event)
        if available_subscription:
            self.subscription = available_subscription
        else:
            active_block = get_active_user_block(self.user, self.event, dropin_only=dropin_only)
            if active_block:
                self.block = active_block

    def _old_booking(self):
        if self.pk:
            return Booking.objects.get(pk=self.pk)

    def _is_new_booking(self):
        if not self.pk:
            return True

    def _is_rebooking(self):
        if not self.pk:
            return False
        was_cancelled = self._old_booking().status == 'CANCELLED' and self.status == 'OPEN'
        was_no_show = self._old_booking().no_show and not self.no_show
        return was_cancelled or was_no_show

    def _is_cancellation(self):
        if not self.pk:
            return False
        return self._old_booking().status == 'OPEN' and self.status == 'CANCELLED'

    def clean(self):
        if self.status == "CANCELLED":
            # Booking should never be both cancelled and no-show; reset no-show before clean
            self.no_show = False

        if self._is_rebooking():
            if self.event.spaces_left == 0 and not self.event.course:
                raise ValidationError(
                    _('Attempting to reopen booking for full event %s' % self.event.id)
                )

        if self._is_new_booking() and self.status != "CANCELLED" and \
                self.event.spaces_left == 0:
                    raise ValidationError(
                        _('Attempting to create booking for full event %s (id %s)' % (str(self.event), self.event.id))
                    )

        if self.attended and self.no_show:
            raise ValidationError(_('Booking cannot be both attended and no-show'))

    def save(self, *args, **kwargs):
        self.full_clean()
        if self._is_cancellation() and not self.event.course:
            # cancelling a drop in booking removes it from the block
            self.block = None
            old_block = self._old_booking().block
        else:
            old_block = None
        if self._is_rebooking():
            self.date_rebooked = timezone.now()
        super().save(*args, **kwargs)
        # if there is a block on the booking, make sure its start date is updated
        # if no block, and we cancelled, update the start date on the old block
        if self.block:
            self.block.set_start_date()
        elif old_block:
            old_block.set_start_date()

        # if there is a subscription on the booking, make sure its start date is updated
        if self.subscription:
            self.subscription.set_start_date_from_bookings()


# Model-related utils
def valid_course_block_configs(course, active_only=True):
    if not course.has_started:
        # not started course - course blocks matching size and event type are valid
        all_block_configs = BlockConfig.objects.filter(
            course=True, event_type=course.event_type, size=course.number_of_events
        )
        if active_only:
            return all_block_configs.filter(active=True)
        # return blocks that are active first, and then order by id, latest first
        # If no blocks are active, this means we pick the latest one that matches, which
        # should be the one with the most up to date cost
        return all_block_configs.order_by("-active", "-id")
    return BlockConfig.objects.none()


def valid_dropin_block_configs(
    event=None, event_type=None, active_only=True, size=None
):
    ev_type = event.event_type if event else event_type
    all_block_configs = BlockConfig.objects.filter(
        course=False, event_type=ev_type
    )
    if size:
        all_block_configs.filter(size=size)
    if active_only:
        return all_block_configs.filter(active=True)
    return all_block_configs.order_by("-active", "-id")


def add_to_cart_course_block_config(course):
    # get all block configs valid for the course, whether active or not
    # we want to return an active one first, if possible
    valid_block_configs = valid_course_block_configs(course, active_only=False)
    return valid_block_configs.first()


def add_to_cart_drop_in_block_config(event):
    # get all block configs valid for the event, whether active or not
    # find the ones that have size=1
    # we want to return an active one first, if possible
    valid_block_configs = valid_dropin_block_configs(
        event, active_only=False, size=1
    )
    return valid_block_configs.first()


def has_available_block(user, event, dropin_only=False):
    if event.course and not event.course.allow_drop_in and not dropin_only:
        return any(True for block in user.blocks.all() if block.valid_for_course(event.course))
    else:
        if dropin_only:
            return any(
                True for block in user.blocks.all()
                if not block.block_config.course and block.valid_for_event(event)
            )
        return any(True for block in user.blocks.all() if block.valid_for_event(event))


def has_available_course_block(user, course):
    return any(True for block in user.blocks.all() if block.valid_for_course(course))


def get_active_user_block(user, event, dropin_only=True):
    """
    return the active block for this booking with the soonest expiry date
    Expiry dates can be None if the block hasn't started yet, order by purchase date as well
    """
    if event.course and not dropin_only:
        valid_course_block = get_active_user_course_block(user, event.course)
        # If the course block is valid, or drop in isn't allowed, return it now
        if valid_course_block is not None or not event.course.allow_drop_in:
            return valid_course_block

    blocks = user.blocks.filter(
        block_config__course=False, block_config__event_type=event.event_type
    ).order_by("expiry_date", "purchase_date")
    return next((block for block in blocks if block.valid_for_event(event)), None)


def get_active_user_course_block(user, course):
    blocks = user.blocks.filter(
        block_config__course=True, block_config__event_type=course.event_type
    ).order_by("expiry_date", "purchase_date")
    valid_blocks = (block for block in blocks if block.valid_for_course(course))
    # already sorted by expiry date, so we can just get the next valid one
    # UNLESS the course has started and allows part booking - then we want to make sure we return a valid part
    # block before a full block
    return next(valid_blocks, None)


def iter_available_subscriptions(user, event):
    for subscription in user.subscriptions.filter(
            paid=True, config__bookable_event_types__has_key=str(event.event_type.id)
            ).order_by("expiry_date", "start_date", "purchase_date"):
        if subscription.valid_for_event(event):
            yield subscription


def has_available_subscription(user, event):
    return any(iter_available_subscriptions(user, event))


def get_available_user_subscription(user, event):
    """
    return the available subscription for this booking with the soonest expiry date
    Expiry dates can be None if the subscriptions hasn't started yet, order by purchase date as well
    """
    return next(iter_available_subscriptions(user, event), None)


@receiver(post_delete, sender=GiftVoucher)
def delete_related_voucher(sender, instance, **kwargs):
    if instance.voucher:
        if instance.voucher.basevoucher_ptr_id is None:
            instance.voucher.basevoucher_ptr_id = instance.voucher.id
        instance.voucher.delete()
