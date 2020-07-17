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

from booking.models import Block, Event, Booking
from common.test_utils import TestUsersMixin, EventTestMixin


class EventAdminListViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_test_setup()
        self.create_users()
        self.create_admin_users()
        self.url = reverse('studioadmin:events')

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

    def test_events_by_track(self):
        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert "track_events" in resp.context_data
        track_events = resp.context_data["track_events"]
        assert len(track_events) == 2  # 2 tracks, kids and adults
        assert track_events[0]["track"] == "Adults"
        assert len(track_events[0]["queryset"].object_list) == Event.objects.filter(event_type__track=self.adult_track).count()
        assert track_events[1]["track"] == "Kids"
        assert len(track_events[1]["queryset"].object_list) == Event.objects.filter(event_type__track=self.kids_track).count()

    def test_pagination(self):
        baker.make_recipe('booking.future_event', event_type__track=self.adult_track, _quantity=20)
        self.login(self.staff_user)

        resp = self.client.get(self.url + '?page=1')
        assert len(resp.context_data["track_events"][0]["queryset"].object_list) == 20
        paginator = resp.context_data['track_events'][0]["queryset"]
        self.assertEqual(paginator.number, 1)

        resp = self.client.get(self.url + '?page=2&tab=0')
        assert len(resp.context_data["track_events"][0]["queryset"].object_list) == 6
        paginator = resp.context_data['track_events'][0]["queryset"]
        self.assertEqual(paginator.number, 2)

        # page not a number shows page 1
        resp = self.client.get(self.url + '?page=one')
        paginator = resp.context_data['track_events'][0]["queryset"]
        self.assertEqual(paginator.number, 1)

        # page out of range shows page q
        resp = self.client.get(self.url + '?page=3')
        assert len(resp.context_data["track_events"][0]["queryset"].object_list) == 20
        paginator = resp.context_data['track_events'][0]["queryset"]
        assert paginator.number == 1


class EventAjaxMakeVisibleTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.event = baker.make_recipe("booking.future__event")
        self.url = reverse("studioadmin:ajax_toggle_event_visible", args=(self.event.id,))

    def toggle_visible(self):
        self.login(self.staff_user)
        assert self.event.show_on_site is True
        self.client.post(self.url)
        assert self.event.show_on_site is False


class CancelEventViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.create_test_setup()
        self.event = self.aerial_events[0]
        self.event.max_participants = 20
        self.event.save()
        self.course.max_participants = 10
        self.course.save()
        self.course_event.max_participants = 10
        self.course_event.save()

    def url(self, event):
        return reverse("studioadmin:cancel_event", args=(event.slug,))

    def test_only_staff_user_can_access(self):
        url = self.url(self.event)
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

    def test_list_open_bookings_on_event(self):
        url = self.url(self.event)
        baker.make(Booking, event=self.event, _quantity=5)
        baker.make(Booking, event=self.event, status="CANCELLED", _quantity=3)
        baker.make(Booking, event=self.event, status="OPEN", no_show=True, _quantity=2)

        self.login(self.staff_user)
        resp = self.client.get(url)
        assert len(resp.context_data["bookings_to_cancel"]) == 5

    def test_list_open_and_no_show_bookings_on_course_event(self):
        url = self.url(self.course_event)
        baker.make(Booking, event=self.course_event, _quantity=5)
        baker.make(Booking, event=self.course_event, status="CANCELLED", _quantity=3)
        baker.make(Booking, event=self.course_event, status="OPEN", no_show=True, _quantity=2)

        self.login(self.staff_user)
        resp = self.client.get(url)
        assert len(resp.context_data["bookings_to_cancel"]) == 7

    def test_cancel_event_no_bookings(self):
        # no bookings - event deleted, no emails sent
        event_id = self.event.id
        url = self.url(self.event)
        self.login(self.staff_user)
        resp = self.client.post(
            url, data={"confirm": "yes, confirm", "additional_message": ""}, follow=True
        )
        assert Event.objects.filter(id=event_id).exists() is False
        assert "Event deleted" in resp.rendered_content
        assert len(mail.outbox) == 0

    def test_cancel_event_with_cancelled_bookings(self):
        # event set to cancel
        # no bookings - event set to cancel, no emails sent
        baker.make(Booking, event=self.event, status="CANCELLED", _quantity=3)
        url = self.url(self.event)
        self.login(self.staff_user)
        resp = self.client.post(
            url, data={"confirm": "yes, confirm", "additional_message": ""}, follow=True
        )
        self.event.refresh_from_db()
        assert self.event.cancelled
        assert "Event cancelled; no open bookings" in resp.rendered_content
        assert len(mail.outbox) == 0

    def test_cancel_event_with_open_bookings(self):
        # event set to cancel
        # bookings set to cancelled
        # blocks released from bookings
        # emails sent to manager users
        baker.make(
            Booking, block=baker.make_recipe("booking.dropin_block", paid=True, user=self.student_user),
            event=self.event, user=self.student_user
        )
        baker.make(
            Booking, block=baker.make_recipe("booking.dropin_block", paid=True, user=self.student_user1),
            event=self.event, user=self.student_user1
        )
        for booking in self.event.bookings.all():
            assert booking.status == "OPEN"
            assert booking.block is not None
        url = self.url(self.event)
        self.login(self.staff_user)
        resp = self.client.post(
            url, data={"confirm": "yes, confirm", "additional_message": ""}, follow=True
        )
        self.event.refresh_from_db()
        assert self.event.cancelled
        for booking in self.event.bookings.all():
            assert booking.status == "CANCELLED"
            assert booking.block is None
        assert "Event cancelled; bookings cancelled and notification emails sent to students" in resp.rendered_content
        assert len(mail.outbox) == 1
        assert sorted(mail.outbox[0].bcc) == sorted([self.student_user.email, self.student_user1.email])

    def test_cancel_event_with_no_show_bookings(self):
        # event set to cancel
        # bookings set to cancelled
        # blocks released from bookings
        # emails sent to manager users
        open_booking = baker.make(
            Booking, block=baker.make_recipe("booking.dropin_block", paid=True, user=self.student_user),
            event=self.event, user=self.student_user
        )
        no_show_booking = baker.make(
            Booking, block=baker.make_recipe("booking.dropin_block", paid=True, user=self.student_user1),
            event=self.event, user=self.student_user1, no_show=True
        )
        url = self.url(self.event)
        self.login(self.staff_user)
        resp = self.client.post(
            url, data={"confirm": "yes, confirm", "additional_message": ""}, follow=True
        )
        for obj in [self.event, open_booking, no_show_booking]:
            obj.refresh_from_db()
        assert self.event.cancelled
        assert open_booking.status == "CANCELLED"
        assert open_booking.block is None
        assert no_show_booking.status == "OPEN"
        assert no_show_booking.no_show is True
        assert no_show_booking.block is not None

        assert "Event cancelled; bookings cancelled and notification emails sent to students" in resp.rendered_content
        # emails to open booking user only
        assert len(mail.outbox) == 1
        assert mail.outbox[0].bcc == [self.student_user.email]

    def test_cancel_event_on_course(self):
        # event set to cancel
        # event removed from course
        # bookings set to cancelled
        # block released from bookings
        # emails sent to manager users
        open_booking = baker.make(
            Booking, block=baker.make_recipe("booking.course_block", paid=True, user=self.student_user),
            event=self.course_event, user=self.student_user
        )
        no_show_booking = baker.make(
            Booking, block=baker.make_recipe("booking.course_block", paid=True, user=self.student_user1),
            event=self.course_event, user=self.student_user1, no_show=True
        )
        url = self.url(self.course_event)
        self.login(self.staff_user)
        resp = self.client.post(
            url, data={"confirm": "yes, confirm", "additional_message": ""}, follow=True
        )
        for obj in [self.course_event, open_booking, no_show_booking]:
            obj.refresh_from_db()
        assert self.course_event.cancelled
        assert open_booking.status == "CANCELLED"
        assert open_booking.block is None
        assert no_show_booking.status == "CANCELLED"
        assert no_show_booking.block is None

        assert "Event cancelled and removed from course; " \
               "bookings cancelled and notification emails sent to students" in resp.rendered_content
        # emails to open and no-show booking users
        assert len(mail.outbox) == 1
        assert sorted(mail.outbox[0].bcc) == sorted([self.student_user.email, self.student_user1.email])

    def test_cancel_event_with_open_bookings_email_message(self):
        baker.make(Booking, event=self.event, user=self.student_user)
        url = self.url(self.event)
        self.login(self.staff_user)
        resp = self.client.post(
            url, data={"confirm": "yes, confirm", "additional_message": "This is an extra message."}
        )
        assert len(mail.outbox) == 1
        assert "This is an extra message." in mail.outbox[0].body

    def test_cancel_event_with_open_bookings_emails_manager_user(self):
        baker.make(Booking, event=self.event, user=self.student_user)
        baker.make(Booking, event=self.event, user=self.child_user)
        url = self.url(self.event)
        self.login(self.staff_user)
        self.client.post(
            url, data={"confirm": "yes, confirm", "additional_message": ""}
        )
        assert sorted(mail.outbox[0].bcc) == sorted([self.student_user.email, self.manager_user.email])


class EventCreateViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.url = reverse("studioadmin:create_event", args=(self.aerial_event_type.id,))
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def form_data(self):
        return {
            "name": "test",
            "description": "",
            "event_type": self.aerial_event_type.id,
            "start": "10-Jul-2020 16:00",
            "max_participants": 10,
            "duration": 90,
            "video_link": "",
            "show_on_site": False
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

    def test_create_event(self):
        assert Event.objects.exists() is False
        resp = self.client.post(self.url, data=self.form_data())
        assert Event.objects.exists() is True
        new_event = Event.objects.first()
        assert new_event.name == "test"

    def test_redirects_to_events_list_on_save(self):
        resp = self.client.post(self.url, data=self.form_data())
        assert resp.status_code == 302
        assert resp.url == reverse("studioadmin:events") + f"?track={self.aerial_event_type.track.id}"


class EventUpdateViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.event = baker.make_recipe("booking.future_event", event_type=self.aerial_event_type)
        self.url = reverse("studioadmin:update_event", args=(self.event.slug,))
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def form_data(self):
        return {
            "id": self.event.id,
            "name": "test",
            "description": "",
            "event_type": self.aerial_event_type.id,
            "start": "10-Jul-2020 16:00",
            "max_participants": 10,
            "duration": 90,
            "video_link": "",
            "show_on_site": False
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

    def test_update_event(self):
        assert self.event.name != "test"
        resp = self.client.post(self.url, data=self.form_data())
        self.event.refresh_from_db()
        assert self.event.name == "test"

        assert resp.status_code == 302
        assert resp.url == reverse("studioadmin:events") + f"?track={self.aerial_event_type.track.id}"

    def test_event_type_form_field_is_shown(self):
        resp = self.client.get(self.url)
        form = resp.context_data["form"]
        assert isinstance(form.fields["event_type"].widget, forms.Select)
