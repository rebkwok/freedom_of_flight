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
    Course, Event, EventType, Block, Booking, BlockVoucher, Track, CourseType,
    DropInBlockConfig, CourseBlockConfig
)
from common.test_utils import make_disclaimer_content, make_online_disclaimer, EventTestMixin, TestUsersMixin

now = timezone.now()


class EventTests(EventTestMixin, TestCase):

    def setUp(self):
        self.event = self.aerial_events[0]
        # Make sure these things are reset for each test
        self.event.max_participants = 2
        self.event.cancellation_period = 24
        self.event.name = 'Test event'
        self.event.start = timezone.now() + timedelta(days=3)
        self.event.course = None
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
        new_course = baker.make(Course, course_type__number_of_events=1, course_type__event_type=self.event.event_type)
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

    def setUp(self):
        super().setUp()
        self.create_users()
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


class CourseTypeTests(TestCase):

    def test_str_class(self):
        course_type = baker.make(CourseType, event_type__name="Aerial", number_of_events=3)
        assert str(course_type) == 'Aerial - 3'


class CourseTests(EventTestMixin, TestCase):

    def setUp(self):
        self.course.course_type.number_of_events = 2
        self.course.max_participants = 2
        self.course.save()
        self.event = self.aerial_events[0]
        self.event.course = self.course
        self.event.save()

    def test_str(self):
        assert str(self.course) == f"{self.course.name} (aerial - 2)"

    def test_full(self):
        assert self.course.full is False
        bookings = baker.make(Booking, event=self.event, _quantity=2)

        assert self.course.full is True
        booking = bookings[0]
        booking.status = "CANCELLED"
        booking.save()
        # still full
        assert self.course.full is True

    def test_has_started(self):
        # course has 2 events, which are in future

        # Allow another one to be added
        self.course.course_type.number_of_events = 3
        self.course.course_type.save()
        assert self.course.has_started is False
        baker.make_recipe(
            "booking.past_event", event_type=self.course.course_type.event_type, course=self.course
        )
        assert self.course.has_started is True

    def test_configured(self):
        # A course is configured if it has the right number of events on it
        assert self.course.is_configured() is True
        self.event.course = None
        self.event.save()
        assert self.course.is_configured() is False

    def test_changing_max_participants_updates_linked_events(self):
        # TODO
        pass

    def test_cancelling_course_cancels_linked_events(self):
        # TODO
        pass


