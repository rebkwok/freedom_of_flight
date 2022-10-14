# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta
from datetime import timedelta, datetime
from datetime import timezone as dt_timezone

from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from model_bakery import baker
import pytest

from booking.models import (
    Course, Event, EventType, Block, Booking, BlockVoucher, Track,
    BlockConfig, SubscriptionConfig, Subscription, GiftVoucher, GiftVoucherConfig, TotalVoucher
)
from common.test_utils import EventTestMixin, TestUsersMixin
from payments.models import Invoice

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
        self.event.start = datetime(2015, 1, 1, tzinfo=dt_timezone.utc)
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
        self.event.start = datetime(2015, 1, 1, 18, 0, tzinfo=dt_timezone.utc)
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
        mock_now = datetime(2015, 1, 1, tzinfo=dt_timezone.utc)
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
        mock_now = datetime(2015, 3, 1, tzinfo=dt_timezone.utc)
        mock_tz.now.return_value = mock_now

        booking = baker.make(
            Booking, event=self.event, user=self.student_user, status='CANCELLED',
            date_rebooked=datetime(2015, 1, 1, tzinfo=dt_timezone.utc)
        )
        assert booking.date_rebooked == datetime(2015, 1, 1, tzinfo=dt_timezone.utc)
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

    def test_valid_for_user(self):
        user = baker.make(User, userprofile__date_of_birth=(timezone.now() - relativedelta(years=16)).date())
        # min and max ages are inclusive so an exactly 16 yr old is valid for both over and under 16
        evtype = baker.make(EventType, minimum_age_for_booking=16)
        assert evtype.valid_for_user(user) is True

        evtype.minimum_age_for_booking = None
        evtype.maximum_age_for_booking = 16
        evtype.save()
        assert evtype.valid_for_user(user) is True

        evtype.maximum_age_for_booking = 15
        evtype.save()
        assert evtype.valid_for_user(user) is False

        evtype.maximum_age_for_booking = None
        evtype.minimum_age_for_booking = 17
        evtype.save()
        assert evtype.valid_for_user(user) is False

        user.userprofile.date_of_birth = None
        user.userprofile.save()
        assert evtype.valid_for_user(user) is False

    def test_age_restrictions(self):
        evtype = baker.make(EventType, minimum_age_for_booking=16)
        assert evtype.age_restrictions == "age 16 and over only"

        evtype.minimum_age_for_booking = None
        evtype.maximum_age_for_booking = 16
        evtype.save()
        assert evtype.age_restrictions == "age 16 and under only"


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
        # fetch from db again - depends on cached properties
        course = Course.objects.get(id=self.course.id)
        assert course.has_started is True

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

    def test_configured_with_cancelled_events(self):
        # A course is configured if it has the right number of uncancelled events on it
        # Course allows 2 events, already has self.event
        baker.make_recipe(
            "booking.future_event", event_type=self.course.event_type, course=self.course,
            _quantity=1
        )
        assert self.course.is_configured() is True
        self.event.cancelled = True
        self.event.save()
        assert self.event.course == self.course
        assert self.course.is_configured() is False

    def test_can_be_visible(self):
        # Can only make a course visible if it's configured OR it has the right number of events when taking
        # cancelled ones into account - we don't want to hide courses if an event is cancelled during the course
        assert self.course.is_configured() is False
        assert self.course.can_be_visible() is False

        baker.make_recipe(
            "booking.future_event", event_type=self.course.event_type, course=self.course,
            _quantity=1
        )
        assert self.course.is_configured() is True
        assert self.course.can_be_visible() is True

        self.event.cancelled = True
        self.event.save()
        assert self.event.course == self.course
        assert self.course.is_configured() is False
        assert self.course.can_be_visible() is True

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

    def test_block_config_age_restrictions(self):
        # property to make course and drop in block configs behave the same
        dropin_config = baker.make(BlockConfig, event_type__minimum_age_for_booking=16, name="A Drop in Block", size=4)
        assert dropin_config.age_restrictions == "Valid for age 16 and over only"


class BlockVoucherTests(TestCase):

    @patch('booking.models.timezone')
    def test_voucher_start_dates(self, mock_tz):
        # dates are set to end of day
        mock_now = datetime(2016, 1, 5, 16, 30, 30, 30, tzinfo=dt_timezone.utc)
        mock_tz.now.return_value = mock_now
        voucher = baker.make(BlockVoucher, start_date=mock_now, discount=10)
        assert voucher.start_date == datetime(2016, 1, 5, 0, 0, 0, 0, tzinfo=dt_timezone.utc)

        voucher.expiry_date = datetime(2016, 1, 6, 18, 30, 30, 30, tzinfo=dt_timezone.utc)
        voucher.save()
        assert voucher.expiry_date == datetime(2016, 1, 6, 23, 59, 59, 999999, tzinfo=dt_timezone.utc)

    @patch('booking.models.timezone')
    def test_has_expired(self, mock_tz):
        mock_tz.now.return_value = datetime(2016, 1, 5, 12, 30, tzinfo=dt_timezone.utc)

        voucher = baker.make(
            BlockVoucher,
            start_date=datetime(2016, 1, 1, tzinfo=dt_timezone.utc),
            expiry_date=datetime(2016, 1, 4, tzinfo=dt_timezone.utc),
            discount=10
        )
        assert voucher.has_expired

        mock_tz.now.return_value = datetime(2016, 1, 3, 12, 30, tzinfo=dt_timezone.utc)
        assert voucher.has_expired is False

    @patch('booking.models.timezone')
    def test_has_started(self, mock_tz):
        mock_tz.now.return_value = datetime(2016, 1, 5, 12, 30, tzinfo=dt_timezone.utc)

        voucher = baker.make(BlockVoucher, start_date=datetime(2016, 1, 1, tzinfo=dt_timezone.utc), discount=10)
        assert voucher.has_started

        voucher.start_date = datetime(2016, 1, 6, tzinfo=dt_timezone.utc)
        voucher.save()
        assert voucher.has_started is False

    def test_check_block_config(self):
        dropin_block_configs = baker.make(BlockConfig, _quantity=2)
        course_block_configs = baker.make(BlockConfig, course=True, _quantity=2)
        voucher = baker.make(BlockVoucher, discount=10)
        voucher.block_configs.add(dropin_block_configs[0], course_block_configs[0])
        assert voucher.check_block_config(dropin_block_configs[0]) is True
        assert voucher.check_block_config(course_block_configs[0]) is True
        assert voucher.check_block_config(dropin_block_configs[1]) is False
        assert voucher.check_block_config(dropin_block_configs[1]) is False

    def test_discount_or_amount(self):
        with pytest.raises(ValidationError):
            baker.make(BlockVoucher, discount=None, discount_amount=None)

        with pytest.raises(ValidationError):
            baker.make(BlockVoucher, discount=10, discount_amount=20)

    def test_str(self):
        voucher = baker.make(BlockVoucher, code="testcode", discount=10)
        assert str(voucher) == 'testcode'

    def test_create_code(self):
        voucher = baker.make(BlockVoucher, code=None, discount=10)
        assert voucher.code is not None
        assert len(voucher.code) == 12

    @patch("booking.models.BaseVoucher._generate_code")
    def test_create_code_duplicates(self, mock_generate_code):
        mock_generate_code.side_effect = ["foo", "foo", "bar"]
        voucher = baker.make(BlockVoucher, code=None, discount=10)
        assert voucher.code == "foo"
        voucher1 = baker.make(BlockVoucher, code=None, discount=10)
        assert voucher1.code == "bar"

    def test_uses(self):
        dropin_block_config = baker.make(BlockConfig)
        course_block_config = baker.make(BlockConfig, course=True)
        voucher = baker.make(BlockVoucher, discount=10)
        voucher.block_configs.add(dropin_block_config, course_block_config)

        baker.make(Block, block_config=dropin_block_config, voucher=voucher, paid=True)
        baker.make(Block, block_config=course_block_config, voucher=voucher, paid=True)
        baker.make(Block, block_config=dropin_block_config, voucher=voucher, paid=False)
        assert voucher.uses() == 2

    def test_uses_voucher_with_item_count(self):
        dropin_block_config = baker.make(BlockConfig)
        course_block_config = baker.make(BlockConfig, course=True)
        voucher = baker.make(BlockVoucher, discount=10, item_count=2)
        voucher.block_configs.add(dropin_block_config, course_block_config)

        baker.make(Block, block_config=dropin_block_config, voucher=voucher, paid=True)
        baker.make(Block, block_config=course_block_config, voucher=voucher, paid=True)
        assert voucher.uses() == 1


