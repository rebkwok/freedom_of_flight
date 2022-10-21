from datetime import timedelta
from unittest.mock import patch

from model_bakery import baker

from django.test import TestCase
from django.utils import timezone

from booking.models import Booking, Block, BlockConfig, Course, \
    has_available_course_block, get_active_user_course_block, \
    has_available_block, get_active_user_block
from common.test_utils import EventTestMixin, TestUsersMixin
from booking.utils import user_can_book_or_cancel


class UtilsTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_tracks_and_event_types()
        self.create_events_and_course()

        # configure the course
        baker.make_recipe(
            "booking.future_event", event_type=self.course.event_type, course=self.course,
            _quantity=self.course.number_of_events - self.course.uncancelled_events.count()
        )

        self.in_progress_course = baker.make(
            Course, event_type=self.course.event_type, number_of_events=self.course.number_of_events
        )
        # in-progress course has 1 past event, rest future
        in_progress_course_events = baker.make_recipe(
            "booking.future_event", event_type=self.in_progress_course.event_type,
            course=self.in_progress_course,
            _quantity=self.in_progress_course.number_of_events - 1
        )
        baker.make_recipe(
            "booking.past_event", event_type=self.in_progress_course.event_type,
            course=self.in_progress_course,
        )
        self.in_progress_course_event = in_progress_course_events[0]

        self.drop_in_allowed_course = baker.make(
            Course, event_type=self.course.event_type,
            number_of_events=self.course.number_of_events,
            allow_drop_in=True,
        )
        drop_in_allowed_course_events = baker.make_recipe(
            "booking.past_event", event_type=self.drop_in_allowed_course.event_type,
            course=self.drop_in_allowed_course,
            _quantity=self.in_progress_course.number_of_events
        )
        self.drop_in_allowed_course_event = drop_in_allowed_course_events[0]

        self.dropin_config = baker.make(
            BlockConfig, duration=2, cost=10, event_type=self.course.event_type, course=False,
            size=self.course.number_of_events
        )
        self.course_config = baker.make(
            BlockConfig, duration=2, cost=10, event_type=self.course.event_type, course=True, size=self.course.number_of_events
        )
        self.part_course_config = baker.make(
            BlockConfig, duration=2, cost=10, event_type=self.in_progress_course.event_type, course=True,
            size=self.in_progress_course.number_of_events - 1
        )

    def test_block_valid_for_course(self):
        dropin_block = baker.make(Block, block_config=self.dropin_config, user=self.student_user, paid=True)
        full_course_block = baker.make(Block, block_config=self.course_config, user=self.student_user, paid=True)
        part_course_block = baker.make(Block, block_config=self.part_course_config, user=self.student_user, paid=True)

        assert has_available_block(self.student_user, self.course_event)
        assert has_available_course_block(self.student_user, self.course)
        assert has_available_block(self.student_user, self.in_progress_course_event)
        assert has_available_course_block(self.student_user, self.in_progress_course)
        assert has_available_block(self.student_user, self.drop_in_allowed_course_event)
        assert has_available_course_block(self.student_user, self.drop_in_allowed_course)

        assert dropin_block.valid_for_course(self.course) is False
        assert dropin_block.valid_for_course(self.in_progress_course) is False
        assert dropin_block.valid_for_course(self.drop_in_allowed_course) is False
        assert dropin_block.valid_for_event(self.drop_in_allowed_course_event) is True

        assert full_course_block.valid_for_course(self.course) is True
        assert full_course_block.valid_for_course(self.in_progress_course) is True

        assert part_course_block.valid_for_course(self.course) is False
        assert part_course_block.valid_for_course(self.in_progress_course) is False

    def test_used_block_not_valid_for_course(self):
        full_course_block = baker.make(Block, block_config=self.course_config, user=self.student_user, paid=True)
        assert full_course_block.valid_for_course(self.course) is True

        booking = baker.make(Booking, user=self.student_user)
        assert full_course_block.valid_for_course(self.course) is True

        booking.block = full_course_block
        booking.save()
        assert full_course_block.valid_for_course(self.course) is False

    def test_get_available_user_course_block(self):
        # full course block was purchased first, will be the next available UNLESS partial booking allowed and there's
        # a part course block available
        full_course_block_newest = baker.make(
            Block, block_config=self.course_config, user=self.student_user, paid=True,
            purchase_date=timezone.now() - timedelta(3)
        )
        full_course_block_oldest = baker.make(
            Block, block_config=self.course_config, user=self.student_user, paid=True,
            purchase_date=timezone.now() - timedelta(4)
        )
        part_course_block_oldest = baker.make(
            Block, block_config=self.part_course_config, user=self.student_user, paid=True,
            purchase_date=timezone.now() - timedelta(2)
        )
        part_course_block_newest = baker.make(
            Block, block_config=self.part_course_config, user=self.student_user, paid=True,
            purchase_date=timezone.now() - timedelta(1)
        )
        drop_in_block = baker.make(
            Block, block_config=self.dropin_config, user=self.student_user, paid=True
        )

        assert get_active_user_course_block(self.student_user, self.course) == full_course_block_oldest
        
        assert get_active_user_course_block(self.student_user1, self.course) is None
        assert get_active_user_course_block(self.student_user1, self.in_progress_course) is None

        # drop in allowed course can be booked with both course block and dropin block
        assert has_available_course_block(self.student_user, self.drop_in_allowed_course)
        assert has_available_block(self.student_user, self.drop_in_allowed_course_event, dropin_only=False)
        assert get_active_user_course_block(self.student_user, self.drop_in_allowed_course) == full_course_block_oldest
        # event returns course block first, oldest first
        assert get_active_user_block(self.student_user, self.drop_in_allowed_course_event, dropin_only=False) == full_course_block_oldest
        full_course_block_oldest.delete()
        assert get_active_user_block(self.student_user, self.drop_in_allowed_course_event, dropin_only=False) == full_course_block_newest
        full_course_block_newest.delete()
        # if there are no course blocks valid, the drop in block is returned
        assert get_active_user_block(self.student_user, self.drop_in_allowed_course_event, dropin_only=False) == drop_in_block

    def test_get_available_user_block(self):
        full_course_block = baker.make(
            Block, block_config=self.course_config, user=self.student_user, paid=True,
            purchase_date=timezone.now() - timedelta(3)
        )
        part_course_block = baker.make(
            Block, block_config=self.part_course_config, user=self.student_user, paid=True,
            purchase_date=timezone.now() - timedelta(2)
        )
        drop_in_block = baker.make(
            Block, block_config=self.dropin_config, user=self.student_user, paid=True
        )

        # by default only shows drop in
        assert get_active_user_block(self.student_user, self.course_event) == None
        assert get_active_user_block(self.student_user, self.course_event, dropin_only=False) == full_course_block
        assert get_active_user_course_block(self.student_user, self.course_event.course) == full_course_block

        assert get_active_user_block(self.student_user1, self.course_event, dropin_only=False) is None
        assert get_active_user_block(self.student_user1, self.in_progress_course_event, dropin_only=False) is None
        assert get_active_user_block(self.student_user1, self.drop_in_allowed_course_event, dropin_only=False) is None

        # drop-in and course block available, return course block first
        assert get_active_user_block(self.student_user, self.drop_in_allowed_course_event, dropin_only=False) == full_course_block

        # remove the course blocks
        full_course_block.delete()
        part_course_block.delete()
        assert get_active_user_block(self.student_user, self.drop_in_allowed_course_event) == drop_in_block

    def test_user_can_book_or_cancel(self):
        event = self.aerial_events[0]
        cancelled_event = self.aerial_events[1]
        cancelled_event.cancelled = True
        cancelled_event.save()

        full_event = baker.make_recipe("booking.future_event", event_type=event.event_type, max_participants=3)
        baker.make(Booking, event=full_event, _quantity=full_event.max_participants)
        assert full_event.full

        # no user booking
        assert user_can_book_or_cancel(event=event, user_booking=None) is True
        assert user_can_book_or_cancel(event=full_event, user_booking=None) is False

        # cancelled event
        assert user_can_book_or_cancel(event=cancelled_event, user_booking=None) is False

        # open booking
        user_booking = baker.make(Booking, event=event, status="OPEN", no_show=False)
        assert user_can_book_or_cancel(event=event, user_booking=user_booking) is True

        # open booking for full event
        ev_booking = full_event.bookings.first()
        ev_booking.status = "CANCELLED"
        ev_booking.save()
        full_user_booking = baker.make(Booking, event=full_event, status="OPEN", no_show=False)
        assert full_event.full
        assert user_can_book_or_cancel(event=full_event, user_booking=full_user_booking) is True

        # no-show booking for full event
        full_user_booking.no_show = True
        full_user_booking.save()
        ev_booking.status = "OPEN"
        ev_booking.save()
        assert full_event.full
        assert user_can_book_or_cancel(event=full_event, user_booking=full_user_booking) is False

        # cancelled booking for full event
        full_user_booking.delete()
        full_user_booking = baker.make(Booking, event=full_event, status="CANCELLED")
        assert full_event.full
        assert user_can_book_or_cancel(event=full_event, user_booking=full_user_booking) is False

        # no-show
        user_booking.no_show = True
        user_booking.save()
        # can book unless restricted
        assert user_can_book_or_cancel(event=event, user_booking=user_booking) is True
        with patch("booking.models.timezone.now", return_value=event.start - timedelta(minutes=10)):
            assert user_can_book_or_cancel(event=event, user_booking=user_booking) is False

        # cancelled
        user_booking.no_show = False
        user_booking.status = "CANCELLED"
        user_booking.save()
        assert user_can_book_or_cancel(event=event, user_booking=user_booking) is True
        with patch("booking.models.timezone.now", return_value=event.start - timedelta(minutes=10)):
            assert user_can_book_or_cancel(event=event, user_booking=user_booking) is False

        # cancelled course booking
        course_booking = baker.make(Booking, event=self.course_event, status="CANCELLED")
        assert user_can_book_or_cancel(event=self.course_event, user_booking=course_booking) is True

        with patch("booking.models.timezone.now", return_value=self.course_event.start - timedelta(minutes=10)):
            assert user_can_book_or_cancel(event=self.course_event, user_booking=course_booking) is False

        # no-show course booking
        course_booking.no_show = True
        course_booking.status = "OPEN"
        course_booking.save()
        assert user_can_book_or_cancel(event=self.course_event, user_booking=course_booking) is True
        with patch("booking.models.timezone.now", return_value=self.course_event.start - timedelta(minutes=10)):
            assert user_can_book_or_cancel(event=self.course_event, user_booking=course_booking) is False

        # full course event
        baker.make(Booking, event=self.course_event, _quantity=self.course_event.max_participants - 1)
        assert self.course_event.full

        # no-show course booking can cancel
        assert user_can_book_or_cancel(event=self.course_event, user_booking=course_booking) is True

        # cancelled course booking cannot cancel
        course_booking.delete()
        course_booking = baker.make(Booking, event=self.course_event, status="CANCELLED")
        assert user_can_book_or_cancel(event=self.course_event, user_booking=course_booking) is True
