# -*- coding: utf-8 -*-
from datetime import timedelta, datetime
from datetime import timezone as dt_timezone

from django import forms
from django.urls import reverse
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from model_bakery import baker

import pytest

from booking.models import EventType, Booking, Course, Event
from common.test_utils import TestUsersMixin, EventTestMixin


class CourseAdminListViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_test_setup()
        self.create_users()
        self.create_admin_users()
        self.url = reverse('studioadmin:courses')

    def test_cannot_access_if_not_logged_in(self):
        """
        test that the page redirects if user is not logged in
        """
        resp = self.client.get(self.url)
        redirected_url = reverse('account_login') + "?next={}".format(self.url)
        assert resp.status_code == 302
        assert redirected_url in resp.url

    def test_staff_only(self):
        """
        test that the page redirects if user is not a staff user
        """
        self.user_access_test(["staff"], self.url)

    def test_courses_by_track(self):
        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert "track_courses" in resp.context_data
        track_courses = resp.context_data["track_courses"]
        assert len(track_courses) == 1  # Only 1 track for courses
        assert track_courses[0]["track"] == "Adults"
        assert len(track_courses[0]["page_obj"].object_list) == Course.objects.count()

    def test_events_with_track_param(self):
        self.login(self.staff_user)
        resp = self.client.get(self.url + f"?track={self.adult_track.id}")
        track_events = resp.context_data["track_courses"]
        assert track_events[0]["track"] == "Adults"
        assert resp.context_data["active_tab"] == 0

        resp = self.client.get(self.url + "?track=invalid-id")
        track_events = resp.context_data["track_courses"]
        assert track_events[0]["track"] == "Adults"
        assert "active_tab" not in resp.context_data

    def test_pagination(self):
        baker.make(Course, event_type=self.aerial_event_type, _quantity=10)
        self.login(self.staff_user)

        resp = self.client.get(self.url + '?page=1&tab=0')
        assert len(resp.context_data["track_courses"][0]["page_obj"].object_list) == 10
        paginator = resp.context_data['track_courses'][0]["page_obj"]
        self.assertEqual(paginator.number, 1)

        # invalid tab, defaults to tab 0
        resp = self.client.get(self.url + '?page=2&tab=foo')
        assert len(resp.context_data["track_courses"][0]["page_obj"].object_list) == 1
        paginator = resp.context_data['track_courses'][0]["page_obj"]
        self.assertEqual(paginator.number, 2)

        resp = self.client.get(self.url + '?page=2&tab=0')
        assert len(resp.context_data["track_courses"][0]["page_obj"].object_list) == 1
        paginator = resp.context_data['track_courses'][0]["page_obj"]
        self.assertEqual(paginator.number, 2)

        # page not a number shows page 1
        resp = self.client.get(self.url + '?page=one&tab=0')
        paginator = resp.context_data['track_courses'][0]["page_obj"]
        self.assertEqual(paginator.number, 1)

        # page out of range shows last page
        resp = self.client.get(self.url + '?page=3&tab=0')
        assert len(resp.context_data["track_courses"][0]["page_obj"].object_list) == 1
        paginator = resp.context_data['track_courses'][0]["page_obj"]
        assert paginator.number == 2


class PastCourseAdminListViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_test_setup()
        self.create_users()
        self.create_admin_users()
        self.url = reverse('studioadmin:past_courses')
        self.login(self.staff_user)

    def test_get_no_past_course(self):
        resp = self.client.get(self.url)
        assert resp.context_data["past"] is True
        assert resp.context_data["track_courses"] == []

    def test_past_courses(self):
        # A course is past if all its events are in the past
        course = baker.make(Course, event_type=self.aerial_event_type, number_of_events=3)
        # course has 2 past events and one future
        baker.make_recipe("booking.past_event", event_type=self.aerial_event_type, course=course, _quantity=2)
        future_event = baker.make_recipe("booking.future_event", event_type=self.aerial_event_type, course=course)
        # Course is not shown in past events
        resp = self.client.get(self.url)
        assert resp.context_data["past"] is True
        assert resp.context_data["track_courses"] == []

        active_course_response = self.client.get(reverse('studioadmin:courses'))
        assert sorted(
            [course.id for course in active_course_response.context_data["track_courses"][0]["page_obj"].object_list]
        ) == sorted([self.course.id, course.id])

        future_event.start = timezone.now() - timedelta(1)
        future_event.save()
        resp = self.client.get(self.url)
        assert resp.context_data["past"] is True
        assert resp.context_data["track_courses"][0]["page_obj"].object_list == [course]
        active_course_response = self.client.get(reverse('studioadmin:courses'))
        assert active_course_response.context_data["track_courses"][0]["page_obj"].object_list == [self.course]

    def test_courses_with_no_events(self):
        # courses with no event are shown in the active courses, not past
        course_with_no_events = baker.make(Course, event_type=self.aerial_event_type, number_of_events=3)
        resp = self.client.get(self.url)
        assert resp.context_data["past"] is True
        assert resp.context_data["track_courses"] == []
        active_course_response = self.client.get(reverse('studioadmin:courses'))
        assert course_with_no_events in active_course_response.context_data["track_courses"][0]["page_obj"].object_list


class CourseAjaxToggleTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.course = baker.make(Course, number_of_events=2, show_on_site=False)
        self.events = baker.make_recipe(
            "booking.future_event", event_type=self.course.event_type, course=self.course,
            show_on_site=False, _quantity=2
        )

    def test_toggle_visible(self):
        url = reverse("studioadmin:ajax_toggle_course_visible", args=(self.course.id,))
        self.login(self.staff_user)
        assert self.course.show_on_site is False
        self.client.post(url)
        self.course.refresh_from_db()
        assert self.course.show_on_site is True
        for event in self.events:
            event.refresh_from_db()
            assert event.show_on_site is True

    def test_toggle_dropin_booking(self):
        url = reverse("studioadmin:ajax_toggle_course_allow_dropin_booking", args=(self.course.id,))
        self.login(self.staff_user)
        assert self.course.allow_drop_in is False
        self.client.post(url)
        self.course.refresh_from_db()
        assert self.course.allow_drop_in is True
        self.client.post(url)
        self.course.refresh_from_db()
        assert self.course.allow_drop_in is False


class CancelCourseViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.create_test_setup()
        self.course.max_participants = 10
        self.course.save()
        self.course_event.max_participants = 10
        self.course_event.save()

    def url(self, course):
        return reverse("studioadmin:cancel_course", args=(course.slug,))

    def test_only_staff_user_can_access(self):
        self.user_access_test(["staff"], self.url(self.course))

    def test_list_open_booking_users_on_course_events(self):
        url = self.url(self.course)
        event = baker.make_recipe(
            "booking.future_event", event_type=self.aerial_event_type, course=self.course
        )
        baker.make(Booking, event=self.course_event, _quantity=5)
        baker.make(Booking, event=self.course_event, status="CANCELLED", _quantity=3)
        baker.make(Booking, event=self.course_event, status="OPEN", no_show=True)
        # user has 2 bookings, only listed once
        baker.make(Booking, event=self.course_event, status="OPEN", user=self.student_user)
        baker.make(Booking, event=event, status="OPEN", user=self.student_user)

        assert Booking.objects.filter(event__course=self.course).count() == 11
        assert self.student_user.bookings.filter(event__course=self.course).count() == 2
        self.login(self.staff_user)
        resp = self.client.get(url)
        # Only list the uncancelled (open or no-show) bookings
        assert len(resp.context_data["bookings_to_cancel_users"]) == 7

    def test_cancel_course_no_bookings(self):
        # no bookings - event set to cancel, no emails sent
        url = self.url(self.course)
        self.login(self.staff_user)
        resp = self.client.post(
            url, data={"confirm": "yes, confirm", "additional_message": "", "send_email_confirmation": True}, follow=True
        )
        self.course.refresh_from_db()
        self.course_event.refresh_from_db()
        assert self.course.cancelled
        assert self.course_event.cancelled
        assert "Course and all associated events cancelled; no open bookings" in resp.rendered_content
        assert len(mail.outbox) == 0

    def test_cancel_course_with_cancelled_bookings(self):
        # event set to cancel
        baker.make(Booking, event=self.course_event, status="CANCELLED", _quantity=3)
        url = self.url(self.course)
        self.login(self.staff_user)
        resp = self.client.post(
            url, data={"confirm": "yes, confirm", "additional_message": "", "send_email_confirmation": True}, follow=True
        )
        self.course.refresh_from_db()
        self.course_event.refresh_from_db()
        assert self.course.cancelled
        assert self.course_event.cancelled
        # emails are sent to all users, including cancelled
        assert "Course and all associated events cancelled" in resp.rendered_content
        assert len(mail.outbox) == 0

    def test_cancel_course_with_open_bookings(self):
        # course and event set to cancel
        # bookings set to cancelled
        # blocks released from bookings
        # emails sent to manager users
        baker.make(
            Booking, block=baker.make_recipe("booking.course_block", paid=True, user=self.student_user),
            event=self.course_event, user=self.student_user
        )
        baker.make(
            Booking, block=baker.make_recipe("booking.course_block", paid=True, user=self.student_user1),
            event=self.course_event, user=self.student_user1
        )
        for booking in self.course_event.bookings.all():
            assert booking.status == "OPEN"
            assert booking.block is not None
        url = self.url(self.course)
        self.login(self.staff_user)
        resp = self.client.post(
            url, data={"confirm": "yes, confirm", "additional_message": "", "send_email_confirmation": True}, follow=True
        )
        self.course.refresh_from_db()
        self.course_event.refresh_from_db()
        assert self.course.cancelled
        assert self.course_event.cancelled
        for booking in self.course_event.bookings.all():
            assert booking.status == "CANCELLED"
            assert booking.block is None
        assert "Course and all associated events cancelled; bookings cancelled " \
               "and notification emails sent to students" in resp.rendered_content
        assert len(mail.outbox) == 1
        assert sorted(mail.outbox[0].bcc) == sorted([self.student_user.email, self.student_user1.email])

    def test_cancel_course_with_no_show_bookings(self):
        # event set to cancel
        # bookings set to cancelled
        # blocks released from bookings
        # emails sent to manager users
        open_booking = baker.make(
            Booking, block=baker.make_recipe("booking.course_block", paid=True, user=self.student_user),
            event=self.course_event, user=self.student_user
        )
        no_show_booking = baker.make(
            Booking, block=baker.make_recipe("booking.course_block", paid=True, user=self.student_user1),
            event=self.course_event, user=self.student_user1, no_show=True
        )
        url = self.url(self.course)
        self.login(self.staff_user)
        resp = self.client.post(
            url, data={"confirm": "yes, confirm", "additional_message": "", "send_email_confirmation": True}, follow=True
        )
        for obj in [self.course_event, open_booking, no_show_booking]:
            obj.refresh_from_db()
        self.course.refresh_from_db()
        self.course_event.refresh_from_db()
        assert self.course.cancelled
        assert self.course_event.cancelled
        # all bookings are cancelled
        assert open_booking.status == "CANCELLED"
        assert open_booking.block is None
        assert no_show_booking.status == "CANCELLED"
        assert no_show_booking.block is None

        assert "Course and all associated events cancelled; bookings cancelled and notification emails " \
               "sent to students" in resp.rendered_content
        # emails to open booking user only
        assert len(mail.outbox) == 1
        assert sorted(mail.outbox[0].bcc) == sorted([self.student_user.email, self.student_user1.email])

    def test_cancel_course_with_open_bookings_email_message(self):
        event = baker.make_recipe(
            "booking.future_event", event_type=self.aerial_event_type, course=self.course
        )
        # user has 2 bookings, only send email once
        baker.make(Booking, event=self.course_event, user=self.student_user)
        baker.make(Booking, event=event, user=self.student_user)
        url = self.url(self.course)
        self.login(self.staff_user)
        resp = self.client.post(
            url,
            data={"confirm": "yes, confirm", "additional_message": "This is an extra message.", "send_email_confirmation": True}
        )
        assert len(mail.outbox) == 1
        assert len(mail.outbox[0].bcc) == 1
        assert "This is an extra message." in mail.outbox[0].body

    def test_cancel_course_no_email(self):
        event = baker.make_recipe(
            "booking.future_event", event_type=self.aerial_event_type, course=self.course
        )
        baker.make(Booking, event=self.course_event, user=self.student_user)
        baker.make(Booking, event=event, user=self.student_user)
        url = self.url(self.course)
        self.login(self.staff_user)
        resp = self.client.post(
            url,
            data={"confirm": "yes, confirm", "additional_message": ""}
        )
        assert len(mail.outbox) == 0

    def test_cancel_course_with_open_bookings_emails_manager_user(self):
        baker.make(Booking, event=self.course_event, user=self.student_user)
        baker.make(Booking, event=self.course_event, user=self.child_user)
        url = self.url(self.course)
        self.login(self.staff_user)
        self.client.post(
            url, data={"confirm": "yes, confirm", "additional_message": "", "send_email_confirmation": True}
        )
        assert sorted(mail.outbox[0].bcc) == sorted([self.student_user.email, self.manager_user.email])


class CourseCreateViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.url = reverse("studioadmin:create_course", args=(self.aerial_event_type.id,))
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def form_data(self):
        return {
            "name": "test course",
            "description": "The course description",
            "event_type": self.aerial_event_type.id,
            "number_of_events": 3,
            "max_participants": 10,
            "show_on_site": False,
            "events": [],
            "cancelled": False
        }

    def test_only_staff(self):
        self.user_access_test(["staff"], self.url)

    def test_choose_event_type_for_course(self):
        url = reverse("studioadmin:choose_course_type_to_create")
        resp = self.client.get(url)
        assert len(resp.context["event_types"]) == EventType.objects.count()

    def test_create_course(self):
        assert Course.objects.exists() is False
        self.client.post(self.url, data=self.form_data())
        assert Course.objects.exists() is True
        new_course = Course.objects.first()
        assert new_course.name == "test course"

    def test_redirects_to_events_list_on_save(self):
        resp = self.client.post(self.url, data=self.form_data())
        assert resp.status_code == 302
        assert resp.url == reverse("studioadmin:courses") + f"?track={self.aerial_event_type.track.id}"

    def test_create_course_with_events(self):
        events = baker.make_recipe("booking.future_event", event_type=self.aerial_event_type, _quantity=2)
        data = self.form_data()
        data["events"] = [event.id for event in events]
        self.client.post(self.url, data)
        new_course = Course.objects.first()
        assert new_course.events.count() == 2

    def test_create_course_with_autogenerated_events(self):
        assert Event.objects.exists() is False
        data = {
            **self.form_data(),
            "create_events_name": "Created event",
            "create_events_time": "14:00",
            "create_events_duration": "45",
            "create_events_dates": "21-Nov-2060, 28-Nov-2060",
        }
        self.client.post(self.url, data)
        course_just_created = Course.objects.latest("id")
        assert Event.objects.count() == 2
        for event in Event.objects.all():
            assert event.course == course_just_created
            assert event.course.description == "The course description"
            assert event.duration == 45
            assert event.start.hour == 14
            assert event.max_participants == course_just_created.max_participants
            assert event.show_on_site == course_just_created.show_on_site
        assert sorted([
            event.start for event in Event.objects.all()
        ]) == [datetime(2060, 11, 21, 14, 0, tzinfo=dt_timezone.utc), datetime(2060, 11, 28, 14, 0, tzinfo=dt_timezone.utc)]

    def test_create_course_with_autogenerated_events_field_validation(self):
        data = {
            **self.form_data(),
            "create_events_dates": "07-Nov-2060, 14-11-2060",
        }
        resp = self.client.post(self.url, data)
        assert resp.context_data["form"].errors == {
            "create_events_dates": [
                "Some dates were entered in an invalid format (14-11-2060). Ensure all dates are in "
                 "the format dd-mmm-yyyy and separated by commas."
            ]
        }

        data = {
            **self.form_data(),
            "create_events_dates": "07-Nov-2060, 14-Nov-2060",
        }
        resp = self.client.post(self.url, data)

        assert resp.context_data["form"].errors == {
            "create_events_name": ["This field is required when creating new classes"],
            "create_events_time": ["This field is required when creating new classes"],
            "create_events_duration": ["This field is required when creating new classes"],
        }

    def test_create_course_with_autogenerated_events_too_many_events(self):
        # too many to autogenerate
        data = {
            **self.form_data(),
            "create_events_name": "Created event",
            "create_events_time": "14:00",
            "create_events_duration": "45",
            "create_events_dates": "07-Nov-2060, 14-Nov-2060, 21-Nov-2060, 28-Nov-2060",
        }
        resp = self.client.post(self.url, data)
        assert resp.context_data["form"].errors == {
            "create_events_dates": ["Too many classes selected or requested for creation; select a maximum total of 3."]
        }

        # too many with selected events as well
        events = baker.make_recipe("booking.future_event", event_type=self.aerial_event_type, _quantity=2)
        data = {
            **self.form_data(),
            "events": [event.id for event in events],
            "create_events_name": "Created event",
            "create_events_time": "14:00",
            "create_events_duration": "45",
            "create_events_dates": "07-Nov-2060, 14-Nov-2060",
        }
        resp = self.client.post(self.url, data)
        assert resp.context_data["form"].errors == {
            "events": ["Too many classes selected or requested for creation; select a maximum total of 3."],
            "create_events_dates": ["Too many classes selected or requested for creation; select a maximum total of 3."]
        }

    @pytest.mark.freeze_time('2021-03-18')
    def test_create_course_with_autogenerated_events_across_dst(self):
        assert Event.objects.exists() is False
        # Create with 2 events, one before and one after change to BST
        data = {
            **self.form_data(),
            "create_events_name": "Created event",
            "create_events_time": "14:00",
            "create_events_duration": "45",
            "create_events_dates": "22-Mar-2021, 29-Mar-2021",
        }
        self.client.post(self.url, data)
        assert Event.objects.count() == 2
        assert sorted([
            event.start for event in Event.objects.all()
        ]) == [datetime(2021, 3, 22, 14, 0, tzinfo=dt_timezone.utc), datetime(2021, 3, 29, 13, 0, tzinfo=dt_timezone.utc)]


class CourseUpdateViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.course = baker.make(Course, event_type=self.aerial_event_type, number_of_events=2)
        self.url = reverse("studioadmin:update_course", args=(self.course.slug,))
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def form_data(self):
        return {
            "id": self.course.id,
            "name": "test course",
            "description": "",
            "event_type": self.course.event_type.id,
            "number_of_events": self.course.number_of_events,
            "max_participants": 10,
            "show_on_site": False,
            "events": [],
            "cancelled": False
        }

    def test_only_staff(self):
        self.user_access_test(["staff"], self.url)

    def test_update_course(self):
        assert self.course.name != "test course"
        resp = self.client.post(self.url, data=self.form_data())
        self.course.refresh_from_db()
        assert self.course.name == "test course"

        assert resp.status_code == 302
        assert resp.url == reverse("studioadmin:courses") + f"?track={self.course.event_type.track.id}"

    def test_change_course_event_type(self):
        assert self.course.event_type == self.aerial_event_type
        baker.make_recipe(
            "booking.future_event", event_type=self.course.event_type, course=self.course, _quantity=2
        )
        assert self.course.events.count() == 2
        for event in self.course.events.all():
            assert event.event_type == self.aerial_event_type

        resp = self.client.post(
            self.url, 
            data={
                **self.form_data(), 
                "event_type": self.floor_event_type.id,
                "events": [event.id for event in self.course.events.all()]
            }
        )
        self.course.refresh_from_db()
        assert self.course.event_type == self.floor_event_type
        assert self.course.events.count() == 2
        for event in self.course.events.all():
            assert event.event_type == self.floor_event_type

    def test_event_type_form_field_is_shown(self):
        resp = self.client.get(self.url)
        form = resp.context_data["form"]
        assert isinstance(form.fields["event_type"].widget, forms.Select)

    def test_cancelled_field_only_shown_for_cancelled_courses(self):
        resp = self.client.get(self.url)
        form = resp.context_data["form"]
        assert isinstance(form.fields["cancelled"].widget, forms.HiddenInput)

        self.course.cancelled = True
        self.course.save()
        resp = self.client.get(self.url)
        form = resp.context_data["form"]
        assert isinstance(form.fields["cancelled"].widget, forms.CheckboxInput)

    def test_update_events_on_course(self):
        assert self.course.events.count() == 0
        event = baker.make_recipe("booking.future_event", event_type=self.course.event_type)
        form_data = {**self.form_data(), "events": [event.id]}
        self.client.post(self.url, data=form_data)
        self.course.refresh_from_db()
        assert self.course.events.count() == 1

    def test_update_events_on_configured_course(self):
        assert self.course.events.count() == 0
        events = baker.make_recipe("booking.future_event", event_type=self.course.event_type, _quantity=2)
        form_data = {**self.form_data(), "events": [event.id for event in events]}
        self.client.post(self.url, data=form_data)
        self.course.refresh_from_db()
        assert self.course.events.count() == 2

        new_event = baker.make_recipe("booking.future_event", event_type=self.course.event_type)
        # this adds too many events
        form_data = {**self.form_data(), "events": [event.id for event in [*events, new_event]]}
        resp = self.client.post(self.url, data=form_data)
        assert resp.status_code == 200
        form = resp.context_data["form"]
        assert form.errors == {
            "events": ["Too many classes selected or requested for creation; select a maximum total of 2."]
        }

        # but we can change events
        form_data = {**self.form_data(), "events": [events[0].id, new_event.id]}
        resp = self.client.post(self.url, data=form_data)
        self.course.refresh_from_db()
        assert self.course.events.count() == 2
        assert events[0] in self.course.events.all()
        assert events[1] not in self.course.events.all()
        assert new_event in self.course.events.all()

    def test_remove_events_on_booked_course(self):
        events = baker.make_recipe(
            "booking.future_event", event_type=self.course.event_type, _quantity=2
        )
        assert self.course.events.count() == 0
        form_data = {**self.form_data(), "events": [event.id for event in events]}
        self.client.post(self.url, data=form_data)
        self.course.refresh_from_db()
        assert self.course.events.count() == 2
        assert self.course.is_configured()

        baker.make(Booking, event=events[0])

        # Events can't be updated once bookings have been made; the events are hidden on
        # the form.  Posted events are ignored.
        form_data = {**self.form_data(), "events": [events[1].id]}
        resp = self.client.post(self.url, data=form_data)
        assert resp.status_code == 302
        self.course.refresh_from_db()
        assert self.course.events.count() == 2
        assert self.course.is_configured()
