from datetime import datetime
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


class CloneEventTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.create_events_and_course()
        self.login(self.staff_user)
        self.event = baker.make_recipe(
            "booking.future_event", name="Original event", show_on_site=True, max_participants=4,
            event_type=self.aerial_event_type,
            course=self.course
        )
        self.url = reverse("studioadmin:clone_event", args=(self.event.slug,))

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def test_only_staff_user_can_access(self):
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

    @patch("studioadmin.forms.timezone")
    def test_clone_single_event(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        data = {
            "recurring_once_datetime": "04-Apr-2020 10:00",
            "submit": "Clone once"
        }
        self.client.post(self.url, data)
        cloned_event = Event.objects.latest("id")
        assert cloned_event.id != self.event.id
        # cloned properties
        assert cloned_event.name == self.event.name
        assert cloned_event.max_participants == self.event.max_participants
        # set to defaults
        assert cloned_event.show_on_site is False
        assert cloned_event.course is None
        assert cloned_event.start == datetime(2020, 4, 4, 10, 0, tzinfo=timezone.utc)

    def test_redirect_to_events_with_track(self):
        pass

    def test_clone_weekly_recurring_event(self):
        pass

    def test_clone_weekly_recurring_event_multiple_days(self):
        pass

    def test_clone_recurring_daily_intervals(self):
        pass
