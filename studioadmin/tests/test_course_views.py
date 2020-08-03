# -*- coding: utf-8 -*-
from datetime import timedelta

from unittest.mock import patch

from model_bakery import baker

from django.conf import settings
from django import forms
from django.urls import reverse
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from booking.models import Block, Event, Booking, Course
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

    def test_cannot_access_if_not_staff(self):
        """
        test that the page redirects if user is not a staff user
        """
        self.login(self.student_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == reverse('booking:permission_denied')

    def test_instructor_group_cannot_access(self):
        """
        test that the page redirects if user is in the instructor group but is
        not a staff user
        """
        self.login(self.instructor_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == reverse('booking:permission_denied')

    def test_can_access_as_staff_user(self):
        """
        test that the page can be accessed by a staff user
        """
        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 200

    def test_courses_by_track(self):
        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert "track_courses" in resp.context_data
        track_events = resp.context_data["track_courses"]
        assert len(track_events) == 1  # Only 1 track for courses
        assert track_events[0]["track"] == "Adults"
        assert len(track_events[0]["queryset"].object_list) == Course.objects.count()

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
        baker.make(Course, event_type=self.aerial_event_type, _quantity=20)
        self.login(self.staff_user)

        resp = self.client.get(self.url + '?page=1')
        assert len(resp.context_data["track_courses"][0]["queryset"].object_list) == 20
        paginator = resp.context_data['track_courses'][0]["queryset"]
        self.assertEqual(paginator.number, 1)

        # invalid tab, defaults to tab 0
        resp = self.client.get(self.url + '?page=2&tab=foo')
        assert len(resp.context_data["track_courses"][0]["queryset"].object_list) == 1
        paginator = resp.context_data['track_courses'][0]["queryset"]
        self.assertEqual(paginator.number, 2)

        resp = self.client.get(self.url + '?page=2&tab=0')
        assert len(resp.context_data["track_courses"][0]["queryset"].object_list) == 1
        paginator = resp.context_data['track_courses'][0]["queryset"]
        self.assertEqual(paginator.number, 2)

        # page not a number shows page 1
        resp = self.client.get(self.url + '?page=one')
        paginator = resp.context_data['track_courses'][0]["queryset"]
        self.assertEqual(paginator.number, 1)

        # page out of range shows page q
        resp = self.client.get(self.url + '?page=3')
        assert len(resp.context_data["track_courses"][0]["queryset"].object_list) == 20
        paginator = resp.context_data['track_courses'][0]["queryset"]
        assert paginator.number == 1


class CourseAjaxMakeVisibleTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.course = baker.make(Course, number_of_events=2, show_on_site=False)
        self.events = baker.make_recipe(
            "booking.future_event", event_type=self.course.event_type, course=self.course,
            show_on_site=False, _quantity=2
        )
        self.url = reverse("studioadmin:ajax_toggle_course_visible", args=(self.course.id,))

    def test_toggle_visible(self):
        self.login(self.staff_user)
        assert self.course.show_on_site is False
        self.client.post(self.url)
        self.course.refresh_from_db()
        assert self.course.show_on_site is True
        for event in self.events:
            event.refresh_from_db()
            assert event.show_on_site is True


class CancelEventViewTests(EventTestMixin, TestUsersMixin, TestCase):

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
        url = self.url(self.course)
        self.login(self.student_user)
        resp = self.client.get(url)
        assert resp.status_code == 302
        assert resp.url == reverse("booking:permission_denied")

        self.login(self.instructor_user)
        resp = self.client.get(url)
        assert resp.status_code == 302
        assert resp.url == reverse("booking:permission_denied")

        self.login(self.staff_user)
        resp = self.client.get(url)
        assert resp.status_code == 200

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
        # We don't care about status, just cancel all bookings
        assert len(resp.context_data["bookings_to_cancel_users"]) == 10

    def test_cancel_course_no_bookings(self):
        # no bookings - event set to cancel, no emails sent
        url = self.url(self.course)
        self.login(self.staff_user)
        resp = self.client.post(
            url, data={"confirm": "yes, confirm", "additional_message": ""}, follow=True
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
            url, data={"confirm": "yes, confirm", "additional_message": ""}, follow=True
        )
        self.course.refresh_from_db()
        self.course_event.refresh_from_db()
        assert self.course.cancelled
        assert self.course_event.cancelled
        # emails are sent to all users, including cancelled
        assert "Course and all associated events cancelled; bookings cancelled " \
               "and notification emails sent to students" in resp.rendered_content
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
            url, data={"confirm": "yes, confirm", "additional_message": ""}, follow=True
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
            url, data={"confirm": "yes, confirm", "additional_message": ""}, follow=True
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
            url, data={"confirm": "yes, confirm", "additional_message": "This is an extra message."}
        )
        assert len(mail.outbox) == 1
        assert len(mail.outbox[0].bcc) == 1
        assert "This is an extra message." in mail.outbox[0].body

    def test_cancel_course_with_open_bookings_emails_manager_user(self):
        baker.make(Booking, event=self.course_event, user=self.student_user)
        baker.make(Booking, event=self.course_event, user=self.child_user)
        url = self.url(self.course)
        self.login(self.staff_user)
        self.client.post(
            url, data={"confirm": "yes, confirm", "additional_message": ""}
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
            "description": "",
            "event_type": self.aerial_event_type.id,
            "number_of_events": 3,
            "max_participants": 10,
            "show_on_site": False,
            "events": [],
            "cancelled": False
        }

    def test_only_staff(self):
        self.login(self.student_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == reverse("booking:permission_denied")

        self.login(self.instructor_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == reverse("booking:permission_denied")

        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 200

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


class CourseUpdateViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.course = baker.make(Course, event_type=self.aerial_event_type)
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
        self.login(self.student_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == reverse("booking:permission_denied")

        self.login(self.instructor_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == reverse("booking:permission_denied")

        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 200

    def test_update_course(self):
        assert self.course.name != "test course"
        resp = self.client.post(self.url, data=self.form_data())
        self.course.refresh_from_db()
        assert self.course.name == "test course"

        assert resp.status_code == 302
        assert resp.url == reverse("studioadmin:courses") + f"?track={self.course.event_type.track.id}"

    def test_event_type_form_field_is_shown(self):
        resp = self.client.get(self.url)
        form = resp.context_data["form"]
        assert isinstance(form.fields["event_type"].widget, forms.Select)
