# -*- coding: utf-8 -*-

import logging
import pytz
import shortuuid

from django.db import models
from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from django_extensions.db.fields import AutoSlugField

from datetime import timedelta
from dateutil.relativedelta import relativedelta

from activitylog.models import ActivityLog
from .utils import has_available_block as has_available_block_util

logger = logging.getLogger(__name__)


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
            return Track.objects.first()


class EventType(models.Model):
    """
    Categorises and configures events.
    Used for assigning to courses and cost categories (see Block Type)
    Also defines some common fields
    """
    name = models.CharField(max_length=255)
    description = models.TextField(help_text="Description", null=True, blank=True)
    track = models.ForeignKey(Track, on_delete=models.SET_NULL, null=True)
    contact_email = models.EmailField(default=settings.DEFAULT_STUDIO_EMAIL)
    cancellation_period = models.PositiveIntegerField(default=24)
    email_studio_when_booked = models.BooleanField(default=False)
    allow_booking_cancellation = models.BooleanField(default=True)
    is_online = models.BooleanField(default=False)

    class Meta:
        unique_together = ("name", "track")

    def __str__(self):
        return f"{self.name} - {self.track}"


class CourseType(models.Model):
    """
    Holds size and event type/quantity info for a Course, distinct from the
    specific course events themselves
    """
    event_type = models.ForeignKey(EventType, on_delete=models.CASCADE)
    number_of_events = models.PositiveIntegerField(default=4)

    def __str__(self):
        return f"{self.event_type.name} - {self.number_of_events}"


class Course(models.Model):
    """A collection of specific Events of the number and EventType as defined by the CourseType"""
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    course_type = models.ForeignKey(CourseType, on_delete=models.CASCADE)
    slug = AutoSlugField(populate_from=["name", "course_type"], max_length=40, unique=True)
    cancelled = models.BooleanField(default=False)

    class Meta:
        unique_together = ("name", "course_type")

    @property
    def full(self):
        # A course is full if its events are full, INCLUDING no-shows
        # Only need to check the first event
        event = self.events.first()
        return event.bookings.filter(status="OPEN").count() >= event.max_participants

    def configured(self):
        return self.events.count() == self.course_type.number_of_events

    def __str__(self):
        return f"{self.name} ({self.course_type})"


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
    show_on_site = models.BooleanField(default=False)

    class Meta:
        ordering = ['-start']
        indexes = [
            models.Index(fields=['event_type', 'start', 'cancelled']),
            models.Index(fields=['event_type', 'name', 'start', 'cancelled']),
        ]

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

    def get_absolute_url(self):
        return reverse("booking:event_detail", kwargs={'slug': self.slug})

    @property
    def is_past(self):
        return self.start < timezone.now()

    def __str__(self):
        return f"{self.name} - {self.start.astimezone(pytz.timezone('Europe/London')).strftime('%d %b %Y, %H:%M')} ({self.event_type.track})"



class BaseBlockConfig(models.Model):
    """Holds cost and event info for a Course or block of (drop in) events"""
    identifier = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    cost = models.DecimalField(max_digits=8, decimal_places=2)
    duration = models.PositiveIntegerField(help_text="Number of weeks until block expires (from first use)")
    active = models.BooleanField(default=False)

    def __str__(self):
        return self.identifier


class DropInBlockConfig(BaseBlockConfig):
    # DROP-IN BLOCKS
    size = models.PositiveIntegerField(help_text="Number of events in block")
    event_type = models.ForeignKey(EventType, on_delete=models.SET_NULL, null=True)


class CourseBlockConfig(BaseBlockConfig):
    # COURSES
    course_type = models.ForeignKey(CourseType, on_delete=models.SET_NULL, null=True)

    @cached_property
    def size(self):
        return self.course_type.number_of_events

    @cached_property
    def event_type(self):
        return self.course_type.event_type


