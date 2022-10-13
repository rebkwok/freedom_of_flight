# -*- coding: utf-8 -*-
from model_bakery import baker

from django.urls import reverse
from django.test import TestCase

from booking.models import Booking

from common.test_utils import TestUsersMixin, EventTestMixin


class BookingListViewTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse('booking:bookings')
        cls.create_cls_tracks_and_event_types()
        cls.past_aerial_event = baker.make_recipe("booking.past_event", event_type=cls.aerial_event_type)

    def setUp(self):
        self.create_users()
        self.create_events_and_course()
        for user in [self.student_user, self.manager_user, self.child_user]:
            self.make_disclaimer(user)
            self.make_data_privacy_agreement(user)
        # 2 aerial events
        self.aerial_bookings = [baker.make(Booking, user=self.student_user, event=event) for event in self.aerial_events]
        baker.make(Booking, event=self.past_aerial_event, user=self.student_user)
        self.login(self.student_user)

    def test_login_required(self):
        """
        test that page redirects if there is no user logged in
        """
        self.client.logout()
        url = reverse('booking:bookings')
        resp = self.client.get(url)
        assert resp.status_code == 302
        assert "login" in resp.url

    def test_booking_list(self):
        """
        Test that only future bookings are listed)
        """
        resp = self.client.get(self.url)
        assert Booking.objects.all().count() == 3
        assert resp.status_code == 200
        assert resp.context_data['bookings'].count() == 2

    def test_booking_list_by_user(self):
        """
        Test that only bookings for this user are listed
        """
        baker.make(Booking, user=self.child_user, event=self.aerial_events[0])
        # check there are now 4 bookings
        assert Booking.objects.all().count() == 4
        resp = self.client.get(self.url)

        # event listing should still only show this user's future bookings
        assert resp.context_data['bookings'].count() == 2

    def test_cancelled_booking_shown_in_booking_list(self):
        """
        Test that all future bookings for this user are listed
        """
        booking = self.aerial_bookings[0]
        booking.status = "CANCELLED"
        booking.save()

        assert Booking.objects.all().count() == 3
        resp = self.client.get(self.url)
        # booking listing should still show this user's future bookings,
        # including the cancelled one
        assert resp.context_data['bookings'].count() == 2

    def test_cancelled_events_shown_in_booking_list(self):
        """
        Test that all future bookings for cancelled events for this user are
        listed
        """
        ev = baker.make_recipe('booking.future_event', cancelled=True)
        baker.make(Booking, user=self.student_user, event=ev, status='CANCELLED')
        # check there are now 4 bookings (2 future, 1 past, 1 cancelled)
        assert Booking.objects.all().count() == 4
        resp = self.client.get(self.url)

        # booking listing should show this user's future bookings,
        # including the cancelled one
        assert resp.context_data['bookings'].count() == 3

    def test_booking_list_by_managed_user(self):
        """
        Test that only bookings for this user are listed
        """
        baker.make(Booking, user=self.child_user, event=self.aerial_events[0])
        # by default view_as_user for manager user is child user
        self.login(self.manager_user)
        resp = self.client.get(self.url)
        assert self.client.session["user_id"] == self.child_user.id
        assert resp.context_data['bookings'].count() == 1

        # post sets the session user id and redirects to the booking page again
        resp = self.client.post(self.url, data={"view_as_user": self.manager_user.id}, follow=True)
        assert self.client.session["user_id"] == self.manager_user.id
        assert resp.context_data['bookings'].count() == 0

    def test_button_displays(self):
        # TODO
        # With a single booking, check that the button displays as expected for:
        # - booked and open
        # - cancelled (with and without available blocks)
        # - no-show (with and without available blocks)
        # - event full and booked
        # - event full and cancelled/no-show
        # - event cancelled and cancelled/no-show
        # - on waiting list
        ...


class BookingHistoryListViewTests(TestUsersMixin, EventTestMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse('booking:past_bookings')
        cls.create_cls_tracks_and_event_types()
        cls.past_aerial_event = baker.make_recipe("booking.past_event", event_type=cls.aerial_event_type)

    def setUp(self):
        self.create_users()
        self.create_events_and_course()
        for user in [self.student_user, self.manager_user, self.child_user]:
            self.make_disclaimer(user)
            self.make_data_privacy_agreement(user)
        # 2 aerial events
        self.aerial_bookings = [baker.make(Booking, user=self.student_user, event=event) for event in
                                self.aerial_events]
        baker.make(Booking, event=self.past_aerial_event, user=self.student_user)
        self.login(self.student_user)

    def test_booking_list(self):
        """
        Test that only past bookings are listed
        """
        resp = self.client.get(self.url)
        assert "history" in resp.context_data
        assert Booking.objects.all().count() == 3
        assert resp.status_code == 200
        assert resp.context_data['bookings'].count() == 1

    def test_booking_list_by_managed_user(self):
        """
        Test that only bookings for this user are listed
        """
        baker.make(Booking, user=self.child_user, event=self.aerial_events[0])
        baker.make(Booking, event=self.past_aerial_event, user=self.child_user)
        # by default view_as_user for manager user is child user
        self.login(self.manager_user)
        resp = self.client.get(self.url)
        assert self.client.session["user_id"] == self.child_user.id
        # only shows past booking
        assert resp.context_data['bookings'].count() == 1

        # post sets the session user id and redirects to the booking page again
        resp = self.client.post(self.url, data={"view_as_user": self.manager_user.id}, follow=True)
        assert self.client.session["user_id"] == self.manager_user.id
        assert resp.context_data['bookings'].count() == 0
