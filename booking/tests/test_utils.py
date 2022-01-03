from datetime import timedelta

from model_bakery import baker

from django.test import TestCase
from django.utils import timezone

from booking.models import Booking, Block, BlockConfig, Course
from common.test_utils import EventTestMixin, TestUsersMixin
from booking.utils import has_available_course_block, get_active_user_course_block, \
    has_available_block, user_can_book_or_cancel


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
        self.in_progress_course_event = baker.make_recipe("booking.past_event", event_type=self.in_progress_course.event_type, course=self.in_progress_course)
        baker.make_recipe(
            "booking.future_event", event_type=self.in_progress_course.event_type, course=self.in_progress_course,
            _quantity=self.in_progress_course.number_of_events - 1
        )

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

        assert dropin_block.valid_for_course(self.course) is False
        assert dropin_block.valid_for_course(self.in_progress_course) is False

        assert full_course_block.valid_for_course(self.course) is True
        assert full_course_block.valid_for_course(self.in_progress_course) is True

        assert part_course_block.valid_for_course(self.course) is False
        assert part_course_block.valid_for_course(self.in_progress_course) is False
        self.in_progress_course.allow_partial_booking = True
        self.in_progress_course.save()
        assert part_course_block.valid_for_course(self.in_progress_course) is True
        assert full_course_block.valid_for_course(self.in_progress_course) is True

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

        assert get_active_user_course_block(self.student_user, self.course) == full_course_block_oldest
        # in progress course doesn't allow partial booking
        assert get_active_user_course_block(self.student_user, self.in_progress_course) == full_course_block_oldest

        self.in_progress_course.allow_partial_booking = True
        self.in_progress_course.save()
        assert get_active_user_course_block(self.student_user, self.in_progress_course) == part_course_block_oldest

        assert get_active_user_course_block(self.student_user1, self.course) is None
        assert get_active_user_course_block(self.student_user1, self.in_progress_course) is None

    def test_user_can_book_or_cancel(self):
        event = self.aerial_events[0]
        cancelled_event = self.aerial_events[1]
        cancelled_event.cancelled = True
        cancelled_event.save()

        # no user booking
        assert user_can_book_or_cancel(event=event, user_booking=None) is True

        # cancelled event
        assert user_can_book_or_cancel(event=cancelled_event, user_booking=None) is False

        # open booking
        user_booking = baker.make(Booking, event=event, status="OPEN", no_show=False)
        assert user_can_book_or_cancel(event=event, user_booking=user_booking) is True

        # no-show
        user_booking.no_show = True
        user_booking.save()
        # can book unless restricted
        assert user_can_book_or_cancel(event=event, user_booking=user_booking) is True
        assert user_can_book_or_cancel(
            event=event, user_booking=user_booking, booking_restricted=True
        ) is False

        # cancelled
        user_booking.no_show = False
        user_booking.status = "CANCELLED"
        user_booking.save()
        assert user_can_book_or_cancel(event=event, user_booking=user_booking) is True
        assert user_can_book_or_cancel(
            event=event, user_booking=user_booking, booking_restricted=True
        ) is False

        # cancelled course booking
        course_booking = baker.make(Booking, event=self.course_event, status="CANCELLED")
        assert user_can_book_or_cancel(event=self.course_event, user_booking=course_booking) is True
        assert user_can_book_or_cancel(
            event=self.course_event, user_booking=course_booking, booking_restricted=True
        ) is True
