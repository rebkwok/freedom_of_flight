from model_bakery import baker

from django.urls import reverse
from django.test import TestCase

from booking.models import Booking, WaitingListUser
from common.test_utils import EventTestMixin, TestUsersMixin
from common.utils import full_name


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
        self.login(self.student_user)
        resp = self.client.get(self.event_url)
        assert resp.status_code == 302
        assert resp.url == reverse("booking:permission_denied")

        self.login(self.instructor_user)
        resp = self.client.get(self.event_url)
        assert resp.status_code == 302
        assert resp.url == reverse("booking:permission_denied")

        self.login(self.staff_user)
        resp = self.client.get(self.event_url)
        assert resp.status_code == 200

    def test_email_event_users_open_and_cancelled_bookings(self):
        # shows users for open bookings checked, cancelled/no-show unchecked in form initial
        baker.make(Booking, event=self.event, user=self.student_user)
        baker.make(Booking, event=self.event, user=self.instructor_user, status="OPEN", no_show=True)
        baker.make(Booking, event=self.event, user=self.student_user1, status="CANCELLED")
        resp = self.client.get(self.event_url)
        form = resp.context_data["form"]
        assert form.fields["students"].initial == [self.student_user.id]
        choices_ids = [user[0] for user in form.fields["students"].choices]
        assert choices_ids[0] == self.student_user.id
        assert sorted(choices_ids[1:]) == sorted([self.instructor_user.id, self.student_user1.id])

    def test_email_event_users_reply_to_and_cc_options(self):
        pass

    def test_select_at_least_one_user(self):
        pass

    def test_emails_go_to_manager_user(self):
        pass

    def test_email_event_course_users(self):
        # shows users with open bookings checked, cancelled/no-show unchecked in form initial
        pass

    def test_email_course_users(self):
        # shows users with any bookings on any event on the course
        # only shows each user once
        pass
