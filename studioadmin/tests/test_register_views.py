# -*- coding: utf-8 -*-
from model_bakery import baker

from django.urls import reverse
from django.test import TestCase

from booking.models import Event, Booking, WaitingListUser
from common.test_utils import EventTestMixin, TestUsersMixin


class EventRegisterListViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_test_setup()
        self.create_users()
        self.create_admin_users()
        self.url = reverse('studioadmin:registers')

    def test_cannot_access_if_not_staff(self):
        """
        test that the page redirects if user is not a staff user
        """
        self.login(self.student_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == reverse('booking:permission_denied')

    def test_instructor_group_can_access(self):
        """
        test that the page redirects if user is in the instructor group but is
        not a staff user
        """
        self.login(self.instructor_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 200

    def test_can_access_as_staff_user(self):
        """
        test that the page can be accessed by a staff user
        """
        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 200

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
        assert len(track_events[0]["queryset"].object_list) == Event.objects.filter(
            event_type__track=self.adult_track).count()
        assert track_events[1]["track"] == "Kids"
        assert len(track_events[1]["queryset"].object_list) == Event.objects.filter(
            event_type__track=self.kids_track).count()

        assert "Click for register" in resp.rendered_content


class RegisterViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.event = baker.make_recipe("booking.future_event")
        self.url = reverse("studioadmin:register", args=(self.event.id,))

    def test_instructor_or_staff_allowed(self):
        self.login(self.student_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == reverse("booking:permission_denied")

        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 200

        self.login(self.instructor_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 200

    def test_shows_enabled_add_new_booking_button(self):
        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert "bookingadd btn btn-success" in resp.rendered_content
        assert "bookingadd btn btn-success disabled" not in resp.rendered_content

        for i in range(self.event.max_participants):
            baker.make(Booking, event=self.event)
        resp = self.client.get(self.url)
        assert "bookingadd btn btn-success disabled" in resp.rendered_content

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

    def test_add_open_booking_already_exists(self):
        booking = baker.make(Booking, event=self.event, user=self.student_user)
        self.login(self.staff_user)
        self.client.post(self.url, {'user': self.student_user.id})
        booking.refresh_from_db()
        assert booking.status == "OPEN"

    def test_adds_to_user_block(self):
        block = baker.make_recipe(
            "booking.dropin_block", dropin_block_config__event_type=self.event.event_type,
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
