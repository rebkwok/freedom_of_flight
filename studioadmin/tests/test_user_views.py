from model_bakery import baker

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.urls import reverse
from django.test import TestCase

from booking.models import Booking
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
