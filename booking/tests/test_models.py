# -*- coding: utf-8 -*-
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from datetime import timedelta, datetime
from unittest.mock import patch
from model_bakery import baker
import pytest

from booking.models import (
    Course, Event, EventType, Block, Booking, BlockVoucher, Track,
    BlockConfig, SubscriptionConfig, Subscription
)
from common.test_utils import EventTestMixin, TestUsersMixin

now = timezone.now()


class EventTests(EventTestMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def setUp(self):
        self.create_events_and_course()
        self.event = self.aerial_events[0]
        self.event.max_participants = 2
        self.event.name = 'Test event'
        self.event.save()

    def test_full_with_no_bookings(self):
        assert self.event.full is False
        assert self.event.has_space is True

    def test_full_with_booking(self):
        baker.make(Booking, event=self.event, status="OPEN")
        assert self.event.full is False

        booking = baker.make(Booking, event=self.event, status="OPEN")
        assert self.event.full is True

        # Cancelled and no-shows don't count
        booking.status = "CANCELLED"
        booking.save()
        assert self.event.full is False

        booking.status = "OPEN"
        booking.no_show = True
        booking.save()
        assert self.event.full is False

        # But they do count if the event is part of a course
        self.event.course = self.course
        self.event.save()
        assert self.event.full is True

    def test_absolute_url(self):
        assert self.event.get_absolute_url() == reverse('booking:event', kwargs={'slug': self.event.slug})

    def test_str(self):
        self.event.start = datetime(2015, 1, 1, tzinfo=timezone.utc)
        self.event.save()
        assert str(self.event) == 'Test event - 01 Jan 2015, 00:00 (Adults)'

    def test_can_cancel(self):
        self.event.start = timezone.now() + timedelta(hours=48)
        self.event.save()
        assert self.event.can_cancel is True
        self.event.start = timezone.now() + timedelta(hours=23)
        self.event.save()
        assert self.event.can_cancel is False

        self.event.event_type.cancellation_period = 12
        self.event.event_type.save()
        assert self.event.can_cancel is True

        # can cancel for cancellation period only
        self.event.event_type.allow_booking_cancellation = False
        self.event.event_type.save()
        assert self.event.can_cancel is True

    def test_adding_course_resets_max_participants(self):
        assert self.course.max_participants == 2
        self.event.max_participants = 3
        self.event.save()
        assert self.event.max_participants == 3

        self.event.course = self.course
        self.event.save()
        assert self.event.max_participants == 2

    def test_cannot_add_course_with_different_event_type(self):
        new_course = baker.make(Course)
        with pytest.raises(ValidationError) as error:
            self.event.course = new_course
            self.event.save()
        assert error.value.messages == ['Cannot add this course - event types do not match.']

    def test_cannot_add_course_if_course_already_has_the_full_number_events(self):
        new_course = baker.make(Course, number_of_events=1, event_type=self.event.event_type)
        event = self.aerial_events[1]
        event.course = new_course
        event.save()
        assert new_course.is_configured() is True
        with pytest.raises(ValidationError) as error:
            self.event.course = new_course
            self.event.save()
        assert error.value.messages == ['Cannot add this course - course is already configured with all its events.']

    def test_can_update_event_on_full_course(self):
        # TODO validation check for configured course passes if this event is already on the course
        pass


class BookingTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def setUp(self):
        super().setUp()
        self.create_users()
        self.create_events_and_course()
        self.event = self.aerial_events[0]
        self.event.max_participants = 3
        self.event.start = datetime(2015, 1, 1, 18, 0, tzinfo=timezone.utc)
        self.name = 'Test event'
        self.event.save()

    def test_str(self):
        booking = baker.make(Booking, event=self.event, user=self.student_user)
        assert str(booking), 'Test event - student@test.com - 01Jan2015 18:00'

    def test_booking_full_event(self):
        """
        Test that attempting to create new booking for full event raises
        ValidationError
        """
        baker.make(Booking, event=self.event, _quantity=3)
        with pytest.raises(ValidationError):
            Booking.objects.create(event=self.event, user=self.student_user)

    def test_reopening_booking_full_event(self):
        """
        Test that attempting to reopen a cancelled booking for now full event
        raises ValidationError
        """
        baker.make(Booking, event=self.event, _quantity=3)
        booking = baker.make(Booking, event=self.event, user=self.student_user, status="CANCELLED")
        with pytest.raises(ValidationError):
            booking.status = 'OPEN'
            booking.save()

    @patch('booking.models.timezone')
    def test_reopening_booking_sets_date_reopened(self, mock_tz):
        """
        Test that reopening a cancelled booking for an event with spaces sets
        the rebooking date
        """
        mock_now = datetime(2015, 1, 1, tzinfo=timezone.utc)
        mock_tz.now.return_value = mock_now
        booking = baker.make(Booking, event=self.event, user=self.student_user, status='CANCELLED')

        assert booking.date_rebooked is None
        booking.status = 'OPEN'
        booking.save()
        booking.refresh_from_db()
        assert booking.date_rebooked == mock_now

    @patch('booking.models.timezone')
    def test_reopening_booking_again_resets_date_reopened(self, mock_tz):
        """
        Test that reopening a second time resets the rebooking date
        """
        mock_now = datetime(2015, 3, 1, tzinfo=timezone.utc)
        mock_tz.now.return_value = mock_now

        booking = baker.make(
            Booking, event=self.event, user=self.student_user, status='CANCELLED',
            date_rebooked=datetime(2015, 1, 1, tzinfo=timezone.utc)
        )
        assert booking.date_rebooked == datetime(2015, 1, 1, tzinfo=timezone.utc)
        booking.status = 'OPEN'
        booking.save()
        booking.refresh_from_db()
        assert booking.date_rebooked == mock_now

    def test_cancelling_booking_with_block(self):
        # cancelling removed block and resets the block's start
        block = baker.make(Block, dropin_block_config__size=4)
        booking = baker.make(Booking, event=self.event, status="OPEN")
        assert block.start_date is None
        assert block.expiry_date is None
        booking.block = block
        booking.save()
        assert block.start_date.date() == self.event.start.date()
        assert block.expiry_date is not None

        booking.status = "CANCELLED"
        booking.save()
        block.refresh_from_db()
        assert block.start_date is None
        assert block.expiry_date is None

    def test_setting_booking_with_block_to_no_show(self):
        # cancelling removed block and resets the block's start
        block = baker.make(Block, dropin_block_config__size=4)
        booking = baker.make(Booking, event=self.event, status="OPEN")
        booking.block = block
        booking.save()
        assert block.start_date.date() == self.event.start.date()
        assert block.expiry_date is not None
        booking.no_show = True
        booking.save()
        assert block.start_date.date() == self.event.start.date()
        assert block.expiry_date is not None


class TrackTests(TestCase):

    def test_track_default(self):
        assert Track.objects.exists() is False
        # no tracks, returns None
        assert Track.get_default() is None

        tracks = baker.make(Track, _quantity=4)
        # no default, returns first one
        assert Track.get_default() == Track.objects.first()

        track = tracks[1]
        track.default = True
        track.save()
        assert Track.get_default() == track

    def test_str(self):
        track = baker.make(Track, name="Kids Classes")
        assert str(track) == "Kids Classes"


class EventTypeTests(TestCase):

    def test_str_class(self):
        evtype = baker.make(EventType, name="Aerial", track__name="Kids classes")
        assert str(evtype) == 'Aerial - Kids classes'

    def test_pluralised_label(self):
        evtype = baker.make(EventType)
        assert evtype.label == "class"
        assert evtype.pluralized_label == "classes"

        evtype = baker.make(EventType, label="event")
        assert evtype.pluralized_label == "events"

        evtype = baker.make(EventType, label="party")
        assert evtype.pluralized_label == "parties"

        evtype = baker.make(EventType, label="sheep", plural_suffix="")
        assert evtype.pluralized_label == "sheep"


class CourseTests(EventTestMixin, TestCase):

    def setUp(self):
        self.create_test_setup()
        self.event = self.aerial_events[0]
        self.event.course = self.course
        self.event.save()

    def test_str(self):
        assert str(self.course) == f"{self.course.name} (Aerial - Adults - 3)"

    def test_full(self):
        assert self.course.full is False
        bookings = baker.make(Booking, event=self.event, _quantity=2)
        baker.make(Booking, event=self.course_event, _quantity=2)

        assert self.course.full is True
        booking = bookings[0]
        booking.status = "CANCELLED"
        booking.save()
        # still full
        assert self.course.full is True

    def test_has_started(self):
        # course has 1 event already, which is in future
        assert self.course.has_started is False
        baker.make_recipe(
            "booking.past_event", event_type=self.course.event_type, course=self.course
        )
        assert self.course.has_started is True

    def test_configured(self):
        # A course is configured if it has the right number of events on it
        # Course allows 2 events, already has self.event
        baker.make_recipe(
            "booking.future_event", event_type=self.course.event_type, course=self.course,
            _quantity=1
        )
        assert self.course.is_configured() is True
        self.event.course = None
        self.event.save()
        assert self.course.is_configured() is False

    def test_changing_max_participants_updates_linked_events(self):
        event = baker.make_recipe(
            "booking.future_event", event_type=self.course.event_type, max_participants=20,
        )
        assert event.max_participants == 20
        assert self.course.max_participants == 2
        event.course = self.course
        event.save()
        assert event.max_participants == 2

        self.course.max_participants = 10
        self.course.save()
        event.refresh_from_db()
        assert event.max_participants == 10

    def test_changing_show_on_site_updates_linked_events(self):
        event = baker.make_recipe(
            "booking.future_event", event_type=self.course.event_type, show_on_site=False,
        )
        assert event.show_on_site is False
        assert self.course.show_on_site is True
        event.course = self.course
        event.save()
        assert event.show_on_site is True

    def test_cancelling_course_cancels_linked_events(self):
        event = baker.make_recipe(
            "booking.future_event", event_type=self.course.event_type, cancelled=False,
        )
        assert event.cancelled is False
        assert self.course.cancelled is False
        event.course = self.course
        event.save()

        self.course.cancelled = True
        self.course.save()
        event.refresh_from_db()
        assert event.cancelled is True


class BlockConfigTests(TestCase):

    def test_dropin_block_config_str(self):
        dropin_config = baker.make(BlockConfig, name="A Drop in Block")
        assert str(dropin_config) == "A Drop in Block"

    def test_course_block_config_str(self):
        course_config = baker.make(BlockConfig, name="A Course Block", course=True)
        assert str(course_config) == "A Course Block"

    def test_block_config_size(self):
        # property to make course and drop in block configs behave the same
        dropin_config = baker.make(BlockConfig, name="A Drop in Block", size=4)
        assert dropin_config.size == 4


class BlockVoucherTests(TestCase):

    @patch('booking.models.timezone')
    def test_voucher_start_dates(self, mock_tz):
        # dates are set to end of day
        mock_now = datetime(2016, 1, 5, 16, 30, 30, 30, tzinfo=timezone.utc)
        mock_tz.now.return_value = mock_now
        voucher = baker.make(BlockVoucher, start_date=mock_now)
        assert voucher.start_date == datetime(2016, 1, 5, 0, 0, 0, 0, tzinfo=timezone.utc)

        voucher.expiry_date = datetime(2016, 1, 6, 18, 30, 30, 30, tzinfo=timezone.utc)
        voucher.save()
        assert voucher.expiry_date == datetime(2016, 1, 6, 23, 59, 59, 0, tzinfo=timezone.utc)

    @patch('booking.models.timezone')
    def test_has_expired(self, mock_tz):
        mock_tz.now.return_value = datetime(2016, 1, 5, 12, 30, tzinfo=timezone.utc)

        voucher = baker.make(
            BlockVoucher,
            start_date=datetime(2016, 1, 1, tzinfo=timezone.utc),
            expiry_date=datetime(2016, 1, 4, tzinfo=timezone.utc)
        )
        assert voucher.has_expired

        mock_tz.now.return_value = datetime(2016, 1, 3, 12, 30, tzinfo=timezone.utc)
        assert voucher.has_expired is False

    @patch('booking.models.timezone')
    def test_has_started(self, mock_tz):
        mock_tz.now.return_value = datetime(2016, 1, 5, 12, 30, tzinfo=timezone.utc)

        voucher = baker.make(BlockVoucher, start_date=datetime(2016, 1, 1, tzinfo=timezone.utc))
        assert voucher.has_started

        voucher.start_date = datetime(2016, 1, 6, tzinfo=timezone.utc)
        voucher.save()
        assert voucher.has_started is False

    def test_check_block_config(self):
        dropin_block_configs = baker.make(BlockConfig, _quantity=2)
        course_block_configs = baker.make(BlockConfig, course=True, _quantity=2)
        voucher = baker.make(BlockVoucher)
        voucher.block_configs.add(dropin_block_configs[0], course_block_configs[0])
        assert voucher.check_block_config(dropin_block_configs[0]) is True
        assert voucher.check_block_config(course_block_configs[0]) is True
        assert voucher.check_block_config(dropin_block_configs[1]) is False
        assert voucher.check_block_config(dropin_block_configs[1]) is False

    def test_str(self):
        voucher = baker.make(BlockVoucher, code="testcode")
        assert str(voucher) == 'testcode'


class BlockTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.event_type = baker.make(EventType)
        self.dropin_config = baker.make(BlockConfig, size=2, duration=2, cost=10, event_type=self.event_type)
        self.dropin_block = baker.make(Block, block_config=self.dropin_config, user=self.student_user)

        course_config = baker.make(BlockConfig, duration=2, cost=10, event_type=self.event_type, course=True, size=3)
        self.course_block = baker.make(
            Block, block_config=course_config, user=self.student_user
        )

    def test_block_expiry_date(self):
        """
        Test that block expiry dates are populated correctly
        """
        # Times are in UTC, but converted from local (GMT/BST)
        # No daylight savings
        self.dropin_block.start_date = datetime(2015, 3, 1, 15, 45, tzinfo=timezone.utc)
        # set to 2 weeks after start date, end of day GMT/BST
        assert self.dropin_block.get_expiry_date() == datetime(2015, 3, 15, 23, 59, 59, 999999, tzinfo=timezone.utc)

        # with daylight savings
        self.course_block.start_date = datetime(2015, 6, 1, 12, 42, tzinfo=timezone.utc)
        assert self.course_block.get_expiry_date() == datetime(2015, 6, 15, 22, 59, 59, 999999, tzinfo=timezone.utc)

        self.dropin_config.duration = None
        self.dropin_config.save()
        assert self.dropin_block.get_expiry_date() is None

    def test_block_manual_expiry_date_set_to_end_of_day(self):
        """
        Test that manual expiry dates are set to end of day on save
        """
        self.dropin_block.manual_expiry_date = datetime(2015, 3, 1, 15, 45, tzinfo=timezone.utc)
        self.dropin_block.save()
        expected = datetime.combine(
            datetime(2015, 3, 1, tzinfo=timezone.utc).date(), datetime.max.time()
        )
        expected = expected.replace(tzinfo=timezone.utc)
        assert self.dropin_block.get_expiry_date() == expected

    @patch('booking.models.timezone.now')
    def test_block_purchase_date_reset_on_paid(self, mock_now):
        """
        Test that a block's purchase date is set to current date on payment
        """
        now = datetime(2015, 2, 1, tzinfo=timezone.utc)
        mock_now.return_value = now

        self.dropin_block.purchase_date = now - timedelta(12)
        self.dropin_block.save()

        self.dropin_block.paid = True
        self.dropin_block.save()
        assert self.dropin_block.purchase_date == now

    def test_active(self):
        # block is not used, but also not paid
        assert self.dropin_block.active_block is False
        # set paid
        self.dropin_block.paid = True
        self.dropin_block.save()
        assert self.dropin_block.active_block is True

    def test_full(self):
        """
        Test that active is False if a block is full
        """
        self.dropin_block.paid = True
        self.dropin_block.save()
        assert self.dropin_block.active_block is True

        baker.make(Booking, block=self.dropin_block, _quantity=2)
        assert self.dropin_block.active_block is False
        assert self.dropin_block.full is True

    @patch('booking.models.timezone.now')
    def test_str(self, mock_now):
        mock_now.return_value = datetime(2015, 2, 1, tzinfo=timezone.utc) # this will be purchase date, used in str
        self.dropin_block.paid = True
        self.dropin_block.save()

        assert str(self.dropin_block) == f'{self.dropin_block.user.username} -- {self.dropin_block.block_config} -- purchased 01 Feb 2015'

    def test_cost_with_voucher(self):
        voucher = baker.make(BlockVoucher, code='123', discount=50)
        voucher.block_configs.add(self.dropin_block.block_config)
        self.dropin_block.voucher = voucher
        self.dropin_block.save()
        assert self.dropin_block.cost_with_voucher == 5.00

    def test_start_and_expiry_dates(self):
        # default is None
        assert self.dropin_block.start_date is None

        # set to date of first class when first used
        event1_start = timezone.now() + timedelta(10)
        booking1 = baker.make(Booking, block=self.dropin_block, event__start=event1_start)
        assert self.dropin_block.start_date == event1_start
        assert self.dropin_block.expiry_date.date() == (event1_start + timedelta(weeks=2)).date()

        # using for an earlier event adjusts start and expiry date
        event2_start = timezone.now() + timedelta(5)
        booking2 = baker.make(Booking, block=self.dropin_block, event__start=event2_start)
        assert self.dropin_block.start_date == event2_start
        assert self.dropin_block.expiry_date.date() == (event2_start + timedelta(weeks=2)).date()

        # using for a later class does not change start and expiry date
        event3_start = timezone.now() + timedelta(8)
        booking3 = baker.make(Booking, block=self.dropin_block, event__start=event3_start)
        assert self.dropin_block.start_date == event2_start
        assert self.dropin_block.expiry_date.date() == (event2_start + timedelta(weeks=2)).date()

        # manual expiry overrides calculated expiry always
        manual_ex = timezone.now() + timedelta(14)
        self.dropin_block.manual_expiry_date = manual_ex
        self.dropin_block.save()
        assert self.dropin_block.expiry_date.date() == manual_ex.date()
        assert self.dropin_block.start_date == event2_start

        # cancelling all classes sets both start and expiry to None
        self.dropin_block.manual_expiry_date = None
        self.dropin_block.save()
        for booking in [booking1, booking2, booking3]:
            booking.status = "CANCELLED"
            booking.save()
        self.dropin_block.refresh_from_db()
        assert self.dropin_block.start_date is None
        assert self.dropin_block.expiry_date is None

    def test_valid_for_event(self):
        # the right event type
        valid_event = baker.make(Event, event_type=self.event_type)
        # wrong event type
        invalid_event = baker.make(Event)
        # the right event type, but part of a course
        course = baker.make(Course, event_type=self.event_type, number_of_events=3)
        invalid_course_event = baker.make(Event, course=course, event_type=self.event_type)

        # not valid for anything until paid
        assert not self.dropin_block.valid_for_event(valid_event)
        self.dropin_block.paid = True
        self.dropin_block.save()

        assert self.dropin_block.valid_for_event(valid_event)
        assert not self.dropin_block.valid_for_event(invalid_event)
        assert not self.dropin_block.valid_for_event(invalid_course_event)

    def test_valid_for_course(self):
        # valid course
        valid_course = baker.make(Course, event_type=self.event_type, number_of_events=3)
        baker.make(Event, course=valid_course, event_type=self.event_type)

        # valid course - no events
        valid_course1 = baker.make(Course, event_type=self.event_type, number_of_events=3)

        # invalid course - wrong type
        invalid_course2 = baker.make(Course)
        baker.make(Event, course=invalid_course2, event_type=invalid_course2.event_type)

        # not valid for anything until paid
        assert not self.course_block.valid_for_course(valid_course)
        self.course_block.paid = True
        self.course_block.save()

        assert self.course_block.valid_for_course(valid_course)
        assert self.course_block.valid_for_course(valid_course1)
        assert not self.course_block.valid_for_course(invalid_course2)

    def test_delete(self):
        # deleting block removes it from bookings
        booking1 = baker.make(Booking, block=self.dropin_block)
        assert booking1.block == self.dropin_block
        self.dropin_block.delete()
        booking1.refresh_from_db()
        assert booking1.block is None


class SubscriptionConfigTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()

    def test_subscription_config_str(self):
        subscription_config = baker.make(SubscriptionConfig, name="membership")
        assert str(subscription_config) == "membership (active)"

    def test_start_date_set_to_start_of_day(self):
        start_date = datetime(2020, 1, 1, 13, 30, tzinfo=timezone.utc)
        subscription_config = baker.make(SubscriptionConfig, start_date=start_date)
        assert subscription_config.start_date.day == 1
        assert subscription_config.start_date.hour == 0
        assert subscription_config.start_date.minute == 0

        # DST; always set to UTC still
        start_date = datetime(2020, 8, 1, 13, 30, tzinfo=timezone.utc)
        subscription_config = baker.make(SubscriptionConfig, start_date=start_date)
        assert subscription_config.start_date.day == 1
        assert subscription_config.start_date.hour == 0
        assert subscription_config.start_date.minute == 0

        # update DST start date to another date
        start_date = datetime(2020, 8, 2, 14, 30, tzinfo=timezone.utc)
        subscription_config.start_date = start_date
        subscription_config.save()
        assert subscription_config.start_date.day == 2
        assert subscription_config.start_date.hour == 0
        assert subscription_config.start_date.minute == 0

        # update DST start date with a 0, 0 start date
        start_date = datetime(2020, 8, 3, 0, 0, tzinfo=timezone.utc)
        subscription_config.start_date = start_date
        subscription_config.save()
        assert subscription_config.start_date.day == 3
        assert subscription_config.start_date.hour == 0
        assert subscription_config.start_date.minute == 0

    def test_validation_start_date(self):
        # start_date start options requires start date
        with pytest.raises(ValidationError):
            baker.make(SubscriptionConfig, start_options="start_date", start_date=None)
        baker.make(SubscriptionConfig, start_options="start_date", start_date=timezone.now())

    def test_validation_partial_purchase_allowed(self):
        # partial_purchase_allowed requires a cost_per_week and start date start options
        with pytest.raises(ValidationError):
            baker.make(SubscriptionConfig, partial_purchase_allowed=True, start_date=None, start_options="signup_date")
        with pytest.raises(ValidationError):
            baker.make(SubscriptionConfig, partial_purchase_allowed=True, start_date=timezone.now(), start_options="signup_date")
        with pytest.raises(ValidationError):
            baker.make(SubscriptionConfig, partial_purchase_allowed=True, start_date=timezone.now(), start_options="start_date")
        baker.make(
            SubscriptionConfig, partial_purchase_allowed=True, start_date=timezone.now(), start_options="start_date",
            cost_per_week=5,
        )

    def test_validation_not_recurring(self):
        # one off subscription requires a start date start options
        with pytest.raises(ValidationError):
            baker.make(SubscriptionConfig, recurring=False, start_date=None, start_options="signup_date")
        with pytest.raises(ValidationError):
            baker.make(SubscriptionConfig, recurring=False, start_date=timezone.now(), start_options="signup_date")
        baker.make(
            SubscriptionConfig, recurring=False, start_date=timezone.now(), start_options="start_date",
        )

    def test_start_date_with_monthly_recurrence(self):
        # if day for recurrence is > 28 and recurrence is in months, set start date to 28th
        config = baker.make(
            SubscriptionConfig, start_date=datetime(2020, 1, 31, 12, 0, tzinfo=timezone.utc), recurring=False
        )
        assert config.start_date.day == 31
        config = baker.make(
            SubscriptionConfig, start_date=datetime(2020, 1, 31, 12, 0, tzinfo=timezone.utc), recurring=True,
            duration=4, duration_units="weeks"
        )
        assert config.start_date.day == 31
        config = baker.make(
            SubscriptionConfig, start_date=datetime(2020, 1, 31, 12, 0, tzinfo=timezone.utc), recurring=True,
            duration=2, duration_units="months"
        )
        assert config.start_date.day == 28

    @patch("booking.models.timezone.now")
    def test_is_purchaseable(self, mock_now):
        mock_now.return_value = datetime(2020, 3, 10, 12, 0, tzinfo=timezone.utc)

        # inactive
        config = baker.make(
            SubscriptionConfig, start_date=datetime(2020, 2, 4, 0, 0, tzinfo=timezone.utc), recurring=True,
            active=False
        )
        assert config.is_purchaseable() is False

        # active and recurring
        config = baker.make(
            SubscriptionConfig, start_date=datetime(2020, 2, 4, 0, 0, tzinfo=timezone.utc), recurring=True,
            active=True
        )
        assert config.is_purchaseable() is True

        # active one-off, not expired
        config = baker.make(
            SubscriptionConfig, start_date=datetime(2020, 3, 20, 0, 0, tzinfo=timezone.utc), recurring=False,
            active=True, start_options="start_date", duration=1, duration_units="months"
        )
        assert config.is_purchaseable() is True

        # active one-off, expired
        # starts 3rd, duration 1 week, expires start of 10th. Today is the 10th, so now expired.
        config = baker.make(
            SubscriptionConfig, start_date=datetime(2020, 3, 3, 0, 0, tzinfo=timezone.utc), recurring=False,
            active=True, start_options="start_date", duration=1, duration_units="weeks"
        )
        assert config.is_purchaseable() is False


@pytest.mark.django_db
class TestSubscriptionConfigStartDates:

    @pytest.mark.parametrize(
        "now_value,config_kwargs,expected_current_start_date,expected_current_next_start_date",
        [
            (
                datetime(2020, 7, 15, 12, 0, tzinfo=timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 5, 3, 12, 0, tzinfo=timezone.utc),  # Sun
                    "duration": 1,
                },
                datetime(2020, 7, 12, 0, 0, tzinfo=timezone.utc), datetime(2020, 7, 19, 0, 0, tzinfo=timezone.utc)
            ),
            (
                # start Sun 3 May; repeats every 3 weeks
                # 3, 24 May, 14 Jun, 5 Jul, 26 Jul
                datetime(2020, 7, 15, 12, 0, tzinfo=timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 5, 3, 12, 0, tzinfo=timezone.utc),  # Sun
                    "duration": 3,
                },
                datetime(2020, 7, 5, 0, 0, tzinfo=timezone.utc), datetime(2020, 7, 26, 0, 0, tzinfo=timezone.utc)
            ),
            (
                # start Sun 3 May; repeats every 4 weeks
                # 3, 31 May, 28 Jun, 26 Jul
                datetime(2020, 7, 15, 12, 0, tzinfo=timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 5, 3, 12, 0, tzinfo=timezone.utc),  # Sun
                    "duration": 4,
                },
                datetime(2020, 6, 28, 0, 0, tzinfo=timezone.utc), datetime(2020, 7, 26, 0, 0, tzinfo=timezone.utc)
            ),
            (
                # start Sun 3 May; repeats every 2 weeks
                # 3, 17, 31 May, 14, 28 Jun, 12, 26 Jul
                datetime(2020, 7, 15, 12, 0, tzinfo=timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 5, 3, 12, 0, tzinfo=timezone.utc),  # Sun
                    "duration": 2,
                },
                datetime(2020, 7, 12, 0, 0, tzinfo=timezone.utc), datetime(2020, 7, 26, 0, 0, tzinfo=timezone.utc)
            ),
            (
                # start Mon 1 Jun; repeats every 2 weeks
                # 1, 15, 29 Jun, 13, 27 Jul
                datetime(2020, 7, 15, 12, 0, tzinfo=timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 6, 1, 12, 0, tzinfo=timezone.utc),  # Mon
                    "duration": 2,
                },
                datetime(2020, 7, 13, 0, 0, tzinfo=timezone.utc), datetime(2020, 7, 27, 0, 0, tzinfo=timezone.utc)
            ),
            (
                # start Mon 1 June; repeats every 4 weeks
                # 1, 29 Jun, 27 Jul
                datetime(2020, 7, 15, 12, 0, tzinfo=timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 6, 1, 12, 0, tzinfo=timezone.utc),  # Mon
                    "duration": 4,
                },
                datetime(2020, 6, 29, 0, 0, tzinfo=timezone.utc), datetime(2020, 7, 27, 0, 0, tzinfo=timezone.utc)
            ),
            (
                # start Mon 1 June; repeats every 3 weeks
                # 1, 22 Jun, 13 Jul, 3 Aug
                datetime(2020, 7, 15, 12, 0, tzinfo=timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 6, 1, 12, 0, tzinfo=timezone.utc),  # Mon
                    "duration": 3,
                },
                datetime(2020, 7, 13, 0, 0, tzinfo=timezone.utc), datetime(2020, 8, 3, 0, 0, tzinfo=timezone.utc)
            ),
            (
                # start Mon 1 June; repeats every 1 week
                # 1, 22 Jun, 13 Jul, 3 Aug
                datetime(2020, 7, 15, 12, 0, tzinfo=timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 6, 1, 12, 0, tzinfo=timezone.utc),  # Mon
                    "duration": 1,
                },
                datetime(2020, 7, 13, 0, 0, tzinfo=timezone.utc), datetime(2020, 7, 20, 0, 0, tzinfo=timezone.utc)
            ),
        ],
    )
    def test_get_subscription_period_start_date_recurring_weekly(
            self, mocker, now_value, config_kwargs, expected_current_start_date, expected_current_next_start_date
    ):
        mock_now = mocker.patch("booking.models.timezone.now")
        mock_now.return_value = now_value
        config = baker.make(
            SubscriptionConfig,
            duration_units="weeks",
            start_options="start_date",
            **config_kwargs
        )
        assert config.get_subscription_period_start_date() == expected_current_start_date
        assert config.get_subscription_period_start_date(next=True) == expected_current_next_start_date

    @pytest.mark.parametrize(
        "now_value,config_kwargs,expected_current_start_date,expected_current_next_start_date",
        [
            (
                datetime(2020, 7, 15, 12, 0, tzinfo=timezone.utc),
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
                    "duration": 1, "start_options": "signup_date",
                },
                None, None
            ),
            (
                datetime(2020, 7, 15, 12, 0, tzinfo=timezone.utc),
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
                    "duration": 1, "start_options": "first_booking_date",
                },
                None, None
            ),
            (
                datetime(2020, 7, 15, 12, 0, tzinfo=timezone.utc),  # DST now
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
                    "duration": 1, "start_options": "start_date",
                },
                datetime(2020, 7, 3, 0, 0, tzinfo=timezone.utc), datetime(2020, 8, 3, 0, 0, tzinfo=timezone.utc)
            ),
            (
                datetime(2020, 2, 15, 12, 0, tzinfo=timezone.utc),  # not DST now
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
                    "duration": 1, "start_options": "start_date",
                },
                datetime(2020, 2, 3, 0, 0, tzinfo=timezone.utc), datetime(2020, 3, 3, 0, 0, tzinfo=timezone.utc)
            ),
            (
                datetime(2020, 2, 3, 12, 0, tzinfo=timezone.utc),  # now day same as start day
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
                    "duration": 1, "start_options": "start_date",
                },
                datetime(2020, 2, 3, 0, 0, tzinfo=timezone.utc), datetime(2020, 3, 3, 0, 0, tzinfo=timezone.utc)
            ),
            (
                datetime(2020, 2, 1, 12, 0, tzinfo=timezone.utc),  # now day before start day
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
                    "duration": 1, "start_options": "start_date",
                },
                datetime(2020, 1, 3, 0, 0, tzinfo=timezone.utc), datetime(2020, 2, 3, 0, 0, tzinfo=timezone.utc)
            ),
            (
                datetime(2020, 2, 1, 12, 0, tzinfo=timezone.utc),  # now before start, 2 month repeat
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
                    "duration": 2, "start_options": "start_date",
                },
                datetime(2020, 1, 3, 0, 0, tzinfo=timezone.utc), datetime(2020, 3, 3, 0, 0, tzinfo=timezone.utc)
            ),
            (
                # 2 month repeat Jan/Mar/May/Jul, now=June
                datetime(2020, 6, 15, 12, 0, tzinfo=timezone.utc),
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
                    "duration": 2, "start_options": "start_date",
                },
                datetime(2020, 5, 3, 0, 0, tzinfo=timezone.utc), datetime(2020, 7, 3, 0, 0, tzinfo=timezone.utc)
            ),
            (
                # repeats every 2 months from Jun - Jun/Aug/Oct/Dec, now=Nov
                datetime(2020, 11, 15, 12, 0, tzinfo=timezone.utc),
                {
                    "start_date": datetime(2020, 6, 10, 12, 0, tzinfo=timezone.utc),
                    "duration": 2, "start_options": "start_date",
                },
                datetime(2020, 10, 10, 0, 0, tzinfo=timezone.utc), datetime(2020, 12, 10, 0, 0, tzinfo=timezone.utc)
            )

        ]
    )
    def test_get_subscription_period_start_date_recurring_monthly(
            self, mocker, now_value, config_kwargs, expected_current_start_date, expected_current_next_start_date
    ):
        mock_now = mocker.patch("booking.models.timezone.now")
        mock_now.return_value = now_value
        config = baker.make(
            SubscriptionConfig,
            duration_units="months",
            **config_kwargs
        )
        assert config.get_subscription_period_start_date() == expected_current_start_date
        assert config.get_subscription_period_start_date(next=True) == expected_current_next_start_date