class TotalVoucherTests(TestCase):

    def test_uses(self):
        voucher = baker.make(TotalVoucher, code="test", discount=10)
        assert voucher.uses() == 0

        invoices = baker.make(Invoice, total_voucher_code="test", paid=False, _quantity=2)
        assert voucher.uses() == 0

        invoice = invoices[0]
        invoice.paid = True
        invoice.save()
        assert voucher.uses() == 1


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
        self.dropin_block.start_date = datetime(2015, 3, 1, 15, 45, tzinfo=dt_timezone.utc)
        # set to 2 weeks after start date, end of day GMT/BST
        assert self.dropin_block.get_expiry_date() == datetime(2015, 3, 15, 23, 59, 59, 999999, tzinfo=dt_timezone.utc)

        # with daylight savings
        self.course_block.start_date = datetime(2015, 6, 1, 12, 42, tzinfo=dt_timezone.utc)
        assert self.course_block.get_expiry_date() == datetime(2015, 6, 15, 22, 59, 59, 999999, tzinfo=dt_timezone.utc)

        self.dropin_config.duration = None
        self.dropin_config.save()
        assert self.dropin_block.get_expiry_date() is None

    def test_expired(self):
        self.dropin_block.start_date = timezone.now() - timedelta(days=14)
        self.dropin_block.save()
        assert self.dropin_block.expired is False

        self.dropin_block.start_date = timezone.now() - timedelta(days=80)
        self.dropin_block.save()
        assert self.dropin_block.expired is True

    def test_block_manual_expiry_date_set_to_end_of_day(self):
        """
        Test that manual expiry dates are set to end of day on save
        """
        self.dropin_block.manual_expiry_date = datetime(2015, 3, 1, 15, 45, tzinfo=dt_timezone.utc)
        self.dropin_block.save()
        expected = datetime.combine(
            datetime(2015, 3, 1, tzinfo=dt_timezone.utc).date(), datetime.max.time()
        )
        expected = expected.replace(tzinfo=dt_timezone.utc)
        assert self.dropin_block.get_expiry_date() == expected

    @patch('booking.models.timezone.now')
    def test_block_purchase_date_reset_on_paid(self, mock_now):
        """
        Test that a block's purchase date is set to current date on payment
        """
        now = datetime(2015, 2, 1, tzinfo=dt_timezone.utc)
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

    @pytest.mark.freeze_time('2015-02-01')
    def test_str(self):
        self.dropin_block.paid = True
        self.dropin_block.save()

        assert str(self.dropin_block) == f'{self.dropin_block.user.username} -- {self.dropin_block.block_config} -- created 01 Feb 2015'

    def test_cost_with_voucher(self):
        assert self.dropin_block.cost_with_voucher == 10.00
        voucher = baker.make(BlockVoucher, code='123', discount=50)
        voucher.block_configs.add(self.dropin_block.block_config)
        self.dropin_block.voucher = voucher
        self.dropin_block.save()
        assert self.dropin_block.cost_with_voucher == 5.00

    def test_cost_with_voucher_amount(self):
        voucher = baker.make(BlockVoucher, code='123', discount_amount=3)
        voucher.block_configs.add(self.dropin_block.block_config)
        self.dropin_block.voucher = voucher
        self.dropin_block.save()
        assert self.dropin_block.cost_with_voucher == 7.00

        voucher.discount_amount = 2.75
        voucher.save()
        assert self.dropin_block.cost_with_voucher == 7.25

        voucher.discount_amount = 200
        voucher.save()
        assert self.dropin_block.cost_with_voucher == 0

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
        # deleting block removes it from bookings if the block is paid
        self.dropin_block.paid = True
        self.dropin_block.save()
        booking1 = baker.make(Booking, block=self.dropin_block)
        assert booking1.block == self.dropin_block
        self.dropin_block.delete()
        booking1.refresh_from_db()
        assert booking1.block is None

    def test_delete_unpaid_block(self):
        # deleting an unpaid block deletes its bookings
        assert self.dropin_block.paid == False
        booking1 = baker.make(Booking, block=self.dropin_block)
        booking1_id = booking1.id
        assert booking1.block == self.dropin_block
        self.dropin_block.delete()
        assert not Booking.objects.filter(id=booking1_id),exists()


class SubscriptionConfigTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()

    def test_subscription_config_str(self):
        subscription_config = baker.make(SubscriptionConfig, name="membership")
        assert str(subscription_config) == "membership (active)"

    def test_age_restrictions(self):
        event_type = baker.make(EventType, maximum_age_for_booking=12)
        subscription_config = baker.make(
            SubscriptionConfig, name="membership", bookable_event_types={str(event_type.id): {}})
        assert subscription_config.age_restrictions == "Valid for age 12 and under only"

    def test_start_date_set_to_start_of_day(self):
        start_date = datetime(2020, 1, 1, 13, 30, tzinfo=dt_timezone.utc)
        subscription_config = baker.make(SubscriptionConfig, start_date=start_date)
        assert subscription_config.start_date.day == 1
        assert subscription_config.start_date.hour == 0
        assert subscription_config.start_date.minute == 0

        # DST; always set to UTC still
        start_date = datetime(2020, 8, 1, 13, 30, tzinfo=dt_timezone.utc)
        subscription_config = baker.make(SubscriptionConfig, start_date=start_date)
        assert subscription_config.start_date.day == 1
        assert subscription_config.start_date.hour == 0
        assert subscription_config.start_date.minute == 0

        # update DST start date to another date
        start_date = datetime(2020, 8, 2, 14, 30, tzinfo=dt_timezone.utc)
        subscription_config.start_date = start_date
        subscription_config.save()
        assert subscription_config.start_date.day == 2
        assert subscription_config.start_date.hour == 0
        assert subscription_config.start_date.minute == 0

        # update DST start date with a 0, 0 start date
        start_date = datetime(2020, 8, 3, 0, 0, tzinfo=dt_timezone.utc)
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
            # no start date
            baker.make(
                SubscriptionConfig, partial_purchase_allowed=True, cost_per_week=5, start_date=None, start_options="start_date"
            )
        with pytest.raises(ValidationError):
            # wrong start option
            baker.make(
                SubscriptionConfig, partial_purchase_allowed=True, cost_per_week=5, start_date=timezone.now(), start_options="signup_date"
            )
        with pytest.raises(ValidationError):
            # no cost per week
            baker.make(
                SubscriptionConfig, partial_purchase_allowed=True, start_date=timezone.now(), start_options="start_date"
            )
        baker.make(
            SubscriptionConfig, partial_purchase_allowed=True, start_date=timezone.now(), start_options="start_date",
            cost_per_week=5,
        )

    def test_validation_not_recurring(self):
        # one off subscription requires a start date start options
        with pytest.raises(ValidationError):
            baker.make(SubscriptionConfig, recurring=False, start_date=timezone.now(), start_options="signup_date")
        with pytest.raises(ValidationError):
            baker.make(SubscriptionConfig, recurring=False, start_date=None, start_options="start_date")
        baker.make(
            SubscriptionConfig, recurring=False, start_date=timezone.now(), start_options="start_date",
        )

    def test_start_date_with_monthly_recurrence(self):
        # if day for recurrence is > 28 and recurrence is in months, set start date to 28th
        config = baker.make(
            SubscriptionConfig, start_date=datetime(2020, 1, 31, 12, 0, tzinfo=dt_timezone.utc), recurring=False
        )
        assert config.start_date.day == 31
        config = baker.make(
            SubscriptionConfig, start_date=datetime(2020, 1, 31, 12, 0, tzinfo=dt_timezone.utc), recurring=True,
            duration=4, duration_units="weeks"
        )
        assert config.start_date.day == 31
        config = baker.make(
            SubscriptionConfig, start_date=datetime(2020, 1, 31, 12, 0, tzinfo=dt_timezone.utc), recurring=True,
            duration=2, duration_units="months"
        )
        assert config.start_date.day == 28

    @patch("booking.models.timezone.now")
    def test_is_purchaseable(self, mock_now):
        mock_now.return_value = datetime(2020, 3, 10, 12, 0, tzinfo=dt_timezone.utc)

        # inactive
        config = baker.make(
            SubscriptionConfig, start_date=datetime(2020, 2, 4, 0, 0, tzinfo=dt_timezone.utc), recurring=True,
            active=False
        )
        assert config.is_purchaseable() is False

        # active and recurring
        config = baker.make(
            SubscriptionConfig, start_date=datetime(2020, 2, 4, 0, 0, tzinfo=dt_timezone.utc), recurring=True,
            active=True
        )
        assert config.is_purchaseable() is True

        # active one-off, not expired
        config = baker.make(
            SubscriptionConfig, start_date=datetime(2020, 3, 20, 0, 0, tzinfo=dt_timezone.utc), recurring=False,
            active=True, start_options="start_date", duration=1, duration_units="months"
        )
        assert config.is_purchaseable() is True

        # active one-off, expired
        # starts 3rd, duration 1 week, expires start of 10th. Today is the 10th, so now expired.
        config = baker.make(
            SubscriptionConfig, start_date=datetime(2020, 3, 3, 0, 0, tzinfo=dt_timezone.utc), recurring=False,
            active=True, start_options="start_date", duration=1, duration_units="weeks"
        )
        assert config.is_purchaseable() is False


