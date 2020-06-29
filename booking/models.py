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
    """Categorises events.  Used for assigning to courses and cost categories (see Block Type)"""
    name = models.CharField(max_length=255)
    description = models.TextField(help_text="Description", null=True, blank=True)
    track = models.ForeignKey(Track, on_delete=models.SET_NULL, null=True)

    class Meta:
        unique_together = ("name", "track")

    def __str__(self):
        return f"{self.name} - {self.track}"

class CourseType(models.Model):
    """Holds cost and event info for a Course"""
    event_type = models.ForeignKey(EventType, on_delete=models.CASCADE)
    number_of_events = models.PositiveIntegerField(default=4)

    def __str__(self):
        return f"{self.event_type.name} - {self.number_of_events}"

class Course(models.Model):
    """Associated with a number of Events of the same EventType as defined by the CourseType"""
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    course_type = models.ForeignKey(CourseType, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.name} ({self.course_type})"

class Event(models.Model):
    """A single bookable Event"""
    name = models.CharField(max_length=255)
    event_type = models.ForeignKey(EventType, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.TextField(blank=True, default="")
    start = models.DateTimeField(help_text="Start date and time")
    duration = models.PositiveIntegerField(help_text="Duration in minutes", default=90)
    max_participants = models.PositiveIntegerField(default=10)
    contact_email = models.EmailField(default=settings.DEFAULT_STUDIO_EMAIL)
    cancellation_period = models.PositiveIntegerField(default=24)
    email_studio_when_booked = models.BooleanField(default=False)
    slug = AutoSlugField(populate_from=['name', 'start'], max_length=40, unique=True)
    cancelled = models.BooleanField(default=False)
    allow_booking_cancellation = models.BooleanField(default=True)
    is_online = models.BooleanField(default=False)
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
        booked_number = Booking.objects.filter(event__id=self.id, status='OPEN', no_show=False).count()
        return self.max_participants - booked_number

    @property
    def bookable(self):
        return self.spaces_left > 0

    @property
    def can_cancel(self):
        time_until_event = self.start - timezone.now()
        time_until_event = time_until_event.total_seconds() / 3600
        return time_until_event > self.cancellation_period

    @property
    def show_video_link(self):
        return self.is_online and timezone.now() > self.start - timedelta(minutes=20)

    def get_absolute_url(self):
        return reverse("booking:event_detail", kwargs={'slug': self.slug})

    @property
    def is_past(self):
        return self.start < timezone.now()

    def __str__(self):
        return f"{self.name} - {self.start.astimezone(pytz.timezone('Europe/London')).strftime('%d %b %Y, %H:%M')} ({self.event_type.track})"


class BlockType(models.Model):
    """Holds cost and event info for a Course or block of (drop in) events"""
    identifier = models.CharField(max_length=255)

    # COURSES
    course_type = models.ForeignKey(CourseType, on_delete=models.SET_NULL, null=True)

    # DROP-IN BLOCKS; set this from course type for Courses
    size = models.PositiveIntegerField(help_text="Number of events in block")
    event_type = models.ForeignKey(EventType, on_delete=models.SET_NULL, null=True)

    # COMMON
    cost = models.DecimalField(max_digits=8, decimal_places=2)
    duration = models.PositiveIntegerField(help_text="Number of weeks until block expires (from first use)")
    active = models.BooleanField(default=False)

    def __str__(self):
        return self.identifier

    def save(self, *args, **kwargs):
        if self.course_type:
            self.event_type = self.course_type.event_type
            self.size = self.course_type.number_of_events
        super().save(*args, **kwargs)


class Block(models.Model):
    """
    Block booking
    """
    user = models.ForeignKey(User, related_name='blocks', on_delete=models.CASCADE)
    block_type = models.ForeignKey(BlockType, on_delete=models.CASCADE)
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
        return "{self.user.username} -- {self.block_type} -- purchased {self.purchase_date.strftime('%d %b %Y')}"

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

        # replace block expiry date with very end of day in local time
        # move forwards 1 day and set hrs/min/sec/microsec to 0, then move
        # back 1 sec
        duration = self.block_type.duration
        expiry_datetime = self.start_date + relativedelta(weeks=duration)
        return self._get_end_of_day(expiry_datetime)

    def set_start_date(self):
        # called when a booking is made to ensure block start/expiry is updated to the
        # date of the first booked event
        if has_attr(self, "bookings"):
            self.start_date = self.bookings.first("event__start").start
        self.expiry_date = self.get_expiry_date()
        self.save()

    @cached_property
    def expired(self):
        return self.expiry_date < timezone.now() if self.expiry_date else False

    @property
    def full(self):
        if hasattr(self, "bookings"):
            return self.bookings.count() >= self.block_type.size
        return False

    def active_block(self):
        """
        A block is active if its expiry date has not passed
        AND the number of bookings on it is < size
        AND payment is confirmed
        """
        return not self.expired and not self.full and self.paid
    active_block.boolean = True

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
            self.expiry_date = self.self.manual_expiry_date

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
        if not self.event.allow_booking_cancellation:
            return False
        if self.event.cancellation_period and \
            self.event.start < (timezone.now() + timedelta(hours=self.event.cancellation_period)):
            return False
        return True

    @property
    def has_available_block(self):
        if self.event.course:
            return any(
                block for block in
                Block.objects.select_related("user", "block_type").filter(
                    user=self.user, block_type__course_type=self.event.course.course_type
                )
                if block.active_block()
            )
        else:
            return any(
                block for block in
                Block.objects.select_related("user", "block_type").filter(
                    user=self.user, block_type__course_type__isnull=True,  block_type__event_type=self.event.event_type
                )
                if block.active_block()
            )

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
        if self._is_cancellation():
            # cancelling a booking removes it from the block
            self.block = None
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
    block_types = models.ManyToManyField(BlockType)

    def check_block_type(self, block_type):
        return bool(block_type in self.block_types.all())


class UsedBlockVoucher(models.Model):
    voucher = models.ForeignKey(BlockVoucher, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    block_id = models.CharField(max_length=20, null=True, blank=True)


class GiftVoucherType(models.Model):
    block_type = models.ForeignKey(
        BlockType, null=True, blank=True, on_delete=models.SET_NULL, related_name="gift_vouchers"
    )
    active = models.BooleanField(default=True, help_text="Display on site; set to False instead of deleting unused voucher types")

    @cached_property
    def cost(self):
        return self.block_type.cost

    def __str__(self):
        return f"{self.block_type.identifier} -  £{self.cost}"