@pytest.mark.django_db
class TestStartDatesOfferendToUser:

    @pytest.mark.parametrize(
        "now_value,start,duration,duration_units,start_option,advance_purchase_allowed,expected_start_dates",
        [
            (
                datetime(2020, 7, 15, tzinfo=timezone.utc), datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
                1, "months", "signup_date", True,
                [datetime(2020, 7, 15, tzinfo=timezone.utc)]  # starts on purchase date (today)
            ),
            (
                datetime(2020, 7, 15, tzinfo=timezone.utc), datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
                1, "months", "signup_date", False,
                [datetime(2020, 7, 15, tzinfo=timezone.utc)]  # starts on purchase date (today)
            ),
            (
                datetime(2020, 7, 15, tzinfo=timezone.utc), datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
                1, "months", "first_booking_date", True,
                [None]  # not start date, starts when first used
            ),
            (
                datetime(2020, 7, 15, tzinfo=timezone.utc), datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
                1, "months", "first_booking_date", False,
                [None]  # not start date, starts when first used
            ),
            (
                datetime(2020, 7, 15, tzinfo=timezone.utc), datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
                1, "months", "start_date", True,
                [datetime(2020, 7, 3, tzinfo=timezone.utc), datetime(2020, 8, 3, tzinfo=timezone.utc)]
            ),
            (
                datetime(2020, 7, 15, tzinfo=timezone.utc), datetime(2020, 6, 19, 12, 0, tzinfo=timezone.utc),
                1, "months", "start_date", False,
                [datetime(2020, 6, 19, tzinfo=timezone.utc)]
            ),
            (
                datetime(2020, 7, 15, tzinfo=timezone.utc), datetime(2020, 6, 18, 12, 0, tzinfo=timezone.utc),
                1, "months", "start_date", False,
                [datetime(2020, 6, 18, tzinfo=timezone.utc), datetime(2020, 7, 18, tzinfo=timezone.utc)]
            ),
            (
                datetime(2020, 7, 15, tzinfo=timezone.utc), datetime(2020, 7, 20, 12, 0, tzinfo=timezone.utc),
                1, "months", "start_date", True,
                [datetime(2020, 7, 20, tzinfo=timezone.utc)]
            ),
            (
                datetime(2020, 7, 15, tzinfo=timezone.utc), datetime(2020, 8, 15, 12, 0, tzinfo=timezone.utc),
                1, "months", "start_date", True,
                [datetime(2020, 8, 15, tzinfo=timezone.utc)]
            ),
            (
                datetime(2020, 7, 20, tzinfo=timezone.utc), datetime(2020, 7, 1, 0, 0, tzinfo=timezone.utc),
                2, "weeks", "start_date", True,
                [datetime(2020, 7, 15, tzinfo=timezone.utc), datetime(2020, 7, 29, tzinfo=timezone.utc)]
            ),
        ],
        ids=[
            "1. starts on sign up date, advance purchase allowed, one start option only, starts today",
            "2. starts on sign up date, advance purchase not allowed, one start option only, starts today",
            "3. starts on first booking date, advance purchase allowed, one start option only, start None",
            "4. starts on first booking date, advance purchase not allowed, one start option only, start None",
            "5. starts from start date, advance purchase allowed, current and next start options",
            "6. starts from start date, advance purchase not allowed, current only",
            "7. starts from start date, advance purchase not allowed but next is <= 3 days away, current and next options",
            "8. starts from start date, advance purchase allowed, start date in future, next only",
            "9. starts from start date, advance purchase allowed, current start is today, current only",
            "10. starts on sign up date, advance purchase allowed, duration in weeks",
        ]
    )
    def test_start_options_for_user_no_existing_subscription(
            self, student_user, mocker,
            now_value, start, duration, duration_units, start_option, advance_purchase_allowed, expected_start_dates

    ):
        mock_now = mocker.patch("booking.models.timezone.now")
        mock_now.return_value = now_value
        config = baker.make(
            SubscriptionConfig,
            start_date=start,
            duration=duration,
            duration_units=duration_units,
            start_options=start_option,
            advance_purchase_allowed=advance_purchase_allowed,
        )
        start_options_for_user = config.get_start_options_for_user(student_user)
        assert start_options_for_user == expected_start_dates

    def test_start_options_for_signup_config_with_existing_subscription(self, student_user, mocker):
        mock_now = mocker.patch("booking.models.timezone.now")
        mock_now.return_value = datetime(2020, 7, 15, tzinfo=timezone.utc)
        signup_config = baker.make(
            SubscriptionConfig,
            start_date=datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
            duration=1,
            duration_units="months",
            start_options="signup_date",
            advance_purchase_allowed=True,
        )
        baker.make(
            Subscription, user=student_user, config=signup_config,
            start_date=datetime(2020, 7, 1, tzinfo=timezone.utc)
        )
        # starts on purchase date, user already has unexpired subscription, show option for one month from last start
        start_options = signup_config.get_start_options_for_user(student_user)
        assert start_options == [datetime(2020, 8, 1, tzinfo=timezone.utc)]

    def test_start_options_for_first_booking_config_with_existing_subscription(self, student_user, mocker):
        mock_now = mocker.patch("booking.models.timezone.now")
        mock_now.return_value = datetime(2020, 7, 15, tzinfo=timezone.utc)

        first_booking_date_config = baker.make(
            SubscriptionConfig,
            start_date=datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
            duration=1,
            duration_units="months",
            start_options="first_booking_date",
            advance_purchase_allowed=True,
        )
        first_booking_date_subscription = baker.make(
            Subscription, user=student_user, config=first_booking_date_config,
            start_date=None
        )

        # starts on first booking date, date, user already has pending subscription, no options
        start_options = first_booking_date_config.get_start_options_for_user(student_user)
        assert start_options == []
        assert first_booking_date_subscription.expiry_date is None
        # starts on first booking date, date, user already has unexpired used subscription, option with no start date
        baker.make(
            Booking, event__start=datetime(2020, 8, 1, 12, 30, tzinfo=timezone.utc),
            subscription=first_booking_date_subscription, user=student_user
        )
        # booking has set subscription start and expiry
        first_booking_date_subscription.refresh_from_db()
        assert first_booking_date_subscription.start_date == datetime(2020, 8, 1, 0, 0, tzinfo=timezone.utc)
        assert first_booking_date_subscription.expiry_date == datetime(2020, 9, 1, 23, 59, 59, 999999, tzinfo=timezone.utc)
        start_options = first_booking_date_config.get_start_options_for_user(student_user)
        assert start_options == [None]

    @pytest.mark.parametrize(
        "now_value,start,duration,duration_units,start_option,advance_purchase_allowed,subscription_starts,expected_start_dates",
        [
            (
                datetime(2020, 7, 15, tzinfo=timezone.utc), datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
                1, "months", "start_date", True,
                [datetime(2020, 7, 3, tzinfo=timezone.utc)],
                [datetime(2020, 8, 3, tzinfo=timezone.utc)]
            ),
            (
                datetime(2020, 7, 15, tzinfo=timezone.utc), datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
                1, "months", "start_date", True,
                [datetime(2020, 7, 3, tzinfo=timezone.utc), datetime(2020, 8, 3, tzinfo=timezone.utc)],
                []
            ),
            (
                datetime(2020, 7, 15, tzinfo=timezone.utc), datetime(2020, 1, 3, 12, 0, tzinfo=timezone.utc),
                1, "months", "start_date", True,
                [datetime(2020, 6, 3, tzinfo=timezone.utc)],
                [datetime(2020, 7, 3, tzinfo=timezone.utc), datetime(2020, 8, 3, tzinfo=timezone.utc)]
            ),
        ],
        ids=[
            "1. start_date config: unexpired exists for current, advance allowed, show next only",
            "2. start_date config: unexpired exists for current and next, advance allowed, no options",
            "3. start_date config: expired exists, advance allowed, show both",
        ]
    )
    def test_start_options_for_user_with_existing_subscription_start_date_config(
            self, student_user, mocker, now_value, start, duration, duration_units, start_option, advance_purchase_allowed,
            subscription_starts, expected_start_dates

    ):
        mock_now = mocker.patch("booking.models.timezone.now")
        mock_now.return_value = now_value
        config = baker.make(
            SubscriptionConfig,
            start_date=start,
            duration=duration,
            duration_units=duration_units,
            start_options=start_option,
            advance_purchase_allowed=advance_purchase_allowed,
        )
        for subscription_start in subscription_starts:
            baker.make(Subscription, user=student_user, config=config, start_date=subscription_start)
        start_options_for_user = config.get_start_options_for_user(student_user)
        assert start_options_for_user == expected_start_dates


class SubscriptionTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()

    def test_str(self):
        pass

    def test_expiry_date(self):
        pass

    def test_expires_soon(self):
        pass

    def test_purchase_date_updated_on_paid(self):
        pass

    def test_start_date_updated_on_paid_for_signup_date_start_options(self):
        # Only updated if start date is past (since it could have been purchased for an advance date)
        pass

    def test_status(self):
        # Pending if not paid
        # Active when changed to paid
        pass

    def test_set_start_date_from_bookings(self):
        # Has no effect if config start_options is not first_booking_date
        # Otherwise set to date of first non-cancelled booked event
        # no shows could towards start dates
        pass

    def test_valid_for_event(self):
        pass

    def test_valid_for_course(self):
        pass


# class GiftVoucherTypeTests(TestCase):
#
#     def test_event_type_or_block_type_required(self):
#
#         block_type = baker.make_recipe("booking.blocktype5")
#         event_type = baker.make_recipe("booking.event_type_PC")
#
#         with pytest.raises(ValidationError):
#             gift_voucher = GiftVoucherType.objects.create()
#             gift_voucher.clean()
#
#         with pytest.raises(ValidationError):
#             gift_voucher = GiftVoucherType.objects.create(event_type=event_type, block_type=block_type)
#             gift_voucher.clean()
#
#     def test_gift_voucher_cost(self):
#         block_type = baker.make_recipe("booking.blocktype5", cost=40)
#         gift_voucher_type = GiftVoucherType.objects.create(block_type=block_type)
#         assert gift_voucher_type.cost == 40