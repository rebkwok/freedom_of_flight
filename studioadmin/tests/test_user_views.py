from datetime import timedelta

from model_bakery import baker

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from booking.models import Booking, Block, BlockConfig, Course, Event, WaitingListUser, Subscription
from accounts.models import has_active_disclaimer
from common.test_utils import EventTestMixin, TestUsersMixin, make_disclaimer_content


class EmailUsersViewsTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.create_events_and_course()
        self.event = self.aerial_events[0]
        self.event_url = reverse("studioadmin:email_event_users", args=(self.event.slug,))
        self.course_url = reverse("studioadmin:email_course_users", args=(self.course.slug,))
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def test_staff_only(self):
        self.user_access_test(["staff"], self.event_url)
        self.user_access_test(["staff"], self.course_url)

    def test_email_event_users_open_and_cancelled_bookings(self):
        # shows users for open bookings checked, cancelled/no-show unchecked in form initial
        baker.make(Booking, event=self.event, user=self.student_user)
        baker.make(Booking, event=self.event, user=self.instructor_user, status="OPEN", no_show=True)
        baker.make(Booking, event=self.event, user=self.student_user1, status="CANCELLED")
        resp = self.client.get(self.event_url)
        form = resp.context_data["form"]
        assert form.fields["students"].initial == {self.student_user.id}
        choices_ids = [user[0] for user in form.fields["students"].choices]
        assert choices_ids[0] == self.student_user.id
        assert sorted(choices_ids[1:]) == sorted([self.instructor_user.id, self.student_user1.id])

    def test_email_event_users_reply_to_and_cc_options(self):
        baker.make(Booking, event=self.event, user=self.student_user)
        baker.make(Booking, event=self.event, user=self.instructor_user, status="OPEN", no_show=True)
        baker.make(Booking, event=self.event, user=self.student_user1, status="CANCELLED")
        self.client.post(
            self.event_url, {
                "students": [self.student_user.id, self.instructor_user.id],
                "reply_to_email": "test@test.com",
                "subject": "Test",
                "cc": True,
                "message": "Test"
            }
        )
        assert len(mail.outbox) == 1
        assert mail.outbox[0].cc == ["test@test.com"]
        assert sorted(mail.outbox[0].bcc) == sorted([self.student_user.email, self.instructor_user.email])
        assert mail.outbox[0].reply_to == "test@test.com"
        assert mail.outbox[0].subject == "Test"

    def test_select_at_least_one_user(self):
        baker.make(Booking, event=self.event, user=self.student_user)
        resp = self.client.post(
            self.event_url, {
                "students": [],
                "reply_to_email": "test@test.com",
                "subject": "Test",
                "cc": True,
                "message": "Test"
            }
        )
        assert resp.context_data["form"].errors == {
            "students": ["Select at least one student to email"]
        }

    def test_emails_go_to_manager_user(self):
        baker.make(Booking, event=self.event, user=self.child_user)
        self.client.post(
            self.event_url, {
                "students": [self.child_user.id],
                "reply_to_email": "test@test.com",
                "subject": "Test",
                "cc": True,
                "message": "Test"
            }
        )
        assert mail.outbox[0].bcc == [self.manager_user.email]

    def test_email_course_users_form_initial(self):
        # shows users with any bookings checked in form initial
        course_event1 = baker.make_recipe('booking.future_event', event_type=self.aerial_event_type, course=self.course)
        for event in [self.course_event, course_event1]:
            baker.make(Booking, event=event, user=self.student_user)
            baker.make(Booking, event=event, user=self.instructor_user, status="OPEN", no_show=True)
            baker.make(Booking, event=event, user=self.student_user1, status="CANCELLED")
        resp = self.client.get(self.course_url)
        form = resp.context_data["form"]
        assert sorted(form.fields["students"].initial) == sorted([self.student_user.id, self.instructor_user.id, self.student_user1.id])

    def test_email_course_users(self):
        baker.make(Booking, event=self.course_event, user=self.student_user)
        baker.make(Booking, event=self.course_event, user=self.instructor_user, status="OPEN", no_show=True)
        resp = self.client.post(
            self.course_url, {
                "students": [self.instructor_user.id],
                "reply_to_email": "test@test.com",
                "subject": "Test",
                "cc": True,
                "message": "Test"
            }
        )
        assert len(mail.outbox) == 1
        assert mail.outbox[0].cc == ["test@test.com"]
        assert mail.outbox[0].bcc == [self.instructor_user.email]
        assert mail.outbox[0].reply_to == "test@test.com"
        assert mail.outbox[0].subject == "Test"


class UserListViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.login(self.staff_user)
        self.url = reverse("studioadmin:users")

    def test_instructor_and_staff_can_access(self):
        self.user_access_test(["staff", "instructor"], self.url)

    def test_all_users_listed(self):
        resp = self.client.get(self.url)
        assert len(resp.context_data["users"]) == User.objects.count()

    def test_user_search(self):
        resp = self.client.get(self.url + "?search=manager&action=Search")
        assert resp.context_data["search_form"].initial == {"search": "manager"}
        assert len(resp.context_data["users"]) == 1

    def test_user_search_reset(self):
        resp = self.client.get(self.url + "?search=manager&action=Reset")
        assert resp.context_data["search_form"].initial == {"search": ""}
        assert len(resp.context_data["users"]) == User.objects.count()
        # any action except search resets
        resp = self.client.get(self.url + "?search=manager&action=foo")
        assert resp.context_data["search_form"].initial == {"search": ""}
        assert len(resp.context_data["users"]) == User.objects.count()


class UserDetailViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.login(self.staff_user)
        self.url = reverse("studioadmin:user_detail", args=(self.student_user.id,))
        cache.clear()

    def test_instructor_and_staff_can_access(self):
        self.user_access_test(["staff", "instructor"], self.url)

    def test_no_disclaimer(self):
        assert has_active_disclaimer(self.student_user) is False
        resp = self.client.get(self.url)
        assert resp.context_data["account_user"] == self.student_user
        assert resp.context_data["latest_disclaimer"] is None

    def test_with_active_disclaimer(self):
        disclaimer = self.make_disclaimer(self.student_user)
        resp = self.client.get(self.url)
        assert resp.context_data["latest_disclaimer"] == disclaimer

    def test_with_expired_disclaimer(self):
        disclaimer = self.make_disclaimer(self.student_user)
        make_disclaimer_content(version=None)
        assert has_active_disclaimer(self.student_user) is False
        resp = self.client.get(self.url)
        assert resp.context_data["latest_disclaimer"] == disclaimer

    def test_with_expired_and_active_disclaimer(self):
        self.make_disclaimer(self.student_user)
        make_disclaimer_content(version=None)
        assert has_active_disclaimer(self.student_user) is False
        active_disclaimer = self.make_disclaimer(self.student_user)
        assert has_active_disclaimer(self.student_user) is True

        resp = self.client.get(self.url)
        assert resp.context_data["latest_disclaimer"] == active_disclaimer


class UserBookingListViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.login(self.staff_user)
        self.url = reverse("studioadmin:user_bookings", args=(self.student_user.id,))

    def test_instructor_and_staff_can_access(self):
        self.user_access_test(["staff", "instructor"], self.url)

    def test_user_bookings(self):
        baker.make(Booking, user=self.student_user, _quantity=3)
        baker.make(Booking, user=self.student_user1, _quantity=3)
        resp = self.client.get(self.url)
        assert resp.context_data["account_user"] == self.student_user
        assert len(resp.context_data["bookings"]) == 3

    def test_user_bookings_for_past_events_not_shown(self):
        baker.make(Booking, user=self.student_user, _quantity=3)
        past_event = baker.make_recipe("booking.past_event")
        baker.make(Booking, event=past_event, user=self.student_user)
        resp = self.client.get(self.url)
        assert len(resp.context_data["bookings"]) == 3

    def test_shows_past_events_for_today(self):
        baker.make(Booking, user=self.student_user, _quantity=3)
        past_event = baker.make_recipe("booking.past_event", start=timezone.now() - timedelta(minutes=10))
        baker.make(Booking, event=past_event, user=self.student_user)
        resp = self.client.get(self.url)
        assert len(resp.context_data["bookings"]) == 4


class UserBookingHistoryListViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.login(self.staff_user)
        self.url = reverse("studioadmin:past_user_bookings", args=(self.student_user.id,))

    def test_instructor_and_staff_can_access(self):
        self.user_access_test(["staff", "instructor"], self.url)

    def test_user_bookings_for_past_events_only(self):
        baker.make(Booking, user=self.student_user, event__start=timezone.now() + timedelta(minutes=10), _quantity=3)
        past_event = baker.make_recipe("booking.past_event")
        baker.make(Booking, event=past_event, user=self.student_user)
        resp = self.client.get(self.url)
        assert len(resp.context_data["bookings"]) == 1

    def test_shows_past_events_for_today(self):
        # past events for today are shown on both history and active list
        baker.make(Booking, user=self.student_user, event__start=timezone.now() + timedelta(minutes=10), _quantity=3)
        past_event = baker.make_recipe("booking.past_event", event__start=timezone.now() - timedelta(minutes=10))
        baker.make(Booking, event=past_event, user=self.student_user)
        resp = self.client.get(self.url)
        assert len(resp.context_data["bookings"]) == 1


class UserBookingAddViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.event = baker.make_recipe("booking.future_event")
        self.login(self.staff_user)
        self.url = reverse("studioadmin:bookingadd", args=(self.student_user.id,))

    def test_instructor_and_staff_can_access(self):
        self.user_access_test(["staff", "instructor"], self.url)

    def test_get(self):
        resp = self.client.get(self.url)
        assert resp.context_data["booking_user"] == self.student_user

    def test_add_booking(self):
        assert self.student_user.bookings.exists() is False
        self.client.post(
            self.url,
            {"user": self.student_user.id, "event": self.event.id, "block": "", "status": "OPEN", "no_show": False}
        )
        assert self.student_user.bookings.count() == 1
        assert self.student_user.bookings.first().event == self.event

    def test_add_booking_with_block(self):
        assert self.student_user.bookings.exists() is False
        block = baker.make(Block, user=self.student_user, block_config__event_type=self.event.event_type, paid=True)
        self.client.post(
            self.url,
            {"user": self.student_user.id, "event": self.event.id, "block": block.id, "status": "OPEN", "no_show": False}
        )
        assert self.student_user.bookings.count() == 1
        booking = self.student_user.bookings.first()
        assert booking.event == self.event
        assert booking.block == block

    def test_add_booking_and_auto_assign_block(self):
        assert self.student_user.bookings.exists() is False
        block = baker.make(Block, user=self.student_user, block_config__event_type=self.event.event_type, paid=True)
        self.client.post(
            self.url,
            {
                "user": self.student_user.id, "event": self.event.id, "status": "OPEN", "no_show": False,
                "auto_assign_available_subscription_or_block": True
            }
        )
        assert self.student_user.bookings.count() == 1
        booking = self.student_user.bookings.first()
        assert booking.event == self.event
        assert booking.block == block

    def test_add_booking_and_auto_assign_subscription(self):
        assert self.student_user.bookings.exists() is False
        subscription = baker.make(
            Subscription, user=self.student_user, paid=True, config__start_options="first_booking_date",
            config__bookable_event_types={str(self.event.event_type.id): {"allowed_number": ""}}
        )
        self.client.post(
            self.url,
            {
                "user": self.student_user.id, "event": self.event.id, "status": "OPEN", "no_show": False,
                "auto_assign_available_subscription_or_block": True
            }
        )
        assert self.student_user.bookings.count() == 1
        booking = self.student_user.bookings.first()
        assert booking.event == self.event
        assert booking.subscription == subscription

    def test_add_booking_and_auto_assign_subscription_before_block(self):
        assert self.student_user.bookings.exists() is False
        block = baker.make(Block, user=self.student_user, block_config__event_type=self.event.event_type, paid=True)
        subscription = baker.make(
            Subscription, user=self.student_user, paid=True, config__start_options="first_booking_date",
            config__bookable_event_types={str(self.event.event_type.id): {"allowed_number": ""}}
        )
        self.client.post(
            self.url,
            {
                "user": self.student_user.id, "event": self.event.id, "status": "OPEN", "no_show": False,
                "auto_assign_available_subscription_or_block": True
            }
        )
        assert self.student_user.bookings.count() == 1
        booking = self.student_user.bookings.first()
        assert booking.event == self.event
        assert booking.subscription == subscription
        assert booking.block is None

    def test_add_booking_dont_auto_assign_invalid_block(self):
        assert self.student_user.bookings.exists() is False
        baker.make(Block, user=self.student_user, paid=True)
        self.client.post(
            self.url,
            {
                "user": self.student_user.id, "event": self.event.id, "status": "OPEN", "no_show": False,
                "auto_assign_available_subscription_or_block": True
            }
        )
        assert self.student_user.bookings.count() == 1
        assert self.student_user.bookings.first().block is None

    def test_add_booking_ignore_invalid_block_if_auto_assign_checked(self):
        assert self.student_user.bookings.exists() is False
        block = baker.make(Block, user=self.student_user, paid=True)
        self.client.post(
            self.url,
            {
                "user": self.student_user.id, "block": block.id, "event": self.event.id, "status": "OPEN", "no_show": False,
                "auto_assign_available_subscription_or_block": True
            }
        )
        assert self.student_user.bookings.count() == 1
        assert self.student_user.bookings.first().block is None

    def test_add_booking_with_expired_block(self):
        assert self.student_user.bookings.exists() is False
        block = baker.make(
            Block, user=self.student_user,
            block_config__event_type=self.event.event_type, manual_expiry_date=timezone.now() + timedelta(days=7),
            paid=True
        )
        self.event.start = timezone.now() + timedelta(days=8)
        self.event.save()

        resp = self.client.post(
            self.url,
            {"user": self.student_user.id, "event": self.event.id, "block": block.id, "status": "OPEN", "no_show": False}
        )
        assert self.student_user.bookings.count() == 0
        form = resp.context_data["form"]
        assert form.errors == {"block": ["Block is not valid for this class (wrong event type or expired by date of class)"]}

    def test_use_block_for_cancelled_booking(self):
        assert self.student_user.bookings.exists() is False
        block = baker.make(Block, user=self.student_user, block_config__event_type=self.event.event_type, paid=True)
        resp = self.client.post(
            self.url,
            {"user": self.student_user.id, "event": self.event.id, "block": block.id, "status": "CANCELLED",
             "no_show": False}
        )
        assert self.student_user.bookings.count() == 0
        form = resp.context_data["form"]
        assert form.errors == {
            "block": ["Block cannot be assigned for cancelled booking. Set to open and no_show if a block should be used."]
        }

    def test_full_event_not_in_choices(self):
        resp = self.client.get(self.url)
        form = resp.context_data["form"]
        assert self.event.id in [choice[0] for choice in form.fields["event"].choices]

        baker.make(Booking, event=self.event, _quantity=self.event.max_participants)
        resp = self.client.get(self.url)
        form = resp.context_data["form"]
        assert self.event.id not in [choice[0] for choice in form.fields["event"].choices]

    def test_send_email_confirmation(self):
        self.client.post(
            self.url,
            {
                "user": self.student_user.id, "event": self.event.id, "block": "", "status": "OPEN",
                "no_show": False, "send_confirmation": True
            }
        )
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [self.student_user.email]

    def test_send_email_confirmation_managed_user(self):
        url = reverse("studioadmin:bookingadd", args=(self.child_user.id,))
        self.client.post(
            url,
            {
                "user": self.child_user.id, "event": self.event.id, "block": "", "status": "OPEN",
                "no_show": False, "send_confirmation": True
            }
        )
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [self.manager_user.email]

    def test_remove_from_waiting_list(self):
        baker.make(WaitingListUser, user=self.student_user, event=self.event)
        self.client.post(
            self.url,
            {"user": self.student_user.id, "event": self.event.id, "block": "", "status": "OPEN", "no_show": False}
        )
        assert self.student_user.bookings.count() == 1
        assert WaitingListUser.objects.exists() is False


class UserBookingEditViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.event = baker.make_recipe("booking.future_event", max_participants=3)
        self.booking = baker.make(Booking, user=self.student_user, event=self.event)
        self.course = baker.make(Course, event_type=self.event.event_type, max_participants=3)
        self.course_block = baker.make_recipe(
            "booking.course_block", block_config__event_type=self.event.event_type, user=self.student_user, paid=True
        )
        self.dropin_block = baker.make_recipe(
            "booking.dropin_block", block_config__event_type=self.event.event_type, user=self.student_user, paid=True
        )


        self.login(self.staff_user)
        self.url = reverse("studioadmin:bookingedit", args=(self.booking.id,))
        self.form_data = {
            "id": self.booking.id,
            "user": self.student_user.id,
            "event": self.event.id,
            "status": self.booking.status,
            "no_show": self.booking.no_show,
            "auto_assign_available_subscription_or_block": False,
        }

    def test_instructor_and_staff_can_access(self):
        self.user_access_test(["staff", "instructor"], self.url)

    def test_change_status(self):
        self.client.post(self.url, {**self.form_data, "status": "CANCELLED"})
        self.booking.refresh_from_db()
        assert self.booking.status == "CANCELLED"

    def test_can_reopen_no_show(self):
        self.booking.no_show = True
        self.booking.save()
        self.client.post(self.url, self.form_data)
        self.booking.refresh_from_db()
        assert self.booking.no_show is False

    def test_cannot_remove_block_from_course_event(self):
        self.event.course = self.course
        self.event.save()
        self.booking.block = self.course_block
        self.booking.save()
        self.client.post(self.url, self.form_data)
        self.booking.refresh_from_db()
        assert self.booking.block == self.course_block

    def test_cannot_remove_block_from_course_event_even_if_cancelled(self):
        self.event.course = self.course
        self.event.save()
        self.booking.no_show = True
        self.booking.block = self.course_block
        self.booking.save()
        self.client.post(self.url, {**self.form_data, "no_show": self.booking.no_show})
        self.booking.refresh_from_db()
        assert self.booking.block == self.course_block
        assert self.booking.no_show is True

    def test_cannot_cancel_course_event(self):
        self.event.course = self.course
        self.event.save()
        self.booking.block = self.course_block
        self.booking.save()
        self.client.post(self.url, {**self.form_data, "status": "CANCELLED"})
        self.booking.refresh_from_db()
        # set to no show, block stays
        assert self.booking.block == self.course_block
        assert self.booking.status == "OPEN"
        assert self.booking.no_show is True

    def test_cannot_reopen_cancelled_booking_for_full_event(self):
        self.booking.status = "CANCELLED"
        self.booking.save()
        baker.make(Booking, event=self.event, _quantity=self.event.max_participants)
        self.client.post(self.url, {**self.form_data, "status": "OPEN"})
        self.booking.refresh_from_db()
        # still cancelled
        assert self.booking.status == "CANCELLED"

    def test_cannot_remove_no_show_for_full_event(self):
        self.booking.no_show = True
        self.booking.save()
        baker.make(Booking, event=self.event, _quantity=self.event.max_participants)
        self.client.post(self.url, {**self.form_data, "no_show": False})
        self.booking.refresh_from_db()
        # still cancelled
        assert self.booking.no_show is True

    def test_no_changes(self):
        resp = self.client.post(self.url, self.form_data)
        assert resp.status_code == 200

    def test_send_confirmation_no_changes(self):
        self.client.post(self.url, {**self.form_data, "send_confirmation": True})
        assert len(mail.outbox) == 0

        self.client.post(self.url, {**self.form_data, "status": "CANCELLED", "send_confirmation": True})
        assert len(mail.outbox) == 1

    def test_remove_block_from_cancelled_booking(self):
        self.booking.block = self.dropin_block
        self.booking.save()
        self.client.post(self.url, {**self.form_data, "status": "CANCELLED"})
        self.booking.refresh_from_db()
        # cancelled
        assert self.booking.status == "CANCELLED"
        # block removed
        assert self.booking.block is None

    def test_reopen_cancelled_booking(self):
        self.booking.status = "CANCELLED"
        self.booking.save()
        self.client.post(
            self.url, {**self.form_data, "block": self.dropin_block.id, "status": "OPEN", "send_confirmation": True}
        )
        self.booking.refresh_from_db()
        # cancelled
        assert self.booking.status == "OPEN"
        assert self.booking.block == self.dropin_block
        assert "has been reopened" in mail.outbox[0].subject

    def test_send_waiting_list_email_for_cancelled_booking_for_full_event(self):
        baker.make(WaitingListUser, event=self.event, user=self.student_user1)
        baker.make(WaitingListUser, event=self.event, user=self.child_user)
        baker.make(Booking, event=self.event, _quantity=self.event.max_participants - 1)
        assert self.event.full is True
        self.client.post(self.url, {**self.form_data, "status": "CANCELLED"})
        assert len(mail.outbox) == 1
        assert mail.outbox[0].bcc == [self.student_user1.email, self.manager_user.email]


class UserCourseBookingAddViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.create_tracks_and_event_types()
        self.create_events_and_course()

        # configure the course
        for i in range(self.course.number_of_events - self.course.uncancelled_events.count()):
            baker.make(Event, event_type=self.course.event_type, course=self.course)
        self.unconfigured_course = baker.make(
            Course, event_type=self.course.event_type, number_of_events=self.course.number_of_events
        )

        self.course_config = baker.make(BlockConfig, duration=2, cost=10, event_type=self.course.event_type, course=True, size=self.course.number_of_events)

        self.login(self.staff_user)
        self.url = reverse("studioadmin:coursebookingadd", args=(self.student_user.id,))

    def test_instructor_and_staff_can_access(self):
        self.user_access_test(["staff", "instructor"], self.url)

    def test_get(self):
        resp = self.client.get(self.url)
        assert resp.context["booking_user"] == self.student_user

    def test_add_course_booking_no_available_block(self):
        assert self.student_user.bookings.exists() is False
        resp = self.client.get(self.url)
        assert resp.context["form"].fields["course"].choices == []
        assert "Student has no available course credit blocks" in resp.content.decode("utf-8")

        # unpaid block, still not allowed to book
        block = baker.make(Block, user=self.student_user, block_config=self.course_config, paid=False)
        resp = self.client.get(self.url)
        assert resp.context["form"].fields["course"].choices == []
        assert "Student has no available course credit blocks" in resp.content.decode("utf-8")

        # paid block, allowed
        block.paid = True
        block.save()
        resp = self.client.get(self.url)
        # Only the configured course is an option
        assert len(resp.context["form"].fields["course"].choices) == 1
        assert resp.context["form"].fields["course"].choices[0][0] == self.course.id

    def test_course_options(self):
        def _get_choices_ids(response):
            return sorted(choice[0] for choice in response.context["form"].fields["course"].choices)
        # user has paid block valid for self.course and self.unconfigured_course
        block = baker.make(
            Block, user=self.student_user, block_config=self.course_config, paid=True
        )
        block.save()
        resp = self.client.get(self.url)
        # Only the configured course is an option
        choices = _get_choices_ids(resp)
        assert len(resp.context["form"].fields["course"].choices) == 1
        assert choices == [self.course.id]

        # configured course with spaces, but not valid for the user's block, not shown in choices
        course = baker.make(Course, event_type=self.course.event_type, number_of_events=4, max_participants=3)
        baker.make(Event, course=course, event_type=self.course.event_type, _quantity=4)
        assert course.is_configured()
        assert course.full is False
        assert block.valid_for_course(course) is False
        resp = self.client.get(self.url)
        assert _get_choices_ids(resp) == [self.course.id]

        # make a block for the user
        new_block = baker.make(
            Block, user=self.student_user, block_config__event_type=self.course.event_type,
            block_config__course=True, block_config__size=4, paid=True
        )
        assert new_block.valid_for_course(course) is True
        resp = self.client.get(self.url)
        assert _get_choices_ids(resp) == sorted([self.course.id, course.id])

        # make self.course full
        for event in self.course.uncancelled_events:
            baker.make(Booking, event=event, _quantity=self.course.max_participants)
        assert self.course.full is True
        resp = self.client.get(self.url)
        assert _get_choices_ids(resp) == [course.id]

    def test_post_with_no_valid_options(self):
        resp = self.client.post(self.url, {"course": self.course.id})
        assert resp.context["form"].errors == {"course": ["No valid course options"]}

    def test_add_booking_with_autoassigned_block(self):
        assert self.student_user.bookings.exists() is False
        block = baker.make(Block, user=self.student_user, block_config=self.course_config, paid=True)
        assert block.valid_for_course(self.course) is True
        self.client.post(self.url, {"course": self.course.id})
        assert self.student_user.bookings.count() == self.course.uncancelled_events.count()
        for booking in self.student_user.bookings.all():
            assert booking.event.course == self.course
            assert booking.block == block


class UserBlockChangeCourseTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.create_tracks_and_event_types()
        self.course1 = baker.make(
            Course, number_of_events=2, event_type=self.aerial_event_type, max_participants=3
        )
        self.course2 = baker.make(
            Course, number_of_events=2, event_type=self.aerial_event_type, max_participants=3
        )
        baker.make(Event, event_type=self.aerial_event_type, course=self.course1, _quantity=2)
        baker.make(Event, event_type=self.aerial_event_type, course=self.course2, _quantity=2)
        self.login(self.staff_user)

        course_config = baker.make(
            BlockConfig, duration=2, cost=10, event_type=self.aerial_event_type, course=True,
            size=2
        )
        self.block = baker.make(Block, user=self.student_user, block_config=course_config, paid=True)

        self.url = reverse("studioadmin:courseblockchange", args=(self.block.id,))

    def test_instructor_and_staff_can_access(self):
        self.user_access_test(["staff", "instructor"], self.url)

    def test_get(self):
        resp = self.client.get(self.url)
        assert resp.context["block"] == self.block

    def test_course_options(self):
        def _get_choices_ids(response):
            return sorted(choice[0] for choice in response.context["form"].fields["course"].choices)
        resp = self.client.get(self.url)
        # Both courses are configured and valid for the block
        choices = _get_choices_ids(resp)
        assert choices == sorted([self.course1.id, self.course2.id])

        # book user on course 1
        for event in self.course1.uncancelled_events:
            baker.make(Booking, user=self.student_user, event=event, block=self.block)
        resp = self.client.get(self.url)
        choices = _get_choices_ids(resp)
        assert choices == [self.course2.id]

        # configured course with spaces, but not valid for the user's block, not shown in choices
        course = baker.make(Course, event_type=self.course1.event_type, number_of_events=4, max_participants=3)
        baker.make(Event, course=course, event_type=self.course1.event_type, _quantity=4)
        assert course.is_configured()
        assert course.full is False
        resp = self.client.get(self.url)
        assert _get_choices_ids(resp) == [self.course2.id]

        # make self.course full
        for event in self.course2.uncancelled_events:
            baker.make(Booking, event=event, _quantity=self.course2.max_participants)
        assert self.course2.full is True
        resp = self.client.get(self.url)
        assert _get_choices_ids(resp) == []

    def test_add_course_to_block(self):
        assert self.student_user.bookings.exists() is False
        self.client.post(self.url, {"course": self.course1.id})
        assert self.student_user.bookings.count() == 2
        for booking in self.student_user.bookings.all():
            assert booking.block == self.block

    def test_change_course_on_block(self):
        for event in self.course1.events.all():
            baker.make(Booking, event=event, user=self.student_user, block=self.block)

        self.client.post(self.url, {"course": self.course2.id})
        assert self.student_user.bookings.count() == 4
        for booking in self.student_user.bookings.filter(event__course=self.course1):
            assert booking.block is None
            assert booking.status == "CANCELLED"
        for booking in self.student_user.bookings.filter(event__course=self.course2):
            assert booking.block == self.block

    def test_send_email_confirmation(self):
        self.client.post(self.url, {"course": self.course1.id, "send_confirmation": True})
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [self.student_user.email]

    def test_send_email_confirmation_managed_user(self):
        self.block.user=self.child_user
        self.block.save()
        url = reverse("studioadmin:courseblockchange", args=(self.block.id,))
        self.client.post(
            url, {"course": self.course1.id, "send_confirmation": True}
        )
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [self.manager_user.email]


class UserBlockListViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.login(self.staff_user)
        self.url = reverse("studioadmin:user_blocks", args=(self.student_user.id,))

    def test_instructor_and_staff_can_access(self):
        self.user_access_test(["staff", "instructor"], self.url)

    def test_get(self):
        baker.make_recipe("booking.course_block", user=self.student_user, paid=True)
        baker.make_recipe("booking.dropin_block", user=self.student_user, paid=True)
        baker.make_recipe("booking.dropin_block", user=self.student_user, paid=False)
        baker.make_recipe("booking.dropin_block", user=self.student_user1, paid=True)
        resp = self.client.get(self.url)
        assert resp.context_data["account_user"] == self.student_user
        assert len(resp.context_data["blocks"]) == 3


class AddUserBlockViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.dropin_block_config = baker.make(BlockConfig, active=True)
        self.course_block_config = baker.make(BlockConfig, course=True, active=True)
        self.login(self.staff_user)
        self.url = reverse("studioadmin:blockadd", args=(self.student_user.id,))

    def test_instructor_and_staff_can_access(self):
        self.user_access_test(["staff", "instructor"], self.url)

    def test_get(self):
        resp = self.client.get(self.url)
        assert resp.context_data["block_user"] == self.student_user

    def test_add_block(self):
        assert self.student_user.blocks.exists() is False
        self.client.post(self.url, {"block_config": self.dropin_block_config.id, "paid": True, "user": self.student_user.id})
        assert self.student_user.blocks.count() == 1
        assert self.student_user.blocks.first().paid is True

    def test_add_block_with_manual_expiry(self):
        assert self.student_user.blocks.exists() is False
        expiry = timezone.now() + timedelta(20)
        self.client.post(
            self.url,
            {
                "block_config": self.course_block_config.id, "paid": True, "user": self.student_user.id,
                "manual_expiry_date": expiry.strftime("%d-%b-%Y")
            })
        assert self.student_user.blocks.count() == 1
        assert self.student_user.blocks.first().expiry_date.date() == expiry.date()


class EditUserBlockViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.aerial_block_config = baker.make(BlockConfig, event_type=self.aerial_event_type, active=True, size=2)
        self.aerial_block = baker.make(Block, block_config=self.aerial_block_config, user=self.student_user, paid=True)
        self.floor_block_config = baker.make(BlockConfig, event_type=self.floor_event_type, active=True, size=2)
        self.login(self.staff_user)
        self.url = reverse("studioadmin:blockedit", args=(self.aerial_block.id,))

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def test_instructor_and_staff_can_access(self):
        self.user_access_test(["staff", "instructor"], self.url)

    def test_edit_block(self):
        self.client.post(
            self.aerial_block.id,
            {"id": self.aerial_block.id, "block_config": self.aerial_event_type.id, "paid": False, "user": self.student_user.id}
        )
        self.aerial_block.refresh_from_db()
        assert self.aerial_block.paid is True

    def test_change_block_config(self):
        self.client.post(
            self.url,
            {"id": self.aerial_block.id, "block_config": self.floor_block_config.id, "paid": False, "user": self.student_user.id}
        )
        self.aerial_block.refresh_from_db()
        assert self.aerial_block.block_config == self.floor_block_config

    def test_change_block_config_type_with_bookings(self):
        aerial_block_config1 = baker.make(BlockConfig, event_type=self.aerial_event_type, active=True, size=4)
        baker.make(Booking, user=self.student_user, block=self.aerial_block)
        # can't change to block config with different event type
        self.client.post(
            self.url,
            {"id": self.aerial_block.id, "block_config": self.floor_block_config.id, "paid": True,
             "user": self.student_user.id}
        )
        self.aerial_block.refresh_from_db()
        assert self.aerial_block.block_config == self.aerial_block_config

        self.client.post(
            self.url,
            {"id": self.aerial_block.id, "block_config": aerial_block_config1.id, "paid": True,
             "user": self.student_user.id}
        )
        self.aerial_block.refresh_from_db()
        assert self.aerial_block.block_config == aerial_block_config1

    def test_change_block_config_type_with_too_many_bookings(self):
        # make 2 bookings
        baker.make(Booking, user=self.student_user, block=self.aerial_block, _quantity=self.aerial_block_config.size)
        smaller_aerial_block_config = baker.make(BlockConfig, event_type=self.aerial_event_type, active=True, size=1)

        # try to change to block config with too small size
        self.client.post(
            self.url,
            {"id": self.aerial_block.id, "block_config": smaller_aerial_block_config.id, "paid": True,
             "user": self.student_user.id}
        )
        self.aerial_block.refresh_from_db()
        assert self.aerial_block.block_config == self.aerial_block_config


class DeleteUserBlockViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.block = baker.make(Block, user=self.student_user, paid=False)
        self.login(self.staff_user)
        self.url = reverse("studioadmin:blockdelete", args=(self.block.id,))

    def test_delete(self):
        self.client.post(self.url, args=(self.block.id,))
        assert self.student_user.blocks.exists() is False

    def test_delete_paid(self):
        self.block.paid = True
        self.block.save()
        resp = self.client.post(self.url, args=(self.block.id,))
        assert resp.status_code == 400
        assert self.student_user.blocks.exists() is True
