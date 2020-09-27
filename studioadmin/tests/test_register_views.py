# -*- coding: utf-8 -*-
from datetime import timedelta
from model_bakery import baker

from django.core import mail
from django.urls import reverse
from django.utils import timezone
from django.test import TestCase

from booking.models import Event, Booking, WaitingListUser
from common.test_utils import EventTestMixin, TestUsersMixin


class EventRegisterListViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_test_setup()
        self.create_users()
        self.create_admin_users()
        self.url = reverse('studioadmin:registers')

    def test_staff_and_instructor_only(self):
        """
        test that the page redirects if user is not a staff user
        """
        self.user_access_test(["instructor", "staff"], self.url)

    def test_shows_registers(self):
        """
        test that the page redirects if user is not logged in
        """
        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert "track_events" in resp.context_data
        track_events = resp.context_data["track_events"]
        assert len(track_events) == 2  # 2 tracks, kids and adults
        assert track_events[0]["track"] == "Adults"
        assert len(track_events[0]["page_obj"].object_list) == Event.objects.filter(
            event_type__track=self.adult_track).count()
        assert track_events[1]["track"] == "Kids"
        assert len(track_events[1]["page_obj"].object_list) == Event.objects.filter(
            event_type__track=self.kids_track).count()

        assert "Click for register" in resp.rendered_content


class RegisterViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.event = baker.make_recipe("booking.future_event")
        self.url = reverse("studioadmin:register", args=(self.event.id,))

    def test_instructor_or_staff_allowed(self):
        self.user_access_test(["instructor", "staff"], self.url)

    def test_shows_enabled_add_new_booking_button(self):
        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert "bookingadd btn btn-xs btn-success" in resp.rendered_content
        assert "bookingadd btn btn-xs btn-success disabled" not in resp.rendered_content

        for i in range(self.event.max_participants):
            baker.make(Booking, event=self.event)
        resp = self.client.get(self.url)
        assert "bookingadd btn btn-xs btn-success disabled" in resp.rendered_content

    def test_shows_open_and_no_show_bookings(self):
        baker.make(Booking, event=self.event, status="OPEN")
        baker.make(Booking, event=self.event, status="CANCELLED")
        baker.make(Booking, event=self.event, status="OPEN", no_show=True)
        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert len(resp.context_data["bookings"]) == 2


class AddRegisterBookingTests(TestUsersMixin, TestCase):
    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.event = baker.make_recipe("booking.future_event")
        self.url = reverse("studioadmin:bookingregisteradd", args=(self.event.id,))

    def test_get(self):
        self.login(self.staff_user)
        resp = self.client.get(self.url, {'user': self.student_user.id})
        assert resp.status_code == 200
        assert resp.context_data["form_event"] == self.event

    def test_add_booking(self):
        self.login(self.staff_user)
        self.client.post(self.url, {'user': self.student_user.id})
        assert self.student_user.bookings.filter(event=self.event.id).exists()

    def test_reopen_booking(self):
        booking = baker.make(Booking, event=self.event, user=self.student_user, status="CANCELLED")
        self.login(self.staff_user)
        self.client.post(self.url, {'user': self.student_user.id})
        booking.refresh_from_db()
        assert booking.status == "OPEN"

    def test_adds_to_user_block(self):
        block = baker.make_recipe(
            "booking.dropin_block", block_config__event_type=self.event.event_type,
            user=self.student_user, paid=True
        )
        self.login(self.staff_user)
        self.client.post(self.url, {'user': self.student_user.id})
        booking = self.student_user.bookings.filter(event=self.event.id).first()
        assert booking.status == "OPEN"
        assert booking.block == block

    def test_removes_user_from_waiting_list(self):
        baker.make(WaitingListUser, user=self.student_user, event=self.event)
        self.login(self.staff_user)
        self.client.post(self.url, {'user': self.student_user.id})
        assert self.student_user.bookings.filter(event=self.event.id).exists()
        assert WaitingListUser.objects.filter(user=self.student_user).exists() is False

    def test_add_event_full(self):
        for i in range(self.event.max_participants):
            baker.make(Booking, event=self.event)
        self.login(self.staff_user)
        self.client.post(self.url, {'user': self.student_user.id})
        assert self.student_user.bookings.filter(event=self.event.id).exists() is False


class AjaxToggleAttendedTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.create_events_and_course()
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def test_toggle_attended(self):
        booking = baker.make(Booking, event=self.aerial_events[0])
        assert booking.no_show is False
        assert booking.attended is False

        url = reverse("studioadmin:ajax_toggle_attended", args=(booking.id,))
        self.client.post(url, {"attendance": "attended"})
        booking.refresh_from_db()
        assert booking.no_show is False
        assert booking.attended is True

        url = reverse("studioadmin:ajax_toggle_attended", args=(booking.id,))
        self.client.post(url, {"attendance": "no-show"})
        booking.refresh_from_db()
        assert booking.no_show is True
        assert booking.attended is False

    def test_toggle_attended_no_attendance_data(self):
        booking = baker.make(Booking, event=self.aerial_events[0])
        url = reverse("studioadmin:ajax_toggle_attended", args=(booking.id,))
        resp = self.client.post(url, {"attendance": "yes"})
        assert resp.status_code == 400
        assert resp.content.decode("utf-8") == "No attendance data"

        resp = self.client.post(url)
        assert resp.status_code == 400
        assert resp.content.decode("utf-8") == "No attendance data"

    def test_toggle_attended_event_full(self):
        event = self.aerial_events[0]
        booking = baker.make(Booking, event=event, status="CANCELLED")
        baker.make(Booking, event=event, _quantity=event.max_participants)

        url = reverse("studioadmin:ajax_toggle_attended", args=(booking.id,))
        resp = self.client.post(url, {"attendance": "attended"})
        assert resp.status_code == 400
        assert resp.content.decode("utf-8") == "Class is now full, cannot reopen booking."

    def test_toggle_attended_course_event_full(self):
        event = self.course_event
        booking = baker.make(Booking, event=event, status="OPEN", no_show=True)
        baker.make(Booking, event=event, _quantity=event.max_participants - 1)
        assert event.full

        url = reverse("studioadmin:ajax_toggle_attended", args=(booking.id,))
        resp = self.client.post(url, {"attendance": "attended"})
        booking.refresh_from_db()
        assert booking.attended is True
        assert booking.no_show is False

    def test_toggle_no_show_event_full(self):
        event = self.aerial_events[0]
        booking = baker.make(Booking, event=event, status="OPEN")
        baker.make(Booking, event=event, _quantity=event.max_participants - 1)

        url = reverse("studioadmin:ajax_toggle_attended", args=(booking.id,))
        resp = self.client.post(url, {"attendance": "no-show"}).json()
        assert resp["attended"] is False
        booking.refresh_from_db()
        assert booking.attended is False
        assert booking.no_show is True

    def test_toggle_no_show_does_not_remove_block(self):
        block = baker.make_recipe("booking.dropin_block", block_config__event_type=self.aerial_event_type)
        booking = baker.make(Booking, event=self.aerial_events[0], block=block)
        url = reverse("studioadmin:ajax_toggle_attended", args=(booking.id,))
        resp = self.client.post(url, {"attendance": "no-show"}).json()
        assert resp["attended"] is False
        booking.refresh_from_db()
        assert booking.attended is False
        assert booking.no_show is True
        assert booking.block == block

    def test_toggle_no_show_sends_waiting_list_emails_up_to_1hr_before(self):
        event = self.aerial_events[0]
        event.start = timezone.now() + timedelta(minutes=59)
        event.save()
        baker.make(Booking, event=event, _quantity=event.max_participants - 1)
        baker.make(WaitingListUser, user=self.student_user, event=event)

        booking = baker.make(Booking, event=event)
        url = reverse("studioadmin:ajax_toggle_attended", args=(booking.id,))
        self.client.post(url, {"attendance": "no-show"})

        # < 15mins before start, no emails sent
        assert len(mail.outbox) == 0
        booking.no_show = False
        booking.save()
        event.start = timezone.now() + timedelta(minutes=61)
        event.save()
        self.client.post(url, {"attendance": "no-show"})

        # >15mins before start, waiting list emails sent
        assert len(mail.outbox) == 1
        assert mail.outbox[0].bcc == [self.student_user.email]