@pytest.mark.django_db
class TestSubscriptionConfigStartDates:

    @pytest.mark.parametrize(
        "now_value,config_kwargs,expected_current_start_date,expected_current_next_start_date",
        [
            (
                datetime(2020, 7, 15, 12, 0, tzinfo=dt_timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 5, 3, 12, 0, tzinfo=dt_timezone.utc),  # Sun
                    "duration": 1,
                },
                datetime(2020, 7, 12, 0, 0, tzinfo=dt_timezone.utc), datetime(2020, 7, 19, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                # start Sun 3 May; repeats every 3 weeks
                # 3, 24 May, 14 Jun, 5 Jul, 26 Jul
                datetime(2020, 7, 15, 12, 0, tzinfo=dt_timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 5, 3, 12, 0, tzinfo=dt_timezone.utc),  # Sun
                    "duration": 3,
                },
                datetime(2020, 7, 5, 0, 0, tzinfo=dt_timezone.utc), datetime(2020, 7, 26, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                # start Sun 3 May; repeats every 4 weeks
                # 3, 31 May, 28 Jun, 26 Jul
                datetime(2020, 7, 15, 12, 0, tzinfo=dt_timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 5, 3, 12, 0, tzinfo=dt_timezone.utc),  # Sun
                    "duration": 4,
                },
                datetime(2020, 6, 28, 0, 0, tzinfo=dt_timezone.utc), datetime(2020, 7, 26, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                # start Sun 3 May; repeats every 2 weeks
                # 3, 17, 31 May, 14, 28 Jun, 12, 26 Jul
                datetime(2020, 7, 15, 12, 0, tzinfo=dt_timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 5, 3, 12, 0, tzinfo=dt_timezone.utc),  # Sun
                    "duration": 2,
                },
                datetime(2020, 7, 12, 0, 0, tzinfo=dt_timezone.utc), datetime(2020, 7, 26, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                # start Mon 1 Jun; repeats every 2 weeks
                # 1, 15, 29 Jun, 13, 27 Jul
                datetime(2020, 7, 15, 12, 0, tzinfo=dt_timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 6, 1, 12, 0, tzinfo=dt_timezone.utc),  # Mon
                    "duration": 2,
                },
                datetime(2020, 7, 13, 0, 0, tzinfo=dt_timezone.utc), datetime(2020, 7, 27, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                # start Mon 1 June; repeats every 4 weeks
                # 1, 29 Jun, 27 Jul
                datetime(2020, 7, 15, 12, 0, tzinfo=dt_timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 6, 1, 12, 0, tzinfo=dt_timezone.utc),  # Mon
                    "duration": 4,
                },
                datetime(2020, 6, 29, 0, 0, tzinfo=dt_timezone.utc), datetime(2020, 7, 27, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                # start Mon 1 June; repeats every 3 weeks
                # 1, 22 Jun, 13 Jul, 3 Aug
                datetime(2020, 7, 15, 12, 0, tzinfo=dt_timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 6, 1, 12, 0, tzinfo=dt_timezone.utc),  # Mon
                    "duration": 3,
                },
                datetime(2020, 7, 13, 0, 0, tzinfo=dt_timezone.utc), datetime(2020, 8, 3, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                # start Mon 1 June; repeats every 1 week
                datetime(2020, 7, 15, 12, 0, tzinfo=dt_timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 6, 1, 12, 0, tzinfo=dt_timezone.utc),  # Mon
                    "duration": 1,
                },
                datetime(2020, 7, 13, 0, 0, tzinfo=dt_timezone.utc), datetime(2020, 7, 20, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                # today is same weekday as start weekday
                datetime(2020, 6, 15, 12, 0, tzinfo=dt_timezone.utc),  # Mon
                {
                    "start_date": datetime(2020, 6, 1, 12, 0, tzinfo=dt_timezone.utc),  # Mon
                    "duration": 1,
                },
                datetime(2020, 6, 15, 0, 0, tzinfo=dt_timezone.utc), datetime(2020, 6, 22, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                # one-off, returns config start date
                datetime(2020, 7, 15, 12, 0, tzinfo=dt_timezone.utc),  # Wed
                {
                    "start_date": datetime(2020, 6, 1, 12, 0, tzinfo=dt_timezone.utc),  # Mon
                    "duration": 1,
                    "recurring": False,
                },
                datetime(2020, 6, 1, 0, 0, tzinfo=dt_timezone.utc), None,
            ),
            (
                # one-off, start date in future, returns config start date
                datetime(2020, 5, 15, 12, 0, tzinfo=dt_timezone.utc),
                {
                    "start_date": datetime(2020, 6, 1, 12, 0, tzinfo=dt_timezone.utc),
                    "duration": 1,
                    "recurring": False,
                },
                datetime(2020, 6, 1, 0, 0, tzinfo=dt_timezone.utc), None,
            ),
        ],
        ids = [
            "1. duration 1, start Sun, now Mon",
            "2. duration 3, start Sun, now Mon",
            "3. duration 4, start Sun, now Mon",
            "4. duration 2, start Sun, now Mon",
            "5. duration 2, start Mon, now Wed",
            "6. duration 4, start Mon, now Wed",
            "7. duration 3, start Mon, now Wed",
            "8. duration 1, start Mon, now Wed",
            "9. duration 1, start Mon, now Mon",
            "10. One-off, returns config start",
            "11. One-off, start date in future"
        ]
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
                datetime(2020, 7, 15, 12, 0, tzinfo=dt_timezone.utc),
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                    "duration": 1, "start_options": "signup_date",
                },
                None, None
            ),
            (
                datetime(2020, 7, 15, 12, 0, tzinfo=dt_timezone.utc),
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                    "duration": 1, "start_options": "first_booking_date",
                },
                None, None
            ),
            (
                datetime(2020, 7, 15, 12, 0, tzinfo=dt_timezone.utc),  # DST now
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                    "duration": 1, "start_options": "start_date",
                },
                datetime(2020, 7, 3, 0, 0, tzinfo=dt_timezone.utc), datetime(2020, 8, 3, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                datetime(2020, 2, 15, 12, 0, tzinfo=dt_timezone.utc),  # not DST now
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                    "duration": 1, "start_options": "start_date",
                },
                datetime(2020, 2, 3, 0, 0, tzinfo=dt_timezone.utc), datetime(2020, 3, 3, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                datetime(2019, 12, 15, 12, 0, tzinfo=dt_timezone.utc),  # start date in future
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                    "duration": 1, "start_options": "start_date",
                },
                None, datetime(2020, 1, 3, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                datetime(2020, 2, 3, 12, 0, tzinfo=dt_timezone.utc),  # now day same as start day
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                    "duration": 1, "start_options": "start_date",
                },
                datetime(2020, 2, 3, 0, 0, tzinfo=dt_timezone.utc), datetime(2020, 3, 3, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                datetime(2020, 2, 1, 12, 0, tzinfo=dt_timezone.utc),  # now day before start day
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                    "duration": 1, "start_options": "start_date",
                },
                datetime(2020, 1, 3, 0, 0, tzinfo=dt_timezone.utc), datetime(2020, 2, 3, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                datetime(2020, 2, 1, 12, 0, tzinfo=dt_timezone.utc),  # now before start, 2 month repeat
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                    "duration": 2, "start_options": "start_date",
                },
                datetime(2020, 1, 3, 0, 0, tzinfo=dt_timezone.utc), datetime(2020, 3, 3, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                # 2 month repeat Jan/Mar/May/Jul, now=June
                datetime(2020, 6, 15, 12, 0, tzinfo=dt_timezone.utc),
                {
                    "start_date": datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                    "duration": 2, "start_options": "start_date",
                },
                datetime(2020, 5, 3, 0, 0, tzinfo=dt_timezone.utc), datetime(2020, 7, 3, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                # repeats every 2 months from Jun - Jun/Aug/Oct/Dec, now=Nov
                datetime(2020, 11, 15, 12, 0, tzinfo=dt_timezone.utc),
                {
                    "start_date": datetime(2020, 6, 10, 12, 0, tzinfo=dt_timezone.utc),
                    "duration": 2, "start_options": "start_date",
                },
                datetime(2020, 10, 10, 0, 0, tzinfo=dt_timezone.utc), datetime(2020, 12, 10, 0, 0, tzinfo=dt_timezone.utc)
            ),
            (
                # repeats every 2 months from Sep - Sep/Nov/Jan, now=Nov
                datetime(2020, 11, 15, 12, 0, tzinfo=dt_timezone.utc),
                {
                    "start_date": datetime(2020, 9, 10, 12, 0, tzinfo=dt_timezone.utc),
                    "duration": 2, "start_options": "start_date",
                },
                datetime(2020, 11, 10, 0, 0, tzinfo=dt_timezone.utc), datetime(2021, 1, 10, 0, 0, tzinfo=dt_timezone.utc)
            ),
        ],
        ids=[
            "1. signup date start option",
            "2. first booking date start option",
            "3. duration 1, DST",
            "4. duration 1, non DST",
            "5. duration 1, start in future",
            "6. duration 1, now day same as start day",
            "7. duration 1, now day before start day",
            "8. duration 2, now day before start day",
            "9. duration 2, repeats Jan/Mar/May/Jul, now=June",
            "10. duration 2, Jun/Aug/Oct/Dec, now=Nov",
            "11. duration 2, Sep/Nov/Jan, now=Nov, goes into next year"
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
class TestStartDatesOfferedToUser:

    @pytest.mark.parametrize(
        "now_value,start,duration,duration_units,start_option,advance_purchase_allowed,recurring,expected_start_dates",
        [
            (
                datetime(2020, 7, 15, tzinfo=dt_timezone.utc), datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                1, "months", "signup_date", True, True,
                [datetime(2020, 7, 15, tzinfo=dt_timezone.utc)]  # starts on purchase date (today)
            ),
            (
                datetime(2020, 7, 15, tzinfo=dt_timezone.utc), datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                1, "months", "signup_date", False, True,
                [datetime(2020, 7, 15, tzinfo=dt_timezone.utc)]  # starts on purchase date (today)
            ),
            (
                datetime(2020, 7, 15, tzinfo=dt_timezone.utc), datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                1, "months", "first_booking_date", True, True,
                [None]  # not start date, starts when first used
            ),
            (
                datetime(2020, 7, 15, tzinfo=dt_timezone.utc), datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                1, "months", "first_booking_date", False, True,
                [None]  # not start date, starts when first used
            ),
            (
                datetime(2020, 7, 15, tzinfo=dt_timezone.utc), datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                1, "months", "start_date", True, True,
                [datetime(2020, 7, 3, tzinfo=dt_timezone.utc), datetime(2020, 8, 3, tzinfo=dt_timezone.utc)]
            ),
            (
                datetime(2020, 7, 15, tzinfo=dt_timezone.utc), datetime(2020, 6, 19, 12, 0, tzinfo=dt_timezone.utc),
                1, "months", "start_date", False, True,
                [datetime(2020, 6, 19, tzinfo=dt_timezone.utc)]
            ),
            (
                datetime(2020, 7, 15, tzinfo=dt_timezone.utc), datetime(2020, 6, 18, 12, 0, tzinfo=dt_timezone.utc),
                1, "months", "start_date", False, True,
                [datetime(2020, 6, 18, tzinfo=dt_timezone.utc), datetime(2020, 7, 18, tzinfo=dt_timezone.utc)]
            ),
            (
                datetime(2020, 7, 15, tzinfo=dt_timezone.utc), datetime(2020, 7, 20, 12, 0, tzinfo=dt_timezone.utc),
                1, "months", "start_date", True, True,
                [datetime(2020, 7, 20, tzinfo=dt_timezone.utc)]
            ),
            (
                datetime(2020, 7, 15, tzinfo=dt_timezone.utc), datetime(2020, 8, 15, 12, 0, tzinfo=dt_timezone.utc),
                1, "months", "start_date", True, True,
                [datetime(2020, 8, 15, tzinfo=dt_timezone.utc)]
            ),
            (
                datetime(2020, 7, 20, tzinfo=dt_timezone.utc), datetime(2020, 7, 1, 0, 0, tzinfo=dt_timezone.utc),
                2, "weeks", "start_date", True, True,
                [datetime(2020, 7, 15, tzinfo=dt_timezone.utc), datetime(2020, 7, 29, tzinfo=dt_timezone.utc)]
            ),
            (
                datetime(2020, 7, 20, tzinfo=dt_timezone.utc), datetime(2020, 7, 1, 0, 0, tzinfo=dt_timezone.utc),
                2, "weeks", "start_date", True, False,
                [datetime(2020, 7, 1, tzinfo=dt_timezone.utc)]
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
            "11. one-off suscription",
        ]
    )
    def test_start_options_for_user_no_existing_subscription(
        self, student_user, mocker,
        now_value, start, duration, duration_units, start_option, advance_purchase_allowed, recurring,
        expected_start_dates
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
            recurring=recurring,
        )
        start_options_for_user = config.get_start_options_for_user(student_user)
        assert start_options_for_user == expected_start_dates

    def test_start_options_for_signup_config_with_existing_subscription(self, student_user, mocker):
        mock_now = mocker.patch("booking.models.timezone.now")
        mock_now.return_value = datetime(2020, 7, 15, tzinfo=dt_timezone.utc)
        signup_config = baker.make(
            SubscriptionConfig,
            start_date=datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
            duration=1,
            duration_units="months",
            start_options="signup_date",
            advance_purchase_allowed=True,
        )
        baker.make(
            Subscription, user=student_user, config=signup_config,
            start_date=datetime(2020, 7, 1, tzinfo=dt_timezone.utc)
        )
        # starts on purchase date, user already has unexpired subscription, show option for one month from last start
        start_options = signup_config.get_start_options_for_user(student_user)
        assert start_options == [datetime(2020, 8, 1, tzinfo=dt_timezone.utc)]

    def test_start_options_for_first_booking_config_with_existing_subscription(self, student_user, mocker):
        mock_now = mocker.patch("booking.models.timezone.now")
        mock_now.return_value = datetime(2020, 7, 15, tzinfo=dt_timezone.utc)

        first_booking_date_config = baker.make(
            SubscriptionConfig,
            start_date=datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
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
            Booking, event__start=datetime(2020, 8, 1, 12, 30, tzinfo=dt_timezone.utc),
            subscription=first_booking_date_subscription, user=student_user
        )
        # booking has set subscription start and expiry
        first_booking_date_subscription.refresh_from_db()
        assert first_booking_date_subscription.start_date == datetime(2020, 8, 1, 0, 0, tzinfo=dt_timezone.utc)
        assert first_booking_date_subscription.expiry_date == datetime(2020, 9, 1, 0, 0, tzinfo=dt_timezone.utc)
        start_options = first_booking_date_config.get_start_options_for_user(student_user)
        assert start_options == [None]

    @pytest.mark.parametrize(
        "now_value,start,duration,duration_units,start_option,advance_purchase_allowed,recurring,subscription_starts,expected_start_dates",
        [
            (
                datetime(2020, 7, 15, tzinfo=dt_timezone.utc), datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                1, "months", "start_date", True, True,
                [datetime(2020, 7, 3, tzinfo=dt_timezone.utc)],
                [datetime(2020, 8, 3, tzinfo=dt_timezone.utc)]
            ),
            (
                datetime(2020, 7, 15, tzinfo=dt_timezone.utc), datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                1, "months", "start_date", True, True,
                [datetime(2020, 7, 3, tzinfo=dt_timezone.utc), datetime(2020, 8, 3, tzinfo=dt_timezone.utc)],
                []
            ),
            (
                datetime(2020, 7, 15, tzinfo=dt_timezone.utc), datetime(2020, 1, 3, 12, 0, tzinfo=dt_timezone.utc),
                1, "months", "start_date", True, True,
                [datetime(2020, 6, 3, tzinfo=dt_timezone.utc)],
                [datetime(2020, 7, 3, tzinfo=dt_timezone.utc), datetime(2020, 8, 3, tzinfo=dt_timezone.utc)]
            ),
            (
                datetime(2020, 7, 15, tzinfo=dt_timezone.utc), datetime(2020, 8, 1, 12, 0, tzinfo=dt_timezone.utc),
                1, "months", "start_date", True, False,
                [datetime(2020, 8, 1, tzinfo=dt_timezone.utc)],
                []
            ),
        ],
        ids=[
            "1. start_date config: unexpired exists for current, advance allowed, show next only",
            "2. start_date config: unexpired exists for current and next, advance allowed, no options",
            "3. start_date config: expired exists, advance allowed, show both",
            "4. start_date config: exists, one-off, advance allowed, no options",
        ]
    )
    def test_start_options_for_user_with_existing_subscription_start_date_config(
        self, student_user, mocker, now_value, start, duration, duration_units, start_option, advance_purchase_allowed,
        recurring, subscription_starts, expected_start_dates

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
            recurring=recurring,
        )
        for subscription_start in subscription_starts:
            baker.make(Subscription, user=student_user, config=config, start_date=subscription_start)
        start_options_for_user = config.get_start_options_for_user(student_user)
        assert start_options_for_user == expected_start_dates


@pytest.mark.django_db
@pytest.mark.parametrize(
    "now_value,expected_cost",
    [
        (datetime(2020, 9, 1, 10, 0, tzinfo=dt_timezone.utc), 20),
        (datetime(2020, 9, 5, 10, 0, tzinfo=dt_timezone.utc), 20),
        (datetime(2020, 9, 7, 10, 0, tzinfo=dt_timezone.utc), 15),
        (datetime(2020, 9, 20, 10, 0, tzinfo=dt_timezone.utc), 10),
        (datetime(2020, 9, 26, 10, 0, tzinfo=dt_timezone.utc), 5),
        (datetime(2020, 9, 28, 10, 0, tzinfo=dt_timezone.utc), 5),
    ],
    ids=[
        "1. 4 weeks left",
        "2. 3 + weeks left, still full cost",
        "3. 3 weeks + 1 day left, 3 week cost",
        "4. 1+ weeks left, rounds up to 2 week cost",
        "5. <1 weeks left, rounds up to 1 week cost",
        "6. 1 day left, still charges 1 week cost",
    ]
)
def test_subscription_config_calculate_current_period_cost_as_of_today(mocker, now_value, expected_cost):
    mock_tz = mocker.patch("booking.models.timezone.now")
    mock_tz.return_value = now_value
    subscription_config_kwargs = {
        "duration": 4,
        "duration_units": "weeks",
        "partial_purchase_allowed": True,
        "cost": 20,
        "cost_per_week": 5,
        "start_date": datetime(2020, 9, 1, 0, 0, tzinfo=dt_timezone.utc),
    }
    config = baker.make(
        SubscriptionConfig, **subscription_config_kwargs,
    )
    assert config.calculate_current_period_cost_as_of_today() == expected_cost

    # if partial purchase not allowed, always return full cost
    config.partial_purchase_allowed = False
    config.save()
    assert config.calculate_current_period_cost_as_of_today() == 20

    # if config hasn't started yet, always return full cost
    config.partial_purchase_allowed = True
    # reset the cost per week - setting partial_purchase_allowed to False will have changed it to None again
    config.cost_per_week = 5
    config.start_date = datetime(2020, 10, 1, 0, 0, tzinfo=dt_timezone.utc)
    config.save()
    assert config.calculate_current_period_cost_as_of_today() == 20


@pytest.mark.django_db
class TestSubscription:

    @pytest.mark.parametrize(
        "subscription_kwargs,expected",
        [
            (
                {"start_date": None, "paid": False},
                "student@test.com -- Membership -- not started yet (unpaid)"
            ),
            (
                {"start_date": None, "paid": True},
                "student@test.com -- Membership -- not started yet (paid)"
            ),
            (
                {
                    "start_date": datetime(2020, 2, 3, tzinfo=dt_timezone.utc),
                    "config__duration": 1,
                    "config__duration_units": "months",
                    "paid": False
                },
                "student@test.com -- Membership -- starts 03 Feb 2020 -- expires 03 Mar 2020 (unpaid)"
            ),
            (
                    {
                        "start_date": datetime(2020, 2, 3, tzinfo=dt_timezone.utc),
                        "config__duration": 2,
                        "config__duration_units": "weeks",
                        "paid": True
                    },
                    "student@test.com -- Membership -- starts 03 Feb 2020 -- expires 17 Feb 2020 (paid)"
            ),
        ]
    )
    def test_str(self, student_user, subscription_kwargs, expected):
        subscription = baker.make(
            Subscription,
            user=student_user,
            config__name="Membership",
            **subscription_kwargs
        )
        assert str(subscription) == expected

    @pytest.mark.parametrize(
        "subscription_kwargs,expected",
        [
            ({"start_date": None}, None),
            (
                {
                    "start_date": datetime(2020, 3, 4, tzinfo=dt_timezone.utc), "config__duration": 1,
                    "config__duration_units": "months"
                },
                datetime(2020, 4, 4, tzinfo=dt_timezone.utc)
            ),
            (
                {
                    "start_date": datetime(2020, 8, 1, tzinfo=dt_timezone.utc), "config__duration": 3,
                    "config__duration_units": "weeks"
                },
                datetime(2020, 8, 22, tzinfo=dt_timezone.utc)
            ),

        ]
    )
    def test_expiry_date(self, student_user, subscription_kwargs, expected):
        subscription = baker.make(
            Subscription,
            user=student_user,
            **subscription_kwargs
        )
        assert subscription.get_expiry_date() == expected

    def test_expires_soon(self, student_user, mocker):
        mock_now = mocker.patch("booking.models.timezone.now")
        mock_now.return_value = datetime(2020, 7, 27, 12, 0, tzinfo=dt_timezone.utc)
        subscription = baker.make(
            Subscription,
            user=student_user,
            start_date=datetime(2020, 7, 1, tzinfo=dt_timezone.utc),
            config__duration=1,
            config__duration_units="months",
        )
        assert subscription.expires_soon() is False

        mock_now.return_value = datetime(2020, 7, 28, 12, 0, tzinfo=dt_timezone.utc)
        assert subscription.expires_soon() is True

    def test_purchase_date_updated_on_paid(self, student_user):
        subscription = baker.make(
            Subscription,
            user=student_user,
            start_date=datetime(2020, 7, 1, tzinfo=dt_timezone.utc),
        )
        initial_purchase_date = subscription.purchase_date
        subscription.paid = True
        subscription.save()
        assert subscription.purchase_date > initial_purchase_date

    def test_start_date_updated_on_paid_for_signup_date_start_options(self, student_user, mocker):
        # Only updated if start date is past (since it could have been purchased for an advance date)
        mock_now = mocker.patch("booking.models.timezone.now")
        mock_now.return_value = datetime(2020, 7, 27, 12, 0, tzinfo=dt_timezone.utc)
        # start date in future, not updated on paid
        subscription = baker.make(
            Subscription,
            user=student_user,
            start_date=datetime(2020, 8, 1, tzinfo=dt_timezone.utc),
            config__start_options="signup_date",
        )
        initial_start_date = subscription.start_date
        subscription.paid = True
        subscription.save()
        assert subscription.start_date == initial_start_date

        # start date in past, updated on paid
        subscription = baker.make(
            Subscription,
            user=student_user,
            start_date=datetime(2020, 7, 1, tzinfo=dt_timezone.utc),
            config__start_options="signup_date",
        )
        subscription.paid = True
        subscription.save()
        assert subscription.start_date == datetime(2020, 7, 27, 0, 0, tzinfo=dt_timezone.utc)

    def test_status(self, student_user):
        # Pending if not paid
        # Active when changed to paid
        subscription = baker.make(
            Subscription,
            user=student_user
        )
        assert subscription.status == "pending"
        subscription.paid = True
        subscription.save()
        assert subscription.status == "active"

    def test_set_start_date_from_bookings(self, student_user):
        # Has no effect if config start_options is not first_booking_date
        # Otherwise set to date of first non-cancelled booked event
        # no shows could towards start dates
        subscription = baker.make(
            Subscription,
            user=student_user,
            config__start_options="first_booking_date"
        )
        assert subscription.start_date is None

        booking = baker.make(
            Booking, event__start=datetime(2020, 3, 5, 13, 45, tzinfo=dt_timezone.utc), subscription=subscription
        )
        subscription.refresh_from_db()
        assert subscription.start_date == datetime(2020, 3, 5, 0, 0, tzinfo=dt_timezone.utc)

        booking.no_show = True
        booking.save()
        subscription.refresh_from_db()
        assert subscription.start_date == datetime(2020, 3, 5, 0, 0, tzinfo=dt_timezone.utc)

        booking.status = "CANCELLED"
        booking.save()
        subscription.refresh_from_db()
        assert subscription.start_date is None

    @pytest.mark.parametrize(
        "bookable_event_types,other_bookable_event_types,kwargs,is_course,expected",
        [
            (None, {}, {}, False, False),
            (None, {"99": {"allowed_number": None}}, {}, False, False),
            ({}, {}, {}, True, False),
            ({"allowed_number": ""}, {}, {}, False, True),
            ({"allowed_number": None}, {}, {}, True, False),
            ({"allowed_number": None}, {}, {"paid": False}, False, False),
            (
                {"allowed_number": None}, {}, {"start_date": datetime(2020, 10, 10, 0, 0, tzinfo=dt_timezone.utc)},
                False, False
            ),
            (
                {"allowed_number": None}, {}, {"start_date": datetime(2020, 8, 9, 0, 0, tzinfo=dt_timezone.utc)},
                False, False
            ),
            (
                {"allowed_number": "", "allowed_unit": "day"}, {}, {"start_date": datetime(2020, 8, 20, 0, 0, tzinfo=dt_timezone.utc)},
                False, True
            ),
        ],
        ids=[
            "1. no bookable events",
            "2. bookable events for other event types",
            "3. no bookable events, is course",
            "4. valid, no restrictions",
            "5. valid, no restrictions, is_course",
            "6. valid, no restrictions, unpaid",
            "7. valid, no restrictions, start date after event start",
            "8. valid, no restrictions, expiry date before event start",
            "9. valid, no restrictions (unit ignored), event within allowed dates",
        ]
    )
    def test_valid_for_event(
            self, student_user, event_type, bookable_event_types, other_bookable_event_types, kwargs, is_course,
            expected
    ):
        event = baker.make(Event, event_type=event_type, start=datetime(2020, 9, 10, 14, 0, tzinfo=dt_timezone.utc))
        if is_course:
            course = baker.make(Course, event_type=event_type)
            event.course = course
            event.save()
        if bookable_event_types:
            bookable_event_types = {**other_bookable_event_types, event_type.id: bookable_event_types}
        elif other_bookable_event_types:
            bookable_event_types = other_bookable_event_types
        subscription_kwargs = {
            "config__bookable_event_types": bookable_event_types,
            "config__duration": 1,
            "config__duration_units": "months",
            "paid": True,
            **kwargs  # override defaults with test params
        }
        subscription = baker.make(
            Subscription,
            user=student_user,
            **subscription_kwargs,
        )
        assert subscription.valid_for_event(event) == expected

    @pytest.mark.parametrize(
        "bookable_event_types,kwargs,existing_booking_dates,expected",
        [
            ({"allowed_number": 1, "allowed_unit": "day"}, {}, [], True),
            ({"allowed_number": 1, "allowed_unit": "day"}, {}, [datetime(2020, 10, 3, 14, 0, tzinfo=dt_timezone.utc)], True),
            ({"allowed_number": 1, "allowed_unit": "day"}, {}, [datetime(2020, 9, 3, 10, 0, tzinfo=dt_timezone.utc)], False),
            ({"allowed_number": 2, "allowed_unit": "day"}, {}, [datetime(2020, 9, 3, 10, 0, tzinfo=dt_timezone.utc)], True),
            (
                {"allowed_number": 2, "allowed_unit": "week"}, {},
                [datetime(2020, 9, 2, 14, 0, tzinfo=dt_timezone.utc), datetime(2020, 9, 5, 14, 0, tzinfo=dt_timezone.utc)],
                False
            ),
            (
                {"allowed_number": 2, "allowed_unit": "week"}, {}, [datetime(2020, 9, 2, 14, 0, tzinfo=dt_timezone.utc)],
                True
            ),
            (
                {"allowed_number": 1, "allowed_unit": "week"}, {}, [datetime(2020, 9, 1, 14, 0, tzinfo=dt_timezone.utc)],
                False
            ),
            (
                {"allowed_number": 1, "allowed_unit": "week"}, {}, [datetime(2020, 9, 8, 14, 0, tzinfo=dt_timezone.utc)],
                True
            ),
            (
                {"allowed_number": 1, "allowed_unit": "month"}, {}, [datetime(2020, 9, 1, 14, 0, tzinfo=dt_timezone.utc)],
                False
            ),
            (
                {"allowed_number": 1, "allowed_unit": "month"}, {}, [datetime(2020, 10, 1, 14, 0, tzinfo=dt_timezone.utc)],
                True
            ),
            (
                {"allowed_number": 1, "allowed_unit": "month"},
                {
                    "config__start_date": datetime(2020, 8, 2, 0, 0, tzinfo=dt_timezone.utc),
                    "start_date": datetime(2020, 9, 2, 0, 0, tzinfo=dt_timezone.utc)
                },
                [datetime(2020, 9, 2, 14, 0, tzinfo=dt_timezone.utc)],
                False
            ),
        ],
        ids=[
            "1. no bookings for same event type",
            "2. 1 per day allowed, booking on different day",
            "3. 1 per day allowed, booking on same day",
            "4. 2 per day allowed, 1 booking on same day",
            "5. 2 per week allowed, 2 bookings in same week",
            "6. 2 per week allowed, 1 booking in same week",
            "7. 1 per week allowed, 1 booking first day of same week",
            "8. 1 per week allowed, 1 booking first day of next week",
            "9. 1 per month allowed, 1 booking first day of same month",
            "10. 1 per month allowed, 1 booking first day of next month",
            "11. 1 per month allowed, 1 booking already, start day before event day",
        ]
    )
    def test_valid_for_event_booking_restrictions(
        self, student_user, event_type, bookable_event_types, kwargs, existing_booking_dates, expected
    ):
        # event on Thurs
        event = baker.make(Event, event_type=event_type, start=datetime(2020, 9, 3, 14, 0, tzinfo=dt_timezone.utc))
        # Subscription starts on Tuesday, so week of the current event is beginning of previous Tues to next Tues
        # i.e. beg 1 Sep - beg 8 Sep
        subscription_kwargs = {
            # jsonfield keys are always strings
            "config__bookable_event_types": {str(event_type.id): bookable_event_types},
            "config__duration": 1,
            "config__duration_units": "months",
            "config__start_date": datetime(2020, 8, 1, 0, 0, tzinfo=dt_timezone.utc),
            "start_date": datetime(2020, 9, 1, 0, 0, tzinfo=dt_timezone.utc),  # Tuesday
            **kwargs  # override defaults with test params
        }
        subscription = baker.make(
            Subscription,
            user=student_user,
            paid=True,
            **subscription_kwargs,
        )
        # booking for different event type on same day has no effect
        baker.make(
            Booking, user=student_user, subscription=subscription, status="OPEN", no_show=False,
            event__start=datetime(2020, 9, 3, 16, 0, tzinfo=dt_timezone.utc)
        )
        # booking for same event type on same day not on subscription has no effect
        baker.make(
            Booking, user=student_user, event__event_type=event_type, status="OPEN", no_show=False,
            event__start=datetime(2020, 9, 3, 17, 0, tzinfo=dt_timezone.utc)
        )
        # booking for same event type/day/subscription no-show has no effect
        baker.make(
            Booking, user=student_user, event__event_type=event_type, status="OPEN", no_show=True,
            event__start=datetime(2020, 9, 3, 18, 0, tzinfo=dt_timezone.utc), subscription=subscription
        )
        # booking for same event type/day/subscription cancelled has no effect
        baker.make(
            Booking, user=student_user, event__event_type=event_type, status="CANCELLED", no_show=False,
            event__start=datetime(2020, 9, 3, 19, 0, tzinfo=dt_timezone.utc), subscription=subscription
        )

        for event_date in existing_booking_dates:
            baker.make(
                Booking, user=student_user, event__event_type=event_type, status="OPEN", no_show=False,
                event__start=event_date, subscription=subscription
            )

        assert subscription.valid_for_event(event) == expected

    def test_valid_for_event_booking_restrictions_existing_booking(self, student_user, event_type):
        # existing booking for event we're checking don't count
        event = baker.make(Event, event_type=event_type, start=datetime(2020, 9, 3, 14, 0, tzinfo=dt_timezone.utc))
        subscription_kwargs = {
            "config__bookable_event_types": {str(event_type.id): {"allowed_number": 1, "allowed_unit": "day"}},
            "config__duration": 1,
            "config__duration_units": "months",
            "config__start_date": datetime(2020, 8, 1, 0, 0, tzinfo=dt_timezone.utc),
            "start_date": datetime(2020, 9, 1, 0, 0, tzinfo=dt_timezone.utc),
        }
        subscription = baker.make(
            Subscription, user=student_user, paid=True, **subscription_kwargs,
        )
        # open booking for same event
        baker.make(
            Booking, user=student_user, subscription=subscription, status="OPEN", no_show=False,
            event=event
        )
        assert subscription.valid_for_event(event) is True

    def test_valid_for_event_booking_restrictions_include_no_shows(self, student_user, event_type):
        event = baker.make(Event, event_type=event_type, start=datetime(2020, 9, 3, 14, 0, tzinfo=dt_timezone.utc))
        subscription_kwargs = {
            "config__bookable_event_types": {str(event_type.id): {"allowed_number": 1, "allowed_unit": "day"}},
            "config__duration": 1,
            "config__duration_units": "months",
            "config__start_date": datetime(2020, 8, 1, 0, 0, tzinfo=dt_timezone.utc),
            "config__include_no_shows_in_usage": False,
            "start_date": datetime(2020, 9, 1, 0, 0, tzinfo=dt_timezone.utc),
        }
        subscription = baker.make(
            Subscription, user=student_user, paid=True, **subscription_kwargs,
        )
        # open booking for same event type, same day
        booking = baker.make(
            Booking, user=student_user, subscription=subscription, status="OPEN", no_show=False,
            event__event_type=event_type, event__start=datetime(2020, 9, 3, 12, 0, tzinfo=dt_timezone.utc)
        )
        assert subscription.valid_for_event(event) is False

        # no-show booking not included in usage by default
        booking.no_show = True
        booking.save()
        assert subscription.valid_for_event(event) is True

        subscription.config.include_no_shows_in_usage = True
        subscription.config.save()
        assert subscription.valid_for_event(event) is False


class GiftVoucherConfigTests(TestCase):

    def test_discount_amount_or_block_config_required(self):

        block_config = baker.make(BlockConfig)

        with pytest.raises(ValidationError):
            config = GiftVoucherConfig.objects.create()
            config.clean()

        with pytest.raises(ValidationError):
            config = GiftVoucherConfig.objects.create(block_config=block_config, discount_amount=10)
            config.clean()

        GiftVoucherConfig.objects.create(block_config=block_config)

    def test_gift_voucher_cost(self):
        block_config = baker.make(BlockConfig, cost=40)
        config = GiftVoucherConfig.objects.create(block_config=block_config)
        assert config.cost == 40

        config1 = GiftVoucherConfig.objects.create(discount_amount=10)
        assert config1.cost == 10


class GiftVoucherTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.block_config = baker.make(BlockConfig, active=True, cost=10, name="4 class block")
        block_config1 = baker.make(BlockConfig, active=True, cost=10, name="2 class block")
        cls.config_total = baker.make(GiftVoucherConfig, discount_amount=10, active=True)
        cls.config_block = baker.make(GiftVoucherConfig, block_config=cls.block_config, active=True, duration=6)
        cls.config_block1 = baker.make(GiftVoucherConfig, block_config=block_config1, active=True, duration=6)

    def test_new_creates_voucher(self):
        gift_voucher = baker.make(GiftVoucher, gift_voucher_config=self.config_block)
        assert isinstance(gift_voucher.voucher, BlockVoucher)
        assert gift_voucher.voucher.block_configs.count() == 1
        assert gift_voucher.voucher.block_configs.first() == self.block_config

        gift_voucher = baker.make(GiftVoucher, gift_voucher_config=self.config_total)
        assert isinstance(gift_voucher.voucher, TotalVoucher)
        assert gift_voucher.voucher.discount_amount == 10

    def test_change_block_config(self):
        gift_voucher = baker.make(GiftVoucher, gift_voucher_config=self.config_block)
        assert gift_voucher.name == "Gift Voucher: 4 class block"
        voucher_id = gift_voucher.voucher.id
        gift_voucher.gift_voucher_config = self.config_block1
        gift_voucher.save()
        assert gift_voucher.name == "Gift Voucher: 2 class block"
        assert gift_voucher.voucher.id == voucher_id
        assert BlockVoucher.objects.count() == 1

    def test_change_voucher_type(self):
        gift_voucher = baker.make(GiftVoucher, gift_voucher_config=self.config_block)
        assert isinstance(gift_voucher.voucher, BlockVoucher)

        gift_voucher.gift_voucher_config = self.config_total
        gift_voucher.save()
        assert BlockVoucher.objects.exists() is False
        assert isinstance(gift_voucher.voucher, TotalVoucher)

        gift_voucher.gift_voucher_config = self.config_block
        gift_voucher.save()
        assert TotalVoucher.objects.exists() is False
        assert isinstance(gift_voucher.voucher, BlockVoucher)
        assert gift_voucher.voucher.block_configs.first() == self.block_config

    def test_gift_voucher_activate(self):
        gift_voucher = baker.make(GiftVoucher, gift_voucher_config=self.config_block)
        start_date = timezone.now() - timedelta(weeks=6)
        gift_voucher.voucher.start_date = start_date
        gift_voucher.voucher.save()
        assert gift_voucher.voucher.expiry_date is None
        assert gift_voucher.paid is False
        assert gift_voucher.voucher.activated is False
        gift_voucher.activate()

        gift_voucher.refresh_from_db()
        assert gift_voucher.voucher.activated is True
        assert gift_voucher.voucher.expiry_date is not None
        assert gift_voucher.voucher.start_date > start_date

    def test_name(self):
        gift_voucher = baker.make(GiftVoucher, gift_voucher_config=self.config_block)
        assert gift_voucher.name == "Gift Voucher: 4 class block"

        gift_voucher1 = baker.make(GiftVoucher, gift_voucher_config=self.config_total)
        assert gift_voucher1.name == "Gift Voucher: £10"

    def test_str(self):
        gift_voucher = baker.make(GiftVoucher, gift_voucher_config=self.config_block)
        gift_voucher.voucher.purchaser_email = "foo@bar.com"
        gift_voucher.save()
        assert str(gift_voucher) == f"{gift_voucher.voucher.code} - Gift Voucher: 4 class block - foo@bar.com"

        gift_voucher1 = baker.make(GiftVoucher, gift_voucher_config=self.config_total)
        gift_voucher1.voucher.purchaser_email = "foo@bar.com"
        gift_voucher1.save()
        assert str(gift_voucher1) == f"{gift_voucher1.voucher.code} - Gift Voucher: £10 - foo@bar.com"


@pytest.mark.django_db
@pytest.mark.freeze_time('2017-05-21 10:00')
def test_cleanup_expired_blocks(client, freezer):
    block = baker.make(Block)
    assert Block.objects.count() == 1
    # block was just made, not cleaned up
    Block.cleanup_expired_blocks()
    assert Block.objects.count() == 1

    freezer.move_to('2017-05-21 10:30')
    # no bookings on it, still not cleaned up
    Block.cleanup_expired_blocks()
    assert Block.objects.count() == 1

    # now it has bookings, but checkout within last 5 mins
    baker.make(Booking, block=block)
    block.time_checked = timezone.now() - timedelta(minutes=4)
    block.save()
    Block.cleanup_expired_blocks()
    assert Block.objects.count() == 1
    
    # move time on 5 more mins
    freezer.move_to('2017-05-21 10:35')
    Block.cleanup_expired_blocks()
    assert Block.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.freeze_time('2017-05-21 10:00')
def test_cleanup_expired_blocks_unpaid_only(client, freezer):
    # another user's block, with booking
    unpaid = baker.make(Block)
    baker.make(Booking, block=unpaid)

    paid = baker.make(Block, paid=True)
    baker.make(Booking, block=paid)

    assert Block.objects.count() == 2
    
    freezer.move_to('2017-05-21 10:30')
    Block.cleanup_expired_blocks()
    assert Block.objects.count() == 1
    assert Block.objects.first() == paid


@pytest.mark.django_db
@pytest.mark.freeze_time('2017-05-21 10:00')
def test_cleanup_expired_blocks_for_user(client, freezer, student_user):
    # another user's block, with booking
    other_user_block = baker.make(Block)
    baker.make(Booking, block=other_user_block)

    # student user's block, with booking
    block = baker.make(Block, user=student_user)
    baker.make(Booking, block=block, user=student_user)
    assert Block.objects.count() == 2

    # cleanup just for this user
    freezer.move_to('2017-05-21 10:30')
    Block.cleanup_expired_blocks(student_user)
    assert Block.objects.count() == 1
    assert Block.objects.first() == other_user_block
