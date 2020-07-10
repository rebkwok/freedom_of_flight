# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import patch
from model_bakery import baker

from django.conf import settings
from django.core import mail
from django.urls import reverse
from django.test import override_settings, TestCase
from django.contrib.auth.models import Group, User
from django.utils import timezone

from accounts.models import DisclaimerContent, OnlineDisclaimer, has_active_disclaimer

from booking.models import Event, EventType, Booking, Block, WaitingListUser
from common.test_utils import make_disclaimer_content, make_online_disclaimer, TestUsersMixin, EventTestMixin



class BookingToggleAjaxViewTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

    def setUp(self):
        super().setUp()
        self.create_users()
        self.make_data_privacy_agreement(self.student_user)
        self.make_data_privacy_agreement(self.manager_user)
        self.make_disclaimer(self.student_user)
        self.login(self.student_user)

        # make sure these are reset for each test
        self.floor_event_type.email_studio_when_booked = False
        self.floor_event_type.allow_booking_cancellation = True
        self.floor_event_type.save()

    def url(self, event_id):
        return reverse('booking:ajax_toggle_booking', args=[event_id])

    def test_redirect_if_booking_user_has_no_disclaimer(self):
        assert has_active_disclaimer(self.manager_user) is False
        self.login(self.manager_user)
        resp = self.client.post(self.url(self.aerial_events[0].id), data={"user_id": self.child_user.id})
        # redirects to the disclaimer page for the child user, even though manager user has no disclaimer
        redirect_url = reverse('booking:disclaimer_required', args=(self.child_user.id,))
        assert resp.json() == {"redirect": True, "url": redirect_url}

        # if the manager user has no disclaimer but is booking for a managed user with a disclaimer, that's finr

        self.make_disclaimer(self.child_user)
        # child user has valid block
        baker.make(Block, dropin_block_config__event_type=self.aerial_event_type, user=self.child_user, paid=True)
        resp = self.client.post(self.url(self.aerial_events[0].id), data={"user_id": self.child_user.id})
        assert resp.status_code == 200
        assert Booking.objects.filter(event=self.aerial_events[0], user=self.child_user).exists()

    def test_create_booking_no_available_block(self):
        """
        Test creating a booking
        """
        assert Booking.objects.exists() is False
        resp = self.client.post(self.url(self.aerial_events[0].id), data={"user_id": self.student_user.id})
        assert resp.status_code == 200
        redirect_url = reverse('booking:dropin_block_purchase', args=(self.aerial_events[0].slug,))
        assert resp.json() == {"redirect": True, "url": redirect_url}

    def test_create_booking(self):
        """
        Test creating a booking
        """
        # block not paid, can't be used
        block = baker.make(Block, dropin_block_config__event_type=self.aerial_event_type, user=self.student_user)
        assert Booking.objects.exists() is False
        resp = self.client.post(self.url(self.aerial_events[0].id), data={"user_id": self.student_user.id})
        assert "redirect" in resp.json()

        block.paid = True
        block.save()
        resp = self.client.post(self.url(self.aerial_events[0].id), data={"user_id": self.student_user.id})
        assert Booking.objects.count() == 1
        assert resp.context['alert_message']['message'] ==  'Booking has been opened'

        # email to student only
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["student@test.com"]

    def test_create_booking_sends_email_to_studio_if_set(self):
        """
        Test creating a booking send email to user and studio if flag sent on
        event
        """
        self.floor_event_type.email_studio_when_booked = True
        self.floor_event_type.save()
        event = baker.make_recipe(
            "booking.future_event", event_type=self.floor_event_type
        )
        # user has available block
        baker.make(
            Block, dropin_block_config__event_type=self.floor_event_type, user=self.student_user, paid=True
        )
        assert event.bookings.count() == 0
        resp = self.client.post(self.url(event.id), data={"user_id": self.student_user.id})
        assert event.bookings.count() == 1
        assert resp.context['alert_message']['message'] ==  'Booking has been opened'

        # email to student and studio only
        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == ["student@test.com"]
        assert mail.outbox[1].to == [settings.DEFAULT_STUDIO_EMAIL]

    def test_cannot_book_for_full_event(self):
        event = baker.make_recipe("booking.future_event", event_type=self.floor_event_type, max_participants=3)
        # user has available block
        baker.make(
            Block, dropin_block_config__event_type=self.floor_event_type, user=self.student_user, paid=True
        )
        # make event full
        baker.make(Booking, event=event, _quantity=3)
        resp = self.client.post(self.url(event.id), data={"user_id": self.student_user.id})

        # no new bookings made
        assert event.bookings.count() == 3
        assert resp.status_code == 400
        assert resp.content.decode("utf-8") == "Sorry, this event is now full"

    def test_cannot_book_for_cancelled_event(self):
        # cancelled event
        event = baker.make_recipe("booking.future_event", event_type=self.floor_event_type, cancelled=True)
        # user has available block
        baker.make(
            Block, dropin_block_config__event_type=self.floor_event_type, user=self.student_user, paid=True
        )
        resp = self.client.post(self.url(event.id), data={"user_id": self.student_user.id})

        # no new bookings made
        assert event.bookings.count() == 0
        assert resp.status_code == 400
        assert resp.content.decode("utf-8") == "Sorry, this event has been cancelled"

    def test_rebook_cancelled_booking(self):
        # user has available block
        block = baker.make(
            Block, dropin_block_config__event_type=self.aerial_event_type, user=self.student_user, paid=True
        )
        booking = baker.make(
            Booking, user=self.student_user, event=self.aerial_events[0], status="CANCELLED"
        )
        resp = self.client.post(self.url(self.aerial_events[0].id), data={"user_id": self.student_user.id})
        booking.refresh_from_db()
        assert booking.status == "OPEN"
        assert booking.block == block
        assert resp.context['alert_message']['message'] ==  'Booking has been reopened'

        # email to student only
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["student@test.com"]

    def test_already_booked_cancels_booking(self):
        # user has available block
        block = baker.make(
            Block, dropin_block_config__event_type=self.aerial_event_type, user=self.student_user, paid=True
        )
        booking = baker.make(
            Booking, user=self.student_user, event=self.aerial_events[0], status="OPEN", block=block
        )
        resp = self.client.post(self.url(self.aerial_events[0].id), data={"user_id": self.student_user.id})
        booking.refresh_from_db()
        assert booking.status == "CANCELLED"
        # block is not removed
        assert booking.block is None
        assert resp.context['alert_message']['message'] ==  'Booking has been cancelled'

        # email to student only
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["student@test.com"]

    def test_rebook_no_show_booking(self):
        # user has available block
        block = baker.make(
            Block, dropin_block_config__event_type=self.aerial_event_type, user=self.student_user, paid=True
        )
        booking = baker.make(
            Booking, user=self.student_user, event=self.aerial_events[0], status="OPEN", no_show=True,
            block=block
        )
        resp = self.client.post(self.url(self.aerial_events[0].id), data={"user_id": self.student_user.id})
        booking.refresh_from_db()
        assert booking.status == "OPEN"
        assert booking.no_show is False
        # block is not removed from no-show
        assert booking.block == block
        assert resp.context['alert_message']['message'] ==  'Booking has been reopened'

        # email to student only
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["student@test.com"]

    def test_create_booking_user_on_waiting_list(self):
        # user has available block
        baker.make(
            Block, dropin_block_config__event_type=self.aerial_event_type, user=self.student_user, paid=True
        )
        baker.make(WaitingListUser, user=self.student_user, event=self.aerial_events[0])
        assert WaitingListUser.objects.filter(user=self.student_user, event=self.aerial_events[0]).exists() is True
        resp = self.client.post(self.url(self.aerial_events[0].id), data={"user_id": self.student_user.id})
        assert Booking.objects.count() == 1
        assert resp.context['alert_message']['message'] ==  'Booking has been opened'
        # user removed from waiting list
        assert WaitingListUser.objects.filter(user=self.student_user, event=self.aerial_events[0]).exists() is False

        # email to student only
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["student@test.com"]

    def test_cancel_booking_from_full_event_emails_waiting_list(self):
        event = baker.make_recipe("booking.future_event", event_type=self.floor_event_type, max_participants=2)
        # user has available block and booking
        baker.make(
            Block, dropin_block_config__event_type=self.floor_event_type, user=self.student_user, paid=True
        )
        booking = baker.make(Booking, user=self.student_user, event=event)
        # make another booking so event is full
        baker.make(Booking, event=event)
        assert event.full is True

        # another user is on waiting list
        baker.make(WaitingListUser, user=self.student_user1, event=event)

        # cancel booking
        resp = self.client.post(self.url(event.id), data={"user_id": self.student_user.id})
        booking.refresh_from_db()
        assert booking.status == "CANCELLED"

        # email to waiting list and then to student
        assert len(mail.outbox) == 2
        assert mail.outbox[0].bcc == ["student1@test.com"]
        assert mail.outbox[1].to == ["student@test.com"]

    def test_cancel_booking_for_full_event_sends_waiting_list_emails_to_managed_user_email(self):
        event = baker.make_recipe("booking.future_event", event_type=self.floor_event_type, max_participants=2)
        # user has available block and booking
        baker.make(
            Block, dropin_block_config__event_type=self.floor_event_type, user=self.student_user, paid=True
        )
        baker.make(Booking, user=self.student_user, event=event)
        # make another booking so event is full
        baker.make(Booking, event=event)

        # child user is on waiting list
        baker.make(WaitingListUser, user=self.child_user, event=event)

        # cancel booking
        self.client.post(self.url(event.id), data={"user_id": self.student_user.id})
        # email to manager email for waiting list and then to student
        assert len(mail.outbox) == 2
        assert mail.outbox[0].bcc == ["manager@test.com"]
        assert mail.outbox[1].to == ["student@test.com"]

    def test_cancel_booking_after_cancellation_period(self):
        # set to no show, keep block
        event = baker.make_recipe(
            "booking.future_event", event_type=self.floor_event_type, start=timezone.now() + timedelta(hours=23)
        )
        # user has available block and booking
        block = baker.make(
            Block, dropin_block_config__event_type=self.floor_event_type, user=self.student_user, paid=True
        )
        booking = baker.make(Booking, user=self.student_user, event=event, block=block)
        # cancel booking, set to no-show
        self.client.post(self.url(event.id), data={"user_id": self.student_user.id})
        booking.refresh_from_db()
        assert booking.status == "OPEN"
        assert booking.block == block
        assert booking.no_show == True

    def test_cancel_booking_cancellation_not_allowed(self):
        # set to no show, keep block
        self.floor_event_type.allow_booking_cancellation = False
        self.floor_event_type.save()
        event = baker.make_recipe(
            "booking.future_event", event_type=self.floor_event_type, start=timezone.now() + timedelta(hours=48)
        )
        # user has available block and booking
        block = baker.make(
            Block, dropin_block_config__event_type=self.floor_event_type, user=self.student_user, paid=True
        )
        booking = baker.make(Booking, user=self.student_user, event=event, block=block)
        # cancel booking, set to no-show
        self.client.post(self.url(event.id), data={"user_id": self.student_user.id})
        booking.refresh_from_db()
        assert booking.status == "OPEN"
        assert booking.block == block
        assert booking.no_show == True

    def test_cancel_booking_from_course(self):
        # always set to no show, keep block
        course_event = baker.make_recipe(
            "booking.future_event", event_type=self.aerial_event_type, course=self.course,
            start=timezone.now() + timedelta(hours=48)
        )
        # user has available block and booking
        block = baker.make(
            Block, course_block_config__course_type=self.course_type, user=self.student_user, paid=True
        )
        booking = baker.make(Booking, user=self.student_user, event=course_event, block=block)
        # cancel booking, set to no-show
        self.client.post(self.url(course_event.id), data={"user_id": self.student_user.id})
        booking.refresh_from_db()
        assert booking.status == "OPEN"
        assert booking.block == block
        assert booking.no_show == True


class BookingAjaxCourseBookingViewTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

    def setUp(self):
        super().setUp()
        self.create_users()
        self.make_data_privacy_agreement(self.student_user)
        self.make_data_privacy_agreement(self.manager_user)
        self.make_disclaimer(self.student_user)
        self.login(self.student_user)

        # make sure these are reset for each test
        # make some more events on the course
        course_events = baker.make_recipe(
            "booking.future_event", course=self.course, event_type=self.aerial_event_type, _quantity=2
        )
        self.course_events = [self.course_event, *course_events]
        assert self.course.is_configured()
        self.course.cancelled = False
        self.course.save()

    def url(self, course_id):
        return reverse('booking:ajax_course_booking', args=[course_id])

    def test_book_course_no_available_block(self):
        resp = self.client.post(self.url(self.course.id), data={"user_id": self.student_user.id}).json()
        assert resp["redirect"] is True
        redirect_url = reverse('booking:course_block_purchase', args=(self.course.slug,))
        assert resp["url"] == redirect_url

    def test_book_course(self):
        # booking a course books for all events on the course
        # make usable block
        block = baker.make(
            Block, user=self.student_user, course_block_config__course_type=self.course_type, paid=True
        )
        assert self.course.is_configured()
        resp = self.client.post(self.url(self.course.id), data={"user_id": self.student_user.id})
        assert resp.status_code == 200
        resp = resp.json()
        assert resp['redirect'] is True
        redirect_url = reverse('booking:course_events', args=(self.course.slug,))
        assert resp['url'] == redirect_url

        for event in self.course_events:
            assert event.bookings.filter(user=self.student_user, status="OPEN", block=block).exists()

        # 1 email sent
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["student@test.com"]
        assert "Course booked:" in mail.outbox[0].subject

    def test_book_course_for_managed_user(self):
        # booking a course books for all events on the course
        # make usable block
        self.login(self.manager_user)
        self.make_disclaimer(self.child_user)
        block = baker.make(
            Block, user=self.child_user, course_block_config__course_type=self.course_type, paid=True
        )
        resp = self.client.post(self.url(self.course.id), data={"user_id": self.child_user.id})
        assert resp.status_code == 200
        resp = resp.json()
        assert resp['redirect'] is True
        redirect_url = reverse('booking:course_events', args=(self.course.slug,))
        assert resp['url'] == redirect_url

        for event in self.course_events:
            assert event.bookings.filter(user=self.child_user, status="OPEN", block=block).exists()

        # 1 email sent, to booking user
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["manager@test.com"]
        assert "Course booked:" in mail.outbox[0].subject

    def test_disclaimer_required_for_booking_user(self):
        assert has_active_disclaimer(self.manager_user) is False
        assert has_active_disclaimer(self.child_user) is False
        self.login(self.manager_user)
        block = baker.make(
            Block, user=self.child_user, course_block_config__course_type=self.course_type, paid=True
        )
        resp = self.client.post(self.url(self.course.id), data={"user_id": self.child_user.id})
        # redirects to the disclaimer page for the child user, even though manager user has no disclaimer
        redirect_url = reverse('booking:disclaimer_required', args=(self.child_user.id,))
        assert resp.json() == {"redirect": True, "url": redirect_url}

    def test_cannot_book_for_full_course(self):
        pass

    def test_cannot_book_for_cancelled_course(self):
        self.course.cancelled = True
        self.course.save()


class WaitinglistToggleAjaxViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def test_user_added_to_waiting_list(self):
        pass

    def test_user_removed_from_waiting_list(self):
        pass

    def test_view_as_user_added_waiting_list(self):
        # if viewing as a different user, the view as user is the one added to the waiting list
        pass


class AjaxBlockDeleteView(TestUsersMixin, TestCase):
    pass


class AjaxBlockPurchase(TestUsersMixin, TestCase):
    pass
