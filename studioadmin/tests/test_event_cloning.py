from datetime import datetime, date, time
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

    @patch("studioadmin.forms.timezone")
    def test_clone_single_event_already_exists(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        event = baker.make_recipe(
            "booking.future_event", name="Original event",  event_type=self.aerial_event_type,
            start=datetime(2020, 4, 4, 10, 0, tzinfo=timezone.utc)
        )
        data = {
            "recurring_once_datetime": "04-Apr-2020 10:00",
            "submit": "Clone once"
        }
        resp = self.client.post(self.url, data, follow=True)
        assert Event.objects.filter(name="Original event").count() == 1
        assert "Class not cloned; a duplicate with this name and start already exists" in resp.rendered_content

    @patch("studioadmin.forms.timezone")
    def test_redirect_to_events_with_track(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        data = {
            "recurring_once_datetime": "04-Apr-2020 10:00",
            "submit": "Clone once"
        }
        resp = self.client.post(self.url, data)
        assert resp.url == reverse("studioadmin:events") + f"?track={self.event.event_type.track.id}"

    @patch("studioadmin.forms.timezone")
    def test_clone_weekly_recurring_event(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        data = {
            "recurring_weekly_start": "01-Jul-2020",
            "recurring_weekly_end": "31-Jul-2020",
            "recurring_weekly_time": "10:00",
            "recurring_weekly_weekdays": [0],
            "submit": "Clone weekly recurring class",
        }
        self.client.post(self.url, data)
        cloned_events = Event.objects.filter(name="Original event").exclude(id=self.event.id).order_by("start")
        # Mondays in July - 6th, 13th, 20th, 27th
        dates = [cloned_events.start.date() for cloned_event in cloned_events]
        times = {cloned_events.start.time() for cloned_event in cloned_events}
        assert dates == [date(2020, 7, 6), date(2020, 7, 13), date(2020, 7, 20), date(2020, 7, 27)]
        assert times == {time(10, 0)}

    @patch("studioadmin.forms.timezone")
    def test_clone_weekly_recurring_event_inclusive(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        data = {
            "recurring_weekly_start": "17-Jul-2020",
            "recurring_weekly_end": "31-Jul-2020",
            "recurring_weekly_time": "10:00",
            "recurring_weekly_weekdays": [4],
            "submit": "Clone weekly recurring class",
        }
        resp = self.client.post(self.url, data)
        cloned_events = Event.objects.filter(name="Original event").exclude(id=self.event.id).order_by("start")
        # Fridays in July - 17th, 24th, 31st - make events on inclusive start/end dates
        dates = [cloned_events.start.date() for cloned_event in cloned_events]
        times = {cloned_events.start.time() for cloned_event in cloned_events}
        assert dates == [date(2020, 7, 17), date(2020, 7, 24), date(2020, 7, 31)]
        assert times == {time(10, 0)}

    @patch("studioadmin.forms.timezone")
    def test_clone_weekly_recurring_event_date_validation(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 4, 1, tzinfo=timezone.utc)
        data = {
            "recurring_weekly_start": "12-Mar-2019",
            "recurring_weekly_end": "31-Jul-2020",
            "recurring_weekly_time": "10:00",
            "recurring_weekly_weekdays": [4],
            "submit": "Clone weekly recurring class",
        }
        resp = self.client.post(self.url, data)
        form = resp.rendered_content["form"]
        assert form.errors == {"recurring_weekly_start": "Date must be in the future"}

        data = {
            "recurring_weekly_start": "12-Jul-2020",
            "recurring_weekly_end": "14-Mar-2020",
            "recurring_weekly_time": "10:00",
            "recurring_weekly_weekdays": [4],
            "submit": "Clone weekly recurring class",
        }
        resp = self.client.post(self.url, data)
        form = resp.rendered_content["form"]
        assert form.errors == {"recurring_weekly_end": "Date must be in the future"}

        data = {
            "recurring_weekly_start": "01-Aug-2020",
            "recurring_weekly_end": "31-Jul-2020",
            "recurring_weekly_time": "10:00",
            "recurring_weekly_weekdays": [4],
            "submit": "Clone weekly recurring class",
        }
        resp = self.client.post(self.url, data)
        form = resp.rendered_content["form"]
        assert form.errors == {"recurring_weekly_end": "End date must be after start date"}

    @patch("studioadmin.forms.timezone")
    def test_clone_weekly_recurring_event_multiple_days(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        data = {
            "recurring_weekly_start": "01-Jul-2020",
            "recurring_weekly_end": "31-Jul-2020",
            "recurring_weekly_time": "10:00",
            "recurring_weekly_weekdays": [2, 6],
            "submit": "Clone weekly recurring class",
        }
        self.client.post(self.url, data)
        cloned_events = Event.objects.filter(name="Original event").exclude(id=self.event.id).order_by("start")
        # Wed and Sun in July - 1st, 5th, 8th, 12th, 15th, 19th, 22nd, 26th
        dates = [cloned_events.start.date() for cloned_event in cloned_events]
        times = {cloned_events.start.time() for cloned_event in cloned_events}
        assert dates == [date(2020, day, 17) for day in [1, 5, 8, 12, 15, 19, 22, 26]]
        assert times == {time(10, 0)}

    @patch("studioadmin.forms.timezone")
    def test_clone_recurring_daily_intervals(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        data = {
            "recurring_daily_date": "01-Jul-2020",
            "recurring_daily_interval": "20",
            "recurring_daily_starttime": "10:00",
            "recurring_daily_endtime": "12:00",
            "submit": "Clone at recurring intervals",
        }
        self.client.post(self.url, data)
        cloned_events = Event.objects.filter(name="Original event").exclude(id=self.event.id).order_by("start")
        dates = {cloned_events.start.date() for cloned_event in cloned_events}
        times = {cloned_events.start.time() for cloned_event in cloned_events}
        assert dates == {date(2020, 7, 1)}
        assert times == {time(10, 0), time(10, 20), time(10, 40), time(11, 0), time(11, 20), time(11, 40), time(12, 00)}

    @patch("studioadmin.forms.timezone")
    def test_clone_recurring_daily_intervals_start_date_today(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 7, 1, 10, 0, tzinfo=timezone.utc)
        data = {
            "recurring_daily_date": "01-Jul-2020",
            "recurring_daily_interval": "10",
            "recurring_daily_starttime": "10:00",
            "recurring_daily_endtime": "10:30",
            "submit": "Clone at recurring intervals",
        }
        self.client.post(self.url, data)
        cloned_events = Event.objects.filter(name="Original event").exclude(id=self.event.id).order_by("start")
        dates = {cloned_events.start.date() for cloned_event in cloned_events}
        times = {cloned_events.start.time() for cloned_event in cloned_events}
        assert dates == {date(2020, 7, 1)}
        assert times == {time(10, 0), time(10, 10), time(10, 20), time(10, 30)}

    @patch("studioadmin.forms.timezone")
    def test_clone_recurring_daily_intervals_validation(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 4, 1, tzinfo=timezone.utc)
        data = {
            "recurring_daily_date": "01-Mar-2020",
            "recurring_daily_interval": "20",
            "recurring_daily_starttime": "10:00",
            "recurring_daily_endtime": "12:00",
            "submit": "Clone at recurring intervals",
        }
        resp = self.client.post(self.url, data)
        form = resp.rendered_content["form"]
        assert form.errors == {"recurring_daily_date": "Date must be in the future"}

        data = {
            "recurring_daily_date": "01-Aug-2020",
            "recurring_daily_interval": "20",
            "recurring_daily_starttime": "10:00",
            "recurring_daily_endtime": "09:00",
            "submit": "Clone at recurring intervals",
        }
        resp = self.client.post(self.url, data)
        form = resp.rendered_content["form"]
        assert form.errors == {"recurring_daily_endtime": "End time must be after start time"}