class BlockConfigTests(TestCase):

    def test_dropin_block_config_str(self):
        dropin_config = baker.make(DropInBlockConfig, identifier="A Drop in Block")
        assert str(dropin_config) == "A Drop in Block"

    def test_course_block_config_str(self):
        course_config = baker.make(CourseBlockConfig, identifier="A Course Block")
        assert str(course_config) == "A Course Block"

    def test_block_config_size(self):
        # property to make course and drop in block configs behave the same
        course_type = baker.make(CourseType, number_of_events=5)
        course_config = baker.make(CourseBlockConfig, course_type=course_type, identifier="A Course Block")
        dropin_config = baker.make(DropInBlockConfig, identifier="A Drop in Block", size=4)
        assert course_config.size == 5
        assert dropin_config.size == 4

    def test_course_block_event_type(self):
        # property to make course and drop in block configs behave the same
        event_type1 = baker.make(EventType)
        event_type2 = baker.make(EventType)
        course_type = baker.make(CourseType,event_type=event_type1)
        course_config = baker.make(CourseBlockConfig, course_type=course_type, identifier="A Course Block")
        dropin_config = baker.make(DropInBlockConfig, identifier="A Drop in Block", event_type=event_type2)
        assert course_config.event_type == event_type1
        assert dropin_config.event_type == event_type2


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

    def test_all_block_configs(self):
        dropin_block_configs = baker.make(DropInBlockConfig, _quantity=2)
        course_block_configs = baker.make(DropInBlockConfig, _quantity=2)
        not_on_voucher_config = baker.make(DropInBlockConfig)
        voucher = baker.make(BlockVoucher)
        voucher.dropin_block_configs.add(*dropin_block_configs)
        voucher.dropin_block_configs.add(*course_block_configs)
        assert len(voucher.all_block_configs()) == 4
        assert not_on_voucher_config not in voucher.all_block_configs()

    def test_check_block_config(self):
        dropin_block_configs = baker.make(DropInBlockConfig, _quantity=2)
        course_block_configs = baker.make(DropInBlockConfig, _quantity=2)
        voucher = baker.make(BlockVoucher)
        voucher.dropin_block_configs.add(dropin_block_configs[0], course_block_configs[0])
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
        dropin_config = baker.make(DropInBlockConfig, size=2, duration=2, cost=10, event_type=self.event_type)
        self.dropin_block = baker.make(
            Block, dropin_block_config=dropin_config,
            course_block_config=None,
            user=self.student_user
        )

        self.course_type = baker.make(CourseType, number_of_events=2, event_type=self.event_type)
        course_config = baker.make(CourseBlockConfig, duration=2, cost=10, course_type=self.course_type)
        self.course_block = baker.make(
            Block, course_block_config=course_config, dropin_block_config=None, user=self.student_user
        )

    def test_block_expiry_date(self):
        """
        Test that block expiry dates are populated correctly
        """
        # Times are in UTC, but converted from local (GMT/BST)
        # No daylight savings
        self.dropin_block.start_date = datetime(2015, 3, 1, 15, 45, tzinfo=timezone.utc)
        # set to 2 weeks after start date, end of day GMT/BST
        self.dropin_block.get_expiry_date() == datetime(2015, 3, 15, 23, 59, 59, tzinfo=timezone.utc)

        # with daylight savings
        self.course_block.start_date = datetime(2015, 6, 1, 12, 42, tzinfo=timezone.utc)
        self.course_block.get_expiry_date() == datetime(2015, 6, 15, 22, 59, 59, tzinfo=timezone.utc)

    def test_block_manual_expiry_date_set_to_end_of_day(self):
        """
        Test that manual expiry dates are set to end of day on save
        """
        self.dropin_block.manual_expiry_date = datetime(2015, 3, 1, 15, 45, tzinfo=timezone.utc)
        self.dropin_block.save()
        assert self.dropin_block.get_expiry_date() == datetime(2015, 3, 1, 23, 59, 59, tzinfo=timezone.utc)

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

    def test_block_config(self):
        # blocks can be associated with dropin or course configs; helper property returns
        # whichever is relevant
        assert isinstance(self.dropin_block.block_config, DropInBlockConfig)
        assert isinstance(self.course_block.block_config, CourseBlockConfig)

    def test_one_and_only_one_config(self):
        dropin_config = baker.make(DropInBlockConfig)
        course_config = baker.make(CourseBlockConfig)
        with pytest.raises(ValidationError) as error:
            baker.make(Block, dropin_block_config=dropin_config, course_block_config=course_config)
        assert error.value.messages == ['Only one of dropin_block_config or course_block_config can be set.']

        with pytest.raises(ValidationError) as error:
            baker.make(Block, dropin_block_config=None, course_block_config=None)
        assert error.value.messages == ['One of dropin_block_config or course_block_config is required.']

    def test_cost_with_voucher(self):
        voucher = baker.make(BlockVoucher, code='123', discount=50)
        voucher.dropin_block_configs.add(self.dropin_block.block_config)
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
        course = baker.make(Course, course_type=self.course_type)
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
        valid_course = baker.make(Course, course_type=self.course_type)
        baker.make(Event, course=valid_course, event_type=self.event_type)

        # valid course - no events
        valid_course1 = baker.make(Course, course_type=self.course_type)

        # invalid course - wrong type
        invalid_course2 = baker.make(Course)
        baker.make(Event, course=invalid_course2, event_type=invalid_course2.course_type.event_type)

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