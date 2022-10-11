from datetime import timedelta
from re import A
from model_bakery import baker
import pytest

from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from booking.utils import full_name
from booking.models import BlockConfig, Course, Block, Event, Booking
from common.test_utils import TestUsersMixin, EventTestMixin


class CourseListViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_test_setup()
        self.make_disclaimer(self.student_user)
        self.make_data_privacy_agreement(self.student_user)
        self.make_data_privacy_agreement(self.manager_user)
        # ensure course has more than one event
        baker.make_recipe(
            "booking.future_event", event_type=self.course.event_type,
            course=self.course,
        )

    def url(self, track):
        return reverse('booking:courses', args=(track.slug,))

    def test_schedule_no_courses(self):
        resp = self.client.get(reverse('booking:events', args=(self.adult_track.slug,)))
        assert "View courses" in resp.rendered_content
        resp = self.client.get(reverse('booking:events', args=(self.kids_track.slug,)))
        assert "View courses" not in resp.rendered_content

    def test_lists_uncancelled_visible_courses_that_are_not_fully_complete(self):
        shown = baker.make(Course, event_type=self.aerial_event_type, show_on_site=True)
        not_shown = baker.make(Course, event_type=self.aerial_event_type, show_on_site=False)
        # cancelled course not shown
        baker.make(Course, event_type=self.aerial_event_type, show_on_site=True, cancelled=True)
        # course with all events in past, not_shown
        past_course = baker.make(Course, event_type=self.aerial_event_type, show_on_site=True, number_of_events=2)
        baker.make_recipe("booking.past_event", event_type=self.aerial_event_type, course=past_course, _quantity=2)
        # course with one event in future shown
        part_done_course = baker.make(Course, event_type=self.aerial_event_type, show_on_site=True)
        baker.make_recipe("booking.past_event", event_type=self.aerial_event_type, course=part_done_course)
        baker.make_recipe("booking.future_event", event_type=self.aerial_event_type, course=part_done_course)

        resp = self.client.get(self.url(self.adult_track))
        assert sorted(course.id for course in resp.context_data["courses"]) == sorted([self.course.id, shown.id, part_done_course.id])

    def test_courses_list_with_booked_courses(self):
        """
        test that booked courses are shown on listing
        """
        # make events for course
        baker.make_recipe(
            "booking.future_event", course=self.course, event_type=self.aerial_event_type,
            _quantity=self.course.number_of_events - self.course.uncancelled_events.count()
        )

        # create a booking for this user
        for event in self.course.events.all():
            baker.make(Booking, user=self.student_user, event=event)
        self.login(self.student_user)
        resp = self.client.get(self.url(self.adult_track))
        user_course_booking_info = resp.context_data['user_course_booking_info']
        booked = [course_id for course_id, user_info in user_course_booking_info.items() if user_info.get("open")]
        assert len(booked) == 1
        assert booked == [self.course.id]
        # bookings have no block associated, so these are considered dropin
        assert user_course_booking_info[self.course.id]["has_booked_dropin"]
        assert user_course_booking_info[self.course.id]["has_booked_course"] is False
        assert user_course_booking_info[self.course.id]["has_booked_all"] is True
        assert '<i class="text-success fas fa-check-circle"></i> Booked' in resp.rendered_content

        # assign course block
        block = baker.make_recipe("booking.course_block", paid=True, user=self.student_user)
        self.student_user.bookings.update(block=block)
        resp = self.client.get(self.url(self.adult_track))
        course_booking_info = resp.context_data['user_course_booking_info'][self.course.id]
        assert course_booking_info["has_booked_dropin"] is False
        assert course_booking_info["has_booked_course"] is True
        assert course_booking_info["has_booked_all"] is True
        assert '<i class="text-success fas fa-check-circle"></i> Booked' in resp.rendered_content

    def test_courses_list_with_full_course(self):
        self.login(self.student_user)
        for event in self.course.events.all():
            baker.make(Booking, event=event, _quantity=self.course.max_participants)
        self.login(self.student_user)
        resp = self.client.get(self.url(self.adult_track))
        assert 'Course is full' in resp.rendered_content
        assert "Drop-in is available for some classes" not in resp.rendered_content

    def test_courses_list_with_full_events_on_course(self):
        self.login(self.student_user)
        assert self.course.events.count() > 1
        assert self.course.full is False

        # only the first event on the course is full, which makes the course full, but
        # still bookable if it allows drop-in
        baker.make(Booking, event=self.course.events.first(), _quantity=self.course.max_participants)
        assert self.course.events.count() > 1
        assert self.course.full

        resp = self.client.get(self.url(self.adult_track))
        # course doesn't allow drop-in
        assert 'Course is full' in resp.rendered_content
        assert "Drop-in is available for some classes" not in resp.rendered_content

        # course allows drop-in
        self.course.allow_drop_in = True
        self.course.save()
        resp = self.client.get(self.url(self.adult_track))
        assert "Course is full" in resp.rendered_content
        assert "Drop-in is available for some classes" in resp.rendered_content

    def test_courses_list_with_course_with_cancelled_events(self):
        self.login(self.student_user)
        # make all events cancelled
        self.course.events.update(cancelled=True)
        assert self.course.uncancelled_events.exists() is False
        resp = self.client.get(self.url(self.adult_track))
        assert [course.id for course in resp.context_data["courses"]] == [self.course.id]

    def test_courses_list_with_started_course(self):
        baker.make_recipe("booking.past_event", event_type=self.aerial_event_type, course=self.course)
        self.login(self.student_user)
        resp = self.client.get(self.url(self.adult_track))
        assert 'Course has started' in resp.rendered_content

    def test_courses_list_with_no_block_available(self):
        self.login(self.student_user)
        resp = self.client.get(self.url(self.adult_track))
        # Add to cart isn't shown if no block config available
        assert "Add to cart (course)" not in resp.rendered_content
        # make a block config (doesn't have to be active)
        baker.make(
            BlockConfig, course=True, event_type=self.course.event_type, 
            size=self.course.number_of_events, active=False
        )
        resp = self.client.get(self.url(self.adult_track))
        assert "Add to cart (course)" in resp.rendered_content

    def test_courses_list_with_block_available(self):
        # make usable block
        self.login(self.student_user)
        block = baker.make(
            Block, user=self.student_user, block_config__event_type=self.aerial_event_type,
            block_config__course=True, block_config__size=self.course.number_of_events,
            paid=True
        )
        assert block.valid_for_course(self.course)

        resp = self.client.get(self.url(self.adult_track))
        assert 'NOT BOOKED' in resp.rendered_content
        assert 'Book Course' in resp.rendered_content

    def test_courses_list_change_view_as_user(self):
        # manager is also a student
        self.make_disclaimer(self.manager_user)
        self.manager_user.userprofile.student = True
        self.manager_user.userprofile.save()
        self.make_disclaimer(self.child_user)
        self.login(self.manager_user)
        for event in self.course.events.all():
            # create a booking for the manager user for all events
            baker.make(Booking, user=self.manager_user, event=event)

        # manager is a student, so by default shows them as view_as_user
        resp = self.client.get(self.url(self.adult_track))
        user_course_booking_info = resp.context_data['user_course_booking_info']
        booked_count = sum([1 if user_info.get("open") else 0 for user_info in user_course_booking_info.values()])
        assert booked_count == 1

        # post to change the user
        resp = self.client.post(self.url(self.adult_track), data={"view_as_user": self.child_user.id}, follow=True)
        assert self.client.session["user_id"] == self.child_user.id
        user_course_booking_info = resp.context_data['user_course_booking_info']
        booked_count = sum([1 if user_info.get("open") else 0 for user_info in user_course_booking_info.values()])
        assert booked_count == 0

    def test_courses_ordered_by_start_date(self):
        Event.objects.all().delete()
        self.course.number_of_events = 3
        self.course.save()

        course1 = baker.make(Course, event_type=self.aerial_event_type, show_on_site=True, number_of_events=3)
        course2 = baker.make(Course, event_type=self.aerial_event_type, show_on_site=True, number_of_events=3)

        # self.course has a past event, will be listed first
        baker.make_recipe("booking.past_event", event_type=self.aerial_event_type, course=self.course)
        baker.make_recipe("booking.future_event", event_type=self.aerial_event_type, course=self.course, _quantity=2)

        # course2 will be next
        baker.make(Event, event_type=self.aerial_event_type, course=course2, start=timezone.now() + timedelta(1))
        baker.make(Event, event_type=self.aerial_event_type, course=course2, start=timezone.now() + timedelta(5))
        baker.make(Event, event_type=self.aerial_event_type, course=course2, start=timezone.now() + timedelta(10))

        # then course1
        baker.make(Event, event_type=self.aerial_event_type, course=course1, start=timezone.now() + timedelta(3))
        baker.make(Event, event_type=self.aerial_event_type, course=course1, start=timezone.now() + timedelta(4))
        baker.make(Event, event_type=self.aerial_event_type, course=course1, start=timezone.now() + timedelta(5))

        resp = self.client.get(self.url(self.adult_track))
        assert [course.id for course in resp.context_data["courses"]] == [self.course.id, course2.id, course1.id]


class CourseUnenrollViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_test_setup()

        self.course.number_of_events = 3
        self.course.save()
        events = baker.make_recipe(
            "booking.future_event", event_type=self.course.event_type,
            course=self.course, _quantity=3-self.course.events.count()
        )
        self.course_block = baker.make_recipe(
            "booking.course_block", block_config__event_type=self.course.event_type,
            block_config__size=3, paid=True, user=self.student_user
        )
        for event in self.course.events.all():
            baker.make(
                Booking, user=self.student_user, event=event, block=self.course_block,
                status="OPEN"
            )

        self.url = reverse('booking:unenroll_course')

    def test_unenroll(self):
        booked_events = self.student_user.bookings.filter(status="OPEN").values_list("event_id", flat=True)
        for event in self.course.events.all():
            assert event.id in booked_events
        assert not self.course_block.active_block

        self.client.login(username=self.student_user.username, password="test")
        self.client.post(
            self.url, {"user_id": self.student_user.id, "course_id": self.course.id}
        )

        cancelled_booked_events = self.student_user.bookings.filter(status="CANCELLED").values_list("event_id", flat=True)
        for event in self.course.events.all():
            assert event.id in cancelled_booked_events
        
        self.course_block.refresh_from_db()
        assert self.course_block.active_block
    
    def test_unenroll_child_user(self):
        course_block = baker.make_recipe(
            "booking.course_block", block_config__event_type=self.course.event_type,
            block_config__size=3, paid=True, user=self.child_user
        )
        for event in self.course.events.all():
            baker.make(
                Booking, user=self.child_user, event=event, block=course_block,
                status="OPEN"
            )

        assert not course_block.active_block

        self.client.login(username=self.manager_user.username, password="test")
        self.client.post(
            self.url, {"user_id": self.child_user.id, "course_id": self.course.id}
        )

        cancelled_booked_events = self.child_user.bookings.filter(status="CANCELLED").values_list("event_id", flat=True)
        for event in self.course.events.all():
            assert event.id in cancelled_booked_events
        
        course_block.refresh_from_db()
        assert course_block.active_block
    
    def test_unenroll_not_enrolled(self):
        booked_events = self.student_user1.bookings.filter(status="OPEN").values_list("event_id", flat=True)
        for event in self.course.events.all():
            assert event.id not in booked_events

        self.client.login(username=self.student_user1.username, password="test")
        resp = self.client.post(
            self.url, {"user_id": self.student_user1.id, "course_id": self.course.id},
            follow=True
        )
        assert f"{full_name(self.student_user1)} is not booked on this course, cannot unenroll" in resp.rendered_content, resp.rendered_content
        