class Block(models.Model):
    """
    Block booking
    """
    user = models.ForeignKey(User, related_name='blocks', on_delete=models.CASCADE)
    dropin_block_config = models.ForeignKey(DropInBlockConfig, on_delete=models.SET_NULL, null=True, blank=True)
    course_block_config = models.ForeignKey(CourseBlockConfig, on_delete=models.SET_NULL, null=True, blank=True)
    purchase_date = models.DateTimeField(default=timezone.now)
    start_date = models.DateTimeField(null=True, blank=True)
    paid = models.BooleanField(default=False, help_text='Payment has been made by user')

    manual_expiry_date = models.DateTimeField(blank=True, null=True)
    expiry_date = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['user__username']
        indexes = [
                models.Index(fields=['user', 'paid']),
                models.Index(fields=['user', 'expiry_date']),
                models.Index(fields=['user', '-start_date']),
            ]

    def __str__(self):
        return f"{self.user.username} -- {self.block_config} -- purchased {self.purchase_date.strftime('%d %b %Y')}"

    @cached_property
    def block_config(self):
        return self.dropin_block_config if self.dropin_block_config else self.course_block_config

    def _get_end_of_day(self, input_datetime):
        next_day = (input_datetime + timedelta(
            days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end_of_day_utc = next_day - timedelta(seconds=1)
        uktz = pytz.timezone('Europe/London')
        end_of_day_uk = end_of_day_utc.astimezone(uktz)
        utc_offset = end_of_day_uk.utcoffset()
        return end_of_day_utc - utc_offset

    def get_expiry_date(self):
        # if a manual extended expiry date has been set, use that instead
        # (unless it's been set to be earlier than the calculated expiry date)
        # extended_expiry_date is set to end of day on save, so just return it
        if self.manual_expiry_date:
            return self.extended_expiry_date

        if self.start_date:
            # replace block expiry date with very end of day in local time
            # move forwards 1 day and set hrs/min/sec/microsec to 0, then move
            # back 1 sec
            duration = self.block_config.duration
            expiry_datetime = self.start_date + relativedelta(weeks=duration)
            return self._get_end_of_day(expiry_datetime)
        else:
            self.expiry_date = None

    def set_start_date(self):
        # called when a booking is made to ensure block start/expiry is updated to the
        # date of the first open booked event
        # Check for no-show=False here - no-show bookings shouldn't reset block start dates
        open_bookings = self.bookings.filter(status="OPEN", no_show=False).order_by("event__start")
        if open_bookings.exists():
            self.start_date = open_bookings.first().event.start
        else:
            self.start_date = None
        self.expiry_date = self.get_expiry_date()
        self.save()

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
        return not self.full and self.paid

    def _valid_and_active_for_event(self, event):
        # hasn't started yet OR event is within block date range
        return self.expiry_date is None or event.start < self.expiry_date

    def valid_for_event(self, event):
        # if it's not active we don't care about anything else
        if not self.active_block:
            return False
        if self.dropin_block_config is not None and self.dropin_block_config.event_type == event.event_type:
            # it's the right type of config and event type matches
            return self._valid_and_active_for_event(event)
        return False

    def valid_for_course(self, course):
        # if it's not active we don't care about anything else
        if not self.active_block:
            return False
        if self.course_block_config is not None and self.course_block_config.course_type == course.course_type:
            # it's the right type of config and course type matches
            # check the earliest event
            event = course.events.order_by("start").first()
            return self._valid_and_active_for_event(event)
        return False

    def bookings_made(self):
        """
        Number of bookings made against block
        """
        return self.bookings.count() if hasattr(self, "bookings") else 0

    def delete(self, *args, **kwargs):
        bookings = self.bookings.all() if hasattr(self, "bookings") else []
        for booking in bookings:
            booking.block = None
            booking.save()
            ActivityLog.objects.create(
                log=f'Booking id {booking.id} booked with deleted block {self.id} has been reset'
            )
        super().delete(*args, **kwargs)

    def clean(self):
        if not self.dropin_block_config and not self.course_block_config:
            raise ValidationError({'dropin_block_config': _('One of dropin_block_config or course_block_config is required.')})
        elif self.dropin_block_config and self.course_block_config:
            raise ValidationError({'course_block_config': _('Only one of dropin_block_config or course_block_config can be set.')})

    def save(self, *args, **kwargs):
        # for an existing block, if changed to paid, update purchase date to now
        # (in case a user leaves a block sitting in basket for a while)
        if self.id:
            pre_save_block = Block.objects.get(id=self.id)
            if not pre_save_block.paid and self.paid:
                self.purchase_date = timezone.now()

        # make manual expiry date end of day
        if self.manual_expiry_date:
            self.manual_expiry_date = self._get_end_of_day(self.manual_expiry_date)
            self.expiry_date = self.manual_expiry_date

        # start date is set to the first date the block is used and used to generate expiry date
        if self.start_date:
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
    status = models.CharField(max_length=255, choices=STATUS_CHOICES, default='OPEN')
    attended = models.BooleanField(default=False, help_text='Student has attended this event')
    no_show = models.BooleanField(default=False, help_text='Student paid but did not attend')

    class Meta:
        unique_together = ('user', 'event')
        permissions = (
            ("can_view_registers", "Can view registers"),
        )
        indexes = [
            models.Index(fields=['event', 'user', 'status']),
            models.Index(fields=['block']),
        ]

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
        return has_available_block_util(self.user, self.event)

    def _old_booking(self):
        if self.pk:
            return Booking.objects.get(pk=self.pk)
        return None

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
        if self._is_rebooking():
            if self.event.spaces_left == 0:
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


class BaseVoucher(models.Model):
    discount = models.PositiveIntegerField(
        help_text="Enter a number between 1 and 100"
    )
    start_date = models.DateTimeField(default=timezone.now)
    expiry_date = models.DateTimeField(null=True, blank=True)
    max_vouchers = models.PositiveIntegerField(
        null=True, blank=True, verbose_name='Maximum available vouchers',
        help_text="Maximum uses across all users")
    max_per_user = models.PositiveIntegerField(
        null=True, blank=True, default=1,
        verbose_name="Maximum uses per user",
        help_text="Maximum times this voucher can be used by a single user"
    )
    # for gift vouchers
    is_gift_voucher = models.BooleanField(default=False)
    activated = models.BooleanField(default=True)
    name = models.CharField(null=True, blank=True, max_length=255, help_text="Name of recipient")
    message = models.TextField(null=True, blank=True, max_length=500, help_text="Message (max 500 characters)")
    purchaser_email = models.EmailField(null=True, blank=True)

    def __str__(self):
        return self.code

    @cached_property
    def has_expired(self):
        if self.expiry_date and self.expiry_date < timezone.now():
            return True
        return False

    @cached_property
    def has_started(self):
        return bool(self.start_date < timezone.now() and self.activated)

    def save(self, *args, **kwargs):
        # replace start time with very start of day
        self.start_date = self.start_date.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        if self.expiry_date:
            # replace time with very end of day
            # move forwards 1 day and set hrs/min/sec/microsec to 0, then move
            # back 1 sec
            next_day = (self.expiry_date + timedelta(
                days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            self.expiry_date = next_day - timedelta(seconds=1)
        super().save(*args, **kwargs)


class BlockVoucher(BaseVoucher):
    code = models.CharField(max_length=255, unique=True)
    block_types = models.ManyToManyField(DropInBlockConfig)
    course_types = models.ManyToManyField(CourseBlockConfig)

    def all_block_configs(self):
        return [*list(self.block_types.all()), *list(self.course_types.all())]

    def check_block_config(self, block_config):
        return any(block_config in self.all_block_configs())


class UsedBlockVoucher(models.Model):
    voucher = models.ForeignKey(BlockVoucher, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    block_id = models.CharField(max_length=20, null=True, blank=True)


class GiftVoucherType(models.Model):
    dropin_block_type = models.ForeignKey(
        DropInBlockConfig, null=True, blank=True, on_delete=models.SET_NULL, related_name="dropin_gift_vouchers"
    )
    course_block_type = models.ForeignKey(
        CourseBlockConfig, null=True, blank=True, on_delete=models.SET_NULL, related_name="course_gift_vouchers"
    )
    active = models.BooleanField(default=True, help_text="Display on site; set to False instead of deleting unused voucher types")

    @cached_property
    def block_type(self):
        return self.dropin_block_type if self.dropin_block_type else self.course_block_type

    @cached_property
    def cost(self):
        return self.block_type().cost

    def __str__(self):
        return f"{self.block_type().identifier} -  £{self.cost}"
