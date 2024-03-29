# -*- coding: utf-8 -*-
from datetime import timedelta
from decimal import Decimal
from model_bakery import baker
import pytest

from django.conf import settings
from django.core import mail
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from accounts.models import OnlineDisclaimer, has_active_disclaimer

from booking.models import Booking, Block, Course, EventType, WaitingListUser, BlockConfig, GiftVoucher, Track
from common.test_utils import TestUsersMixin, EventTestMixin


pytestmark = pytest.mark.django_db


class BookingToggleAjaxViewTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def setUp(self):
        super().setUp()
        self.create_users()
        self.create_events_and_course()
        self.make_data_privacy_agreement(self.student_user)
        self.make_data_privacy_agreement(self.manager_user)
        self.make_disclaimer(self.student_user)
        self.login(self.student_user)

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
        baker.make(Block, block_config__event_type=self.aerial_event_type, user=self.child_user, paid=True)
        resp = self.client.post(self.url(self.aerial_events[0].id), data={"user_id": self.child_user.id})
        assert resp.status_code == 200
        assert Booking.objects.filter(event=self.aerial_events[0], user=self.child_user).exists()

    def test_create_booking_no_available_block(self):
        """
        Test creating a booking with no block available redirects to page it came from
        """
        assert Booking.objects.exists() is False
        ref_urls = {
            "bookings": reverse("booking:bookings"),
            "events": reverse("booking:events", args=(self.aerial_event_type.track.slug,)),
        }
        for ref, redirect_url in ref_urls.items():
            resp = self.client.post(
                self.url(self.aerial_events[0].id), 
                data={"user_id": self.student_user.id, "ref": ref}
            )
            assert resp.status_code == 200
            assert resp.json() == {"redirect": True, "url": redirect_url + "?page=1"}

    def test_create_course_booking_no_available_block(self):
        """
        Test creating a booking
        """
        assert Booking.objects.exists() is False
        ref_urls = {
            "bookings": reverse("booking:bookings"),
            "events": reverse("booking:events", args=(self.aerial_event_type.track.slug,)),
            "course": reverse("booking:course_events", args=(self.course.slug,)),
        }
        for ref, redirect_url in ref_urls.items():
            resp = self.client.post(
                self.url(self.course_event.id), 
                data={"user_id": self.student_user.id, "ref": ref, "page": "1"}
            )
            assert resp.status_code == 200
            assert resp.json() == {"redirect": True, "url": redirect_url + "?page=1"}

    def test_create_course_booking_with_available_block(self):
        """
        Test creating a booking
        """
        ref_urls = {
            "events": reverse("booking:events", args=(self.aerial_event_type.track.slug,)),
            "course": reverse("booking:course_events", args=(self.course.slug,)),
        }
        assert Booking.objects.exists() is False
        block = baker.make(
            Block, user=self.student_user, block_config__event_type=self.aerial_event_type,
            block_config__course=True, block_config__size=self.course.number_of_events,
            paid=True
        )
        assert block.valid_for_course(self.course_event.course)
        for ref, redirect_url in ref_urls.items():
            resp = self.client.post(
                self.url(self.course_event.id), 
                data={"user_id": self.student_user.id, "ref": ref}
            )
            assert resp.status_code == 200
            assert resp.json() == {"redirect": True, "url": redirect_url + "?page=1"}

    def test_create_booking(self):
        """
        Test creating a booking
        """
        # block not paid, can't be used
        block = baker.make(Block, block_config__event_type=self.aerial_event_type, user=self.student_user)
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
            Block, block_config__event_type=self.floor_event_type, user=self.student_user, paid=True
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
            Block, block_config__event_type=self.floor_event_type, user=self.student_user, paid=True
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
            Block, block_config__event_type=self.floor_event_type, user=self.student_user, paid=True
        )
        resp = self.client.post(self.url(event.id), data={"user_id": self.student_user.id})

        # no new bookings made
        assert event.bookings.count() == 0
        assert resp.status_code == 400
        assert resp.content.decode("utf-8") == "Sorry, this event has been cancelled"

    def test_book_for_full_course_event(self):
        for event in self.course.uncancelled_events:
            baker.make(Booking, event=event, _quantity=self.course.max_participants)
        assert self.course.full
        bookings_count = self.course_event.bookings.count()

        # user has available block
        baker.make_recipe(
            "booking.course_block",
            block_config__event_type=self.course.event_type,
            block_config__course=True,
            user=self.student_user, paid=True
        )
        resp = self.client.post(self.url(self.course_event.id), data={"user_id": self.student_user.id})

        # no new bookings made
        assert self.course_event.bookings.count() == bookings_count
        assert resp.status_code == 400
        assert resp.content.decode("utf-8") == "Sorry, this event is now full"

        # user has cancelled booking
        booking = baker.make(Booking, event=self.course_event, status="CANCELLED", user=self.student_user)
        assert self.course_event.bookings.count() == bookings_count + 1
        assert self.course_event.spaces_left == 0
        resp = self.client.post(self.url(self.course_event.id),
                                data={"user_id": self.student_user.id})

        # no new bookings made
        assert self.course_event.bookings.count() == bookings_count + 1
        assert resp.status_code == 400
        assert resp.content.decode("utf-8") == "Sorry, this event is now full"

        # user has no-show booking
        booking.status = "OPEN"
        booking.no_show = True
        booking.save()
        assert self.course_event.bookings.count() == bookings_count + 1

        resp = self.client.post(self.url(self.course_event.id), data={"user_id": self.student_user.id})
        assert resp.status_code == 200
        booking.refresh_from_db()
        assert booking.status == "OPEN"
        assert booking.no_show is False

    def test_rebook_cancelled_booking(self):
        # user has available block
        block = baker.make(
            Block, block_config__event_type=self.aerial_event_type, user=self.student_user, paid=True
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
            Block, block_config__event_type=self.aerial_event_type, user=self.student_user, paid=True
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
            Block, block_config__event_type=self.aerial_event_type, user=self.student_user, paid=True
        )
        booking = baker.make(
            Booking, user=self.student_user, event=self.aerial_events[0], status="OPEN", no_show=True,
            block=block
        )
        resp = self.client.post(
            self.url(self.aerial_events[0].id), 
            data={"user_id": self.student_user.id, "ref": "bookings"}
        )
        booking.refresh_from_db()
        assert booking.status == "OPEN"
        assert booking.no_show is False
        # block is not removed from no-show
        assert booking.block == block
        assert resp.context['alert_message']['message'] ==  'Booking has been reopened'
        assert resp.context['button_info']['button'] == "toggle_booking"
        assert resp.context['button_info']['toggle_option'] == "cancel"
        # email to student only
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["student@test.com"]

    def test_create_booking_user_on_waiting_list(self):
        # user has available block
        baker.make(
            Block, block_config__event_type=self.aerial_event_type, user=self.student_user, paid=True
        )
        baker.make(WaitingListUser, user=self.student_user, event=self.aerial_events[0])
        assert WaitingListUser.objects.filter(user=self.student_user, event=self.aerial_events[0]).exists() is True
        resp = self.client.post(self.url(self.aerial_events[0].id), data={"user_id": self.student_user.id, "ref": "course"})
        assert Booking.objects.count() == 1
        assert resp.context['alert_message']['message'] ==  'Booking has been opened'
        assert resp.context['button_info']['buttons'] == ["toggle_booking"]
        # user removed from waiting list
        assert WaitingListUser.objects.filter(user=self.student_user, event=self.aerial_events[0]).exists() is False

        # email to student only
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["student@test.com"]

    def test_cancel_booking_from_full_event_emails_waiting_list(self):
        event = baker.make_recipe("booking.future_event", event_type=self.floor_event_type, max_participants=2)
        # user has available block and booking
        baker.make(
            Block, block_config__event_type=self.floor_event_type, user=self.student_user, paid=True
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

    def test_cancel_booking_made_with_full_block (self):
        event = baker.make_recipe("booking.future_event", event_type=self.floor_event_type, max_participants=2)
        # make (full) block and booking
        block = baker.make(
            Block, 
            block_config__event_type=self.floor_event_type, block_config__size=1,
            user=self.student_user, paid=True
        )
        booking = baker.make(Booking, user=self.student_user, event=event, block=block)
        assert block.full

        # cancel booking
        resp = self.client.post(self.url(event.id), data={"user_id": self.student_user.id})
        assert resp.json()["redirect"]
        booking.refresh_from_db()
        block.refresh_from_db()
        assert booking.status == "CANCELLED"
        assert booking.block is None
        assert not block.full

    def test_make_booking_that_completes_block (self):
        event = baker.make_recipe("booking.future_event", event_type=self.floor_event_type, max_participants=2)
        # make block and booking
        block = baker.make(
            Block, 
            block_config__event_type=self.floor_event_type, block_config__size=1,
            user=self.student_user, paid=True
        )
        assert not block.full

        # make booking
        resp = self.client.post(
            self.url(event.id), data={"user_id": self.student_user.id, "ref": "bookings"}
        ).json()
        assert resp["redirect"]
        assert reverse("booking:bookings") in resp["url"]
        block.refresh_from_db()
        assert block.full
        assert block.bookings.first().user == self.student_user
        assert block.bookings.first().event == event

    def test_cancel_booking_for_full_event_sends_waiting_list_emails_to_managed_user_email(self):
        event = baker.make_recipe("booking.future_event", event_type=self.floor_event_type, max_participants=2)
        # user has available block and booking
        baker.make(
            Block, block_config__event_type=self.floor_event_type, user=self.student_user, paid=True
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
            Block, block_config__event_type=self.floor_event_type, user=self.student_user, paid=True
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
            Block, block_config__event_type=self.floor_event_type, user=self.student_user, paid=True
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
        # user has available course block and booking
        block = baker.make(
            Block,
            block_config__event_type=self.aerial_event_type,
            block_config__course=True,
            user=self.student_user,
            paid=True
        )
        booking = baker.make(Booking, user=self.student_user, event=course_event, block=block)
        # cancel booking, set to no-show
        self.client.post(self.url(course_event.id), data={"user_id": self.student_user.id})
        booking.refresh_from_db()
        assert booking.status == "OPEN"
        assert booking.block == block
        assert booking.no_show is True

    def test_cancel_dropin_booking_from_course(self):
        # always set to no show, keep block
        self.course.allow_drop_in = True
        self.course.save()
        course_event = baker.make_recipe(
            "booking.future_event", event_type=self.aerial_event_type, course=self.course,
            start=timezone.now() + timedelta(hours=48)
        )
        # user has available dropin block and booking
        block = baker.make(
            Block,
            block_config__event_type=self.aerial_event_type,
            block_config__course=False,
            user=self.student_user,
            paid=True
        )
        booking = baker.make(Booking, user=self.student_user, event=course_event, block=block)
        # cancel booking, it was made with a drop in block, so set to cancelled
        self.client.post(self.url(course_event.id), data={"user_id": self.student_user.id})
        booking.refresh_from_db()
        assert booking.status == "CANCELLED"
        assert booking.block is None
        assert booking.no_show is False


class BookingAjaxCourseBookingViewTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def setUp(self):
        super().setUp()
        self.create_users()
        self.create_events_and_course()
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
        redirect_url = reverse('booking:course_events', args=(self.course.slug,))
        assert redirect_url in resp['url']

    def test_book_course(self):
        # booking a course books for all events on the course
        # make usable block
        block = baker.make(
            Block, user=self.student_user, block_config__event_type=self.aerial_event_type,
            block_config__course=True, block_config__size=self.course.number_of_events,
            paid=True
        )
        assert self.course.is_configured()
        resp = self.client.post(self.url(self.course.id), data={"user_id": self.student_user.id})
        assert resp.status_code == 200
        resp = resp.json()
        assert resp['redirect'] is True
        redirect_url = reverse('booking:course_events', args=(self.course.slug,))
        assert redirect_url in resp['url']

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
            Block, user=self.child_user,
            block_config__event_type=self.aerial_event_type, block_config__course=True, paid=True,
            block_config__size=self.course.number_of_events
        )
        resp = self.client.post(self.url(self.course.id), data={"user_id": self.child_user.id})
        assert resp.status_code == 200
        resp = resp.json()
        assert resp['redirect'] is True
        redirect_url = reverse('booking:course_events', args=(self.course.slug,))
        assert redirect_url in resp['url']

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
            Block, user=self.child_user, block_config__event_type=self.aerial_event_type, block_config__course=True, paid=True
        )
        resp = self.client.post(self.url(self.course.id), data={"user_id": self.child_user.id})
        # redirects to the disclaimer page for the child user, even though manager user has no disclaimer
        redirect_url = reverse('booking:disclaimer_required', args=(self.child_user.id,))
        assert resp.json() == {"redirect": True, "url": redirect_url}

    def test_book_course_from_courselist(self):
        # booking a course books for all events on the course
        # make usable block
        block = baker.make(
            Block, user=self.student_user, block_config__event_type=self.aerial_event_type,
            block_config__course=True, block_config__size=self.course.number_of_events,
            paid=True
        )
        assert self.course.is_configured()
        resp = self.client.post(self.url(self.course.id), data={"user_id": self.student_user.id, "ref": "course_list"})
        resp = resp.json()
        assert resp['redirect'] is True
        redirect_url = reverse('booking:courses', args=(self.course.event_type.track.slug,)) + "?page=1"
        assert redirect_url in resp['url']

        for event in self.course_events:
            assert event.bookings.filter(user=self.student_user, status="OPEN", block=block).exists()

    def test_cannot_book_for_full_course(self):
        # make usable block
        baker.make(
            Block, user=self.student_user, block_config__event_type=self.aerial_event_type,
            block_config__course=True, block_config__size=self.course.number_of_events,
            paid=True
        )
        assert self.course.is_configured()
        for event in self.course.events.all():
            baker.make(Booking, event=event, _quantity=self.course.max_participants)
        assert self.course.full
        resp = self.client.post(self.url(self.course.id), data={"user_id": self.student_user.id})
        assert resp.status_code == 400

    def test_cannot_book_for_cancelled_course(self):
        # make usable block
        baker.make(
            Block, user=self.student_user, block_config__event_type=self.aerial_event_type,
            block_config__course=True, block_config__size=self.course.number_of_events,
            paid=True
        )
        self.course.cancelled = True
        self.course.save()
        resp = self.client.post(self.url(self.course.id), data={"user_id": self.student_user.id})
        assert resp.status_code == 400

    def test_book_course_removed_unpaid_dropin_blocks(self):
        # make usable block
        course_block = baker.make(
            Block, user=self.student_user, block_config__event_type=self.aerial_event_type,
            block_config__course=True, block_config__size=self.course.number_of_events,
            paid=True
        )
        # make drop in block
        unpaid_dropin_block = baker.make(
            Block, user=self.student_user, block_config__event_type=self.aerial_event_type,
            block_config__course=False, block_config__size=1, paid=False
        )
        unpaid_dropin_block_id = unpaid_dropin_block.id
        # make an in-cart booking 
        booking = baker.make(
            Booking, user=self.student_user, block=unpaid_dropin_block, event=self.course_event
        )
        assert booking.is_in_basket()

        self.client.post(
            self.url(self.course.id),
            data={"user_id": self.student_user.id, "ref": "events"}
        )
        
        assert list(course_block.bookings.values_list("event_id", flat=True)) == \
            list(self.course.uncancelled_events.values_list("id", flat=True))
        booking.refresh_from_db()
        assert booking.block == course_block
        assert not Block.objects.filter(id=unpaid_dropin_block_id).exists()


class WaitinglistToggleAjaxViewTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def setUp(self):
        self.create_users()
        self.create_events_and_course()
        self.make_data_privacy_agreement(self.student_user)
        self.make_disclaimer(self.student_user)
        self.make_data_privacy_agreement(self.manager_user)
        self.event = self.aerial_events[0]
        self.url = reverse("booking:toggle_waiting_list", args=(self.event.id,))
        self.login(self.student_user)

    def test_toggle_waiting_list(self):
        self.client.post(self.url, data={"user_id": self.student_user.id})
        assert WaitingListUser.objects.filter(user=self.student_user, event=self.event).exists()

        self.client.post(self.url, data={"user_id": self.student_user.id})
        assert WaitingListUser.objects.filter(user=self.student_user, event=self.event).exists() is False

    def test_view_as_user_added_waiting_list(self):
        # if viewing as a different user, the view as user is the one added to the waiting list
        self.login(self.manager_user)
        self.client.post(self.url, data={"user_id": self.child_user.id})
        assert WaitingListUser.objects.filter(user=self.child_user, event=self.event).exists()

        self.client.post(self.url, data={"user_id": self.child_user.id})
        assert WaitingListUser.objects.filter(user=self.child_user, event=self.event).exists() is False


class AjaxCartItemDeleteView(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.login(self.student_user)

    def test_delete_block(self):
        block = baker.make_recipe("booking.dropin_block", user=self.student_user)
        url = reverse("booking:ajax_cart_item_delete")
        resp = self.client.post(url, {"item_type": "block", "item_id": block.id}).json()
        assert Block.objects.exists() is False
        assert resp["cart_total"] == 0
        assert resp["cart_item_menu_count"] == 0

    def test_delete_block_with_item_count_voucher(self):
        block = baker.make_recipe(
            "booking.dropin_block",
            user=self.student_user,
            voucher__item_count=2,
            voucher__discount=10
        )
        url = reverse("booking:ajax_cart_item_delete")
        resp = self.client.post(url, {"item_type": "block", "item_id": block.id}).json()
        assert Block.objects.exists() is False
        assert resp["redirect"] is True
        assert resp["url"] == reverse("booking:shopping_basket")

    def test_recalculate_total_cart_items(self):
        # calculate total for all manager users blocks
        # the block to delete
        self.login(self.manager_user)
        block = baker.make_recipe(
            "booking.dropin_block", block_config__cost=10, user=self.child_user
        )
        # some other blocks for manager and managed user
        baker.make_recipe(
            "booking.dropin_block", block_config__cost=1, user=self.child_user
        )
        baker.make_recipe(
            "booking.dropin_block", block_config__cost=2, user=self.manager_user
        )
        baker.make_recipe(
            "booking.dropin_block", block_config__cost=3, user=self.manager_user
        )
        # paid blocks don't count towards total
        baker.make_recipe(
            "booking.dropin_block", block_config__cost=100, user=self.manager_user,
            paid=True
        )
        baker.make_recipe(
            "booking.dropin_block", block_config__cost=200, user=self.child_user,
            paid=True
        )

        url = reverse("booking:ajax_cart_item_delete")
        resp = self.client.post(url, {"item_type": "block", "item_id": block.id}).json()
        assert Block.objects.filter(id=block.id).exists() is False
        # 3 blocks still in cart (2 for manager, 1 for child) - not the deleted one or the paid ones
        # cost
        assert resp["cart_total"] == "6.00"
        assert resp["cart_item_menu_count"] == 3

    def test_delete_course_block(self):
        block = baker.make_recipe("booking.course_block", user=self.student_user)
        url = reverse("booking:ajax_cart_item_delete")
        resp = self.client.post(url, {"item_type": "block", "item_id": block.id}).json()
        assert Block.objects.exists() is False
        assert resp["cart_total"] == 0
        assert resp["cart_item_menu_count"] == 0

    def test_delete_gift_voucher(self):
        gift_voucher = baker.make_recipe(
            "booking.gift_voucher_10",
            total_voucher__purchaser_email="anon@test.com",
        )
        url = reverse("booking:ajax_cart_item_delete")
        resp = self.client.post(url, {"item_type": "gift_voucher", "item_id": gift_voucher.id}).json()
        assert GiftVoucher.objects.exists() is False
        assert resp["cart_total"] == 0
        assert resp["cart_item_menu_count"] == 0

    def test_delete_gift_voucher_anonymous_user(self):
        self.client.logout()
        gift_voucher = baker.make_recipe(
            "booking.gift_voucher_10",
            total_voucher__purchaser_email="anon@test.com",
        )
        session = self.client.session
        session.update({"purchases": {"gift_vouchers": [gift_voucher.id]}})
        session.save()

        url = reverse("booking:ajax_cart_item_delete")
        resp = self.client.post(url, {"item_type": "gift_voucher", "item_id": gift_voucher.id}).json()
        assert GiftVoucher.objects.exists() is False
        assert resp["cart_total"] == 0
        assert resp["cart_item_menu_count"] == 0

        # cart items in context have been updated also
        resp = self.client.get(reverse("booking:guest_shopping_basket"))
        assert resp.context_data["unpaid_gift_voucher_info"] == []


class AjaxBlockPurchaseTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.dropin_config = baker.make(BlockConfig, cost=20)
        self.course_config = baker.make(BlockConfig, course=True, cost=20)
        self.login(self.student_user)

    def test_add_new_dropin_block(self):
        # create block, set to unpaid
        assert Block.objects.exists() is False
        url = reverse("booking:ajax_block_purchase", args=(self.dropin_config.id,))
        resp = self.client.post(url, data={"user_id": self.student_user.id})
        assert Block.objects.exists()
        new_block = Block.objects.first()
        assert new_block.user == self.student_user
        assert new_block.block_config == self.dropin_config
        assert new_block.paid is False
        resp_json = resp.json()
        assert resp_json["cart_item_menu_count"] == 1
        assert "Add" in resp_json["html"]
        assert "(1)" in resp_json["html"]
        assert f"Block added to cart for {self.student_user.first_name} {self.student_user.last_name}" in resp_json["html"]

    def test_add_new_course_block(self):
        # create block, set to unpaid
        assert Block.objects.exists() is False
        url = reverse("booking:ajax_block_purchase", args=(self.course_config.id,))
        resp = self.client.post(url, data={"user_id": self.student_user.id})
        assert Block.objects.exists()
        new_block = Block.objects.first()
        assert new_block.user == self.student_user
        assert new_block.block_config == self.course_config
        assert new_block.paid is False
        resp_json = resp.json()
        assert resp_json["cart_item_menu_count"] == 1
        assert "Add" in resp_json["html"]
        assert "(1)" in resp_json["html"]
        assert f"Block added to cart for {self.student_user.first_name} {self.student_user.last_name}" in resp_json["html"]

    def test_add_block_for_managed_user(self):
        self.login(self.manager_user)
        # manager has another unpaid block already
        baker.make_recipe("booking.course_block", user=self.manager_user)
        url = reverse("booking:ajax_block_purchase", args=(self.dropin_config.id,))
        resp = self.client.post(url, data={"user_id": self.child_user.id})
        new_block = Block.objects.latest("id")
        assert new_block.user == self.child_user
        assert new_block.block_config == self.dropin_config
        assert new_block.paid is False
        resp_json = resp.json()
        assert resp_json["cart_item_menu_count"] == 2
        assert "Add" in resp_json["html"]
        assert "(1)" in resp_json["html"]
        assert f"Block added to cart for {self.child_user.first_name} {self.child_user.last_name}" in resp_json[
            "html"]

    def test_add_multiple_from_cart(self):
        self.login(self.manager_user)
        # user has multiple unpaid blocks
        course_block = baker.make_recipe("booking.course_block", block_config=self.course_config, user=self.manager_user)
        dropin_block1 = baker.make_recipe("booking.dropin_block", block_config=self.dropin_config, user=self.child_user)

        assert self.manager_user.blocks.count() == 1
        url = reverse("booking:ajax_block_purchase", args=(self.dropin_config.id,))
        resp = self.client.post(url, data={"user_id": self.manager_user.id})
        assert self.manager_user.blocks.count() == 2
        assert self.manager_user.blocks.exclude(id=course_block.id).first().block_config == self.dropin_config

        # chile user still has the same 1 block
        assert [block.id for block in self.child_user.blocks.all()] == [dropin_block1.id]
        assert self.child_user.blocks.count() == 1
        resp = self.client.post(url, data={"user_id": self.child_user.id})
        assert self.child_user.blocks.count() == 2
        for block in self.child_user.blocks.all():
            assert block.block_config == self.dropin_config

        resp_json = resp.json()
        assert resp_json["cart_item_menu_count"] == 4


# ajax_add_booking_to_basket tests

def test_ajax_add_booking_to_basket(client, student_user):
    client.force_login(student_user)
    event = baker.make_recipe("booking.future_event")
    dropin_cart_config = baker.make(
        BlockConfig, active=True, course=False, size=1, event_type=event.event_type
    )
    assert not Block.objects.exists()
    assert not Booking.objects.exists()
    data = {"user_id": student_user.id, "event_id": event.id, "ref": "events"}
    resp = client.post(reverse("booking:ajax_add_booking_to_basket"), data).json()
    assert Booking.objects.count() == Block.objects.count() == 1
    booking = Booking.objects.first()
    assert booking.is_in_basket()
    assert booking.user == student_user
    assert resp["cart_item_menu_count"] == 1


def test_ajax_add_single_course_booking_to_basket_for_another_user(client, manager_user, child_user):
    client.force_login(manager_user)
    event = baker.make_recipe("booking.future_event")
    course = baker.make(Course, event_type=event.event_type, number_of_events=2, allow_drop_in=True)
    event.course = course
    event.save()
    dropin_cart_config = baker.make(
        BlockConfig, active=True, course=False, size=1, event_type=event.event_type
    )
    assert not Block.objects.exists()
    assert not Booking.objects.exists()
    data = {"user_id": child_user.id, "event_id": event.id, "ref": "course"}
    resp = client.post(reverse("booking:ajax_add_booking_to_basket"), data).json()

    assert Booking.objects.count() == Block.objects.count() == 1
    booking = Booking.objects.first()
    assert booking.is_in_basket()
    assert booking.user == child_user
    assert resp["cart_item_menu_count"] == 1


def test_ajax_add_booking_to_basket_disclaimer_required(client, student_user):
    student_user.online_disclaimer.all().delete()
    client.force_login(student_user)
    event = baker.make_recipe("booking.future_event")
    data = {"user_id": student_user.id, "event_id": event.id, "ref": "events"}
    resp = client.post(reverse("booking:ajax_add_booking_to_basket"), data).json()
    assert resp["redirect"]
    assert resp["url"] == reverse('booking:disclaimer_required', args=(student_user.id,))


def test_ajax_add_booking_to_basket_full_event(client, student_user):
    client.force_login(student_user)
    event = baker.make_recipe("booking.future_event", max_participants=1)
    baker.make(Booking, event=event)
    data = {"user_id": student_user.id, "event_id": event.id, "ref": "events"}
    resp = client.post(reverse("booking:ajax_add_booking_to_basket"), data)
    assert resp.status_code == 400
    assert "full" in resp.content.decode()


def test_ajax_add_booking_to_basket_cancelled_event(client, student_user):
    client.force_login(student_user)
    event = baker.make_recipe("booking.future_event", max_participants=1, cancelled=True)
    data = {"user_id": student_user.id, "event_id": event.id, "ref": "events"}
    resp = client.post(reverse("booking:ajax_add_booking_to_basket"), data)
    assert resp.status_code == 400
    assert "cancelled" in resp.content.decode()


def test_ajax_add_booking_to_basket_already_in_basket(client, student_user):
    client.force_login(student_user)
    event = baker.make_recipe("booking.future_event", max_participants=1)
    booking = baker.make(Booking, user=student_user, event=event, block__paid=False)
    data = {"user_id": student_user.id, "event_id": event.id, "ref": "events"}
    resp = client.post(reverse("booking:ajax_add_booking_to_basket"), data)
    assert resp.status_code == 400
    assert "Already added to cart" in resp.content.decode()

    # without block
    booking.block = None
    booking.save()
    resp = client.post(reverse("booking:ajax_add_booking_to_basket"), data)
    assert resp.status_code == 400
    assert "Open booking already exists" in resp.content.decode()


def test_ajax_add_booking_to_basket_no_show_course_booking(client, student_user):
    client.force_login(student_user)
    event = baker.make_recipe("booking.future_event", max_participants=1)
    baker.make(Booking, user=student_user, event=event, block__paid=False, no_show=True)
    course = baker.make(Course, event_type=event.event_type, number_of_events=2, allow_drop_in=True)
    event.course = course
    event.save()
    data = {"user_id": student_user.id, "event_id": event.id, "ref": "events"}
    resp = client.post(reverse("booking:ajax_add_booking_to_basket"), data)
    assert resp.status_code == 400
    assert "Booking can be reopened" in resp.content.decode()


# ajax_add_course_booking_to_basket tests

def test_ajax_add_course_booking_to_basket(client, student_user, drop_in_course):
    client.force_login(student_user)
    url = reverse("booking:ajax_add_course_booking_to_basket")
    assert not Block.objects.exists()
    assert not Booking.objects.exists()
    data = {"user_id": student_user.id, "course_id": drop_in_course.id, "ref": "events"}
    resp = client.post(url, data).json()
    assert resp["redirect"]
    assert reverse("booking:events", args=(drop_in_course.event_type.track.slug,)) in resp["url"]
    
    assert Block.objects.count() == 1
    block = Block.objects.first()
    assert block.user == student_user
    assert not block.paid 
    assert block.block_config.course
    assert Booking.objects.count() == 2
    for booking in Booking.objects.all():
        assert booking.user == student_user


def test_ajax_add_course_booking_to_basket_from_courses(client, student_user, drop_in_course):
    client.force_login(student_user)
    url = reverse("booking:ajax_add_course_booking_to_basket")
    data = {"user_id": student_user.id, "course_id": drop_in_course.id, "ref": "course_list"}
    resp = client.post(url, data).json()
    assert resp["redirect"]
    assert reverse("booking:courses", args=(drop_in_course.event_type.track.slug,)) in resp["url"]


def test_ajax_add_course_booking_to_basket_from_course_events(client, student_user, drop_in_course):
    client.force_login(student_user)
    url = reverse("booking:ajax_add_course_booking_to_basket")
    data = {"user_id": student_user.id, "course_id": drop_in_course.id, "ref": "course"}
    resp = client.post(url, data).json()
    assert resp["redirect"]
    assert reverse("booking:course_events", args=(drop_in_course.slug,)) in resp["url"]


def test_ajax_add_course_booking_to_basket_disclaimer_required(client, student_user, drop_in_course):
    student_user.online_disclaimer.all().delete()
    client.force_login(student_user)
    url = reverse("booking:ajax_add_course_booking_to_basket")
    data = {"user_id": student_user.id, "course_id": drop_in_course.id, "ref": "events"}
    resp = client.post(url, data).json()
    assert resp["redirect"]
    assert resp["url"] == reverse('booking:disclaimer_required', args=(student_user.id,))


def test_ajax_add_course_booking_to_basket_full_course(client, student_user, drop_in_course):
    client.force_login(student_user)
    for event in drop_in_course.events.all():
        baker.make(Booking, event=event, _quantity=2)
    assert drop_in_course.full
    url = reverse("booking:ajax_add_course_booking_to_basket")
    data = {"user_id": student_user.id, "course_id": drop_in_course.id, "ref": "events"}
    resp = client.post(url, data)
    assert resp.status_code == 400
    assert "full" in resp.content.decode()


def test_ajax_add_course_booking_to_basket_cancelled_course(client, student_user, drop_in_course):
    client.force_login(student_user)
    drop_in_course.cancelled = True
    drop_in_course.save()
    url = reverse("booking:ajax_add_course_booking_to_basket")
    data = {"user_id": student_user.id, "course_id": drop_in_course.id, "ref": "events"}
    resp = client.post(url, data)
    assert resp.status_code == 400
    assert "cancelled" in resp.content.decode()


def test_ajax_add_course_booking_to_basket_already_booked(client, student_user, drop_in_course):
    client.force_login(student_user)
    for event in drop_in_course.events.all():
        baker.make(
            Booking, event=event, user=student_user, block__block_config__course=True,
            block__paid=True
        )
    url = reverse("booking:ajax_add_course_booking_to_basket")
    data = {"user_id": student_user.id, "course_id": drop_in_course.id, "ref": "events"}
    resp = client.post(url, data)
    assert resp.status_code == 400
    assert "Course booking already exists" in resp.content.decode()


def test_ajax_add_course_booking_to_basket_already_booked_course_full(client, student_user, drop_in_course):
    client.force_login(student_user)
    for event in drop_in_course.events.all():
        baker.make(
            Booking, event=event, user=student_user, block__block_config__course=True,
            block__paid=True
        )
        baker.make( Booking, event=event)
    drop_in_course.refresh_from_db()
    assert drop_in_course.full
    url = reverse("booking:ajax_add_course_booking_to_basket")
    data = {"user_id": student_user.id, "course_id": drop_in_course.id, "ref": "events"}
    resp = client.post(url, data)
    assert resp.status_code == 400
    assert "Course booking already exists" in resp.content.decode()


def test_ajax_add_course_booking_to_basket_already_in_basket(client, student_user, drop_in_course):
    client.force_login(student_user)
    for event in drop_in_course.events.all():
        baker.make(
            Booking, event=event, user=student_user, block__block_config__course=True,
            block__paid=False
        )
    url = reverse("booking:ajax_add_course_booking_to_basket")
    data = {"user_id": student_user.id, "course_id": drop_in_course.id, "ref": "events"}
    resp = client.post(url, data)
    assert resp.status_code == 400
    assert "Already added to cart" in resp.content.decode()


def test_ajax_add_course_booking_to_basket_for_another_user(client, manager_user, child_user, drop_in_course):
    client.force_login(manager_user)
    url = reverse("booking:ajax_add_course_booking_to_basket")
    assert not Block.objects.exists()
    assert not Booking.objects.exists()
    data = {"user_id": child_user.id, "course_id": drop_in_course.id, "ref": "events"}
    resp = client.post(url, data)
  
    assert Block.objects.count() == 1
    block = Block.objects.first()
    assert block.user == child_user
    assert not block.paid 
    assert block.block_config.course
    assert Booking.objects.count() == 2
    for booking in Booking.objects.all():
        assert booking.user == child_user


def test_ajax_add_course_booking_to_basket_deletes_drop_in_unpaid_blocks(client, student_user, drop_in_course):
    client.force_login(student_user)
    url = reverse("booking:ajax_add_course_booking_to_basket")
    
    # make a dropin cart booking
    event = drop_in_course.events.first()
    block = baker.make(Block, user=student_user, paid=False, block_config__size=1)
    booking = baker.make(Booking, event=event, user=student_user, block=block)
    
    block_id = block.id

    data = {"user_id": student_user.id, "course_id": drop_in_course.id, "ref": "events"}
    client.post(url, data)
    
    # old block has been deleted
    assert Block.objects.count() == 1
    new_block = Block.objects.first()
    assert new_block.id != block_id
    assert new_block.block_config.course

    assert Booking.objects.count() == 2
    for booking in Booking.objects.all():
        assert booking.user == student_user 
        assert booking.block == new_block
    assert booking in new_block.bookings.all()


def test_ajax_add_course_booking_to_basket_does_not_deletes_paid_blocks(client, student_user, drop_in_course):
    client.force_login(student_user)
    url = reverse("booking:ajax_add_course_booking_to_basket")
    
    # make a paid dropin booking
    event = drop_in_course.events.first()
    block = baker.make(Block, user=student_user, paid=True, block_config__size=1)
    booking = baker.make(Booking, event=event, user=student_user, block=block)
    
    data = {"user_id": student_user.id, "course_id": drop_in_course.id, "ref": "events"}
    client.post(url, data)
    
    # old block has not been deleted
    assert Block.objects.count() == 2
    new_block = Block.objects.latest('id')
    assert new_block.block_config.course

    assert Booking.objects.count() == 2
    for booking in Booking.objects.all():
        assert booking.user == student_user 
        assert booking.block == new_block
    assert booking in new_block.bookings.all()