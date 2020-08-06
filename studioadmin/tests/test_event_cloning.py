from datetime import datetime, date, time, timedelta
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

    def test_inital(self):
        self.event.start = datetime(2020, 1, 1, 10, 0, tzinfo=timezone.utc)
        self.event.save()
        resp = self.client.get(self.url)
        # single clone sets date to event date + one week
        assert resp.context_data["single_form"].initial == {
            "recurring_once_datetime": self.event.start + timedelta(days=7)
        }
        assert resp.context_data["daily_form"].initial == {}
        assert resp.context_data["weekly_form"].initial == {
            "recurring_weekly_weekdays": [self.event.start.weekday()],
            "recurring_weekly_time": self.event.start.time()
        }
        # If the event is in BST, the initial start times are adjusted
        self.event.start = datetime(2020, 8, 1, 10, 0, tzinfo=timezone.utc)
        self.event.save()
        resp = self.client.get(self.url)
        # single clone sets date to event date + one week; this stays as it is because django will display it properly
        assert resp.context_data["single_form"].initial == {
            "recurring_once_datetime": self.event.start + timedelta(days=7)
        }
        assert resp.context_data["daily_form"].initial == {}
        # but we adjust the time to show the user the time they expect today
        assert resp.context_data["weekly_form"].initial == {
            "recurring_weekly_weekdays": [self.event.start.weekday()],
            "recurring_weekly_time": (self.event.start + timedelta(hours=1)).time()
        }

    @patch("studioadmin.forms.timezone")
    def test_clone_single_event(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        # This datestring in the form is in local time (BST) and converted to UTC by django
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
        assert cloned_event.start == datetime(2020, 4, 4, 9, 0, tzinfo=timezone.utc)

    @patch("studioadmin.forms.timezone")
    def test_clone_single_event_already_exists(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        # make another event with the same name and event type, and the date we're about to try to clone to
        baker.make_recipe(
            "booking.future_event", name="Original event",  event_type=self.aerial_event_type,
            start=datetime(2020, 4, 4, 9, 0, tzinfo=timezone.utc)
        )
        assert Event.objects.filter(name="Original event").count() == 2
        # This datestring in the form is in local time (BST) and converted to UTC by django
        data = {
            "recurring_once_datetime": "04-Apr-2020 10:00",
            "submit": "Clone once"
        }
        resp = self.client.post(self.url, data, follow=True)
        assert Event.objects.filter(name="Original event").count() == 2
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
        dates = [cloned_event.start.date() for cloned_event in cloned_events]
        times = {cloned_event.start.time() for cloned_event in cloned_events}
        # Today is non-BST, event dates are BST, so event dates in UTC are 1 hr earlier
        assert dates == [date(2020, 7, 6), date(2020, 7, 13), date(2020, 7, 20), date(2020, 7, 27)]
        assert times == {time(9, 0)}

    @patch("studioadmin.forms.timezone")
    def test_clone_weekly_recurring_event_already_exists(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        data = {
            "recurring_weekly_start": "01-Jul-2020",
            "recurring_weekly_end": "31-Jul-2020",
            "recurring_weekly_time": "10:00",
            "recurring_weekly_weekdays": [0],
            "submit": "Clone weekly recurring class",
        }
        # Existing event that shouldn't get cloned
        existing = baker.make_recipe(
            "booking.future_event", name="Original event",
            event_type=self.aerial_event_type, start=datetime(2020, 7, 6, 9, 0, tzinfo=timezone.utc)
        )
        resp = self.client.post(self.url, data, follow=True)
        cloned_events = Event.objects.filter(name="Original event").exclude(id=self.event.id).order_by("start")
        # Mondays in July - 6th, 13th, 20th, 27th
        dates = [cloned_event.start.date() for cloned_event in cloned_events]
        times = {cloned_event.start.time() for cloned_event in cloned_events}
        # Today is non-BST, event dates are BST, so event dates in UTC are 1 hr earlier
        assert dates == [date(2020, 7, 6), date(2020, 7, 13), date(2020, 7, 20), date(2020, 7, 27)]
        assert times == {time(9, 0)}
        assert Event.objects.get(name="Original event", start__date=date(2020, 7, 6)).id == existing.id
        # message to user shows local time
        assert "Classes with this name already exist for the following dates/times and were not cloned: " \
               "6 Jul 2020, 10:00" in resp.rendered_content

    @patch("studioadmin.forms.timezone")
    def test_clone_weekly_recurring_event_nothing_to_clone(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        # no mondays in time period
        data = {
            "recurring_weekly_start": "01-Jul-2020",
            "recurring_weekly_end": "05-Jul-2020",
            "recurring_weekly_time": "10:00",
            "recurring_weekly_weekdays": [0],
            "submit": "Clone weekly recurring class",
        }
        resp = self.client.post(self.url, data, follow=True)
        cloned_events = Event.objects.filter(name="Original event").exclude(id=self.event.id)
        assert cloned_events.exists() is False
        assert "Nothing to clone" in resp.rendered_content

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
        self.client.post(self.url, data)
        cloned_events = Event.objects.filter(name="Original event").exclude(id=self.event.id).order_by("start")
        # Fridays in July - 17th, 24th, 31st - make events on inclusive start/end dates
        dates = [cloned_event.start.date() for cloned_event in cloned_events]
        times = {cloned_event.start.time() for cloned_event in cloned_events}
        # Today is non-BST, event dates are BST, so event dates in UTC are 1 hr earlier
        assert dates == [date(2020, 7, 17), date(2020, 7, 24), date(2020, 7, 31)]
        assert times == {time(9, 0)}

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
        form = resp.context_data["weekly_form"]
        assert form.errors == {"recurring_weekly_start": ["Date must be in the future"]}

        data = {
            "recurring_weekly_start": "12-Jul-2020",
            "recurring_weekly_end": "14-Mar-2020",
            "recurring_weekly_time": "10:00",
            "recurring_weekly_weekdays": [4],
            "submit": "Clone weekly recurring class",
        }
        resp = self.client.post(self.url, data)
        form = resp.context_data["weekly_form"]
        assert form.errors == {"recurring_weekly_end": ["Date must be in the future"]}

        data = {
            "recurring_weekly_start": "01-Aug-2020",
            "recurring_weekly_end": "31-Jul-2020",
            "recurring_weekly_time": "10:00",
            "recurring_weekly_weekdays": [4],
            "submit": "Clone weekly recurring class",
        }
        resp = self.client.post(self.url, data)
        form = resp.context_data["weekly_form"]
        assert form.errors == {"recurring_weekly_end": ["End date must be after start date"]}

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
        # Wed and Sun in July - 1st, 5th, 8th, 12th, 15th, 19th, 22nd, 26th, 29th
        dates = [cloned_event.start.date() for cloned_event in cloned_events]
        times = {cloned_event.start.time() for cloned_event in cloned_events}
        assert dates == [date(2020, 7, day) for day in [1, 5, 8, 12, 15, 19, 22, 26, 29]]
        # Mocked now is January - not BST.  Input time is taked as the expected literal time, so if the event is in
        # BST, the UTC date is 1 hr before
        assert times == {time(9, 0)}

    @patch("studioadmin.forms.timezone")
    def test_clone_recurring_daily_intervals(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        data = {
            "recurring_daily_date": "07-Jan-2020",
            "recurring_daily_interval": "20",
            "recurring_daily_starttime": "10:00",
            "recurring_daily_endtime": "12:00",
            "submit": "Clone at recurring intervals",
        }
        self.client.post(self.url, data)
        cloned_events = Event.objects.filter(name="Original event").exclude(id=self.event.id).order_by("start")
        dates = {cloned_event.start.date() for cloned_event in cloned_events}
        times = {cloned_event.start.time() for cloned_event in cloned_events}
        # Mocked now and event data are both in GMT, so entered time is the same in UTC-stored events
        assert dates == {date(2020, 1, 7)}
        assert times == {time(10, 0), time(10, 20), time(10, 40), time(11, 0), time(11, 20), time(11, 40), time(12, 00)}

    @patch("studioadmin.forms.timezone")
    def test_clone_recurring_daily_intervals_existing_event(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        data = {
            "recurring_daily_date": "07-Jan-2020",
            "recurring_daily_interval": "20",
            "recurring_daily_starttime": "10:00",
            "recurring_daily_endtime": "12:00",
            "submit": "Clone at recurring intervals",
        }
        existing = baker.make_recipe(
            "booking.future_event", name="Original event", event_type=self.event.event_type,
            start=datetime(2020, 1, 7, 10, 40, tzinfo=timezone.utc)
        )
        resp = self.client.post(self.url, data, follow=True)
        cloned_events = Event.objects.filter(name="Original event").exclude(id=self.event.id).order_by("start")
        dates = {cloned_event.start.date() for cloned_event in cloned_events}
        times = {cloned_event.start.time() for cloned_event in cloned_events}
        # Mocked now and event data are both in GMT, so entered time is the same in UTC-stored events
        assert dates == {date(2020, 1, 7)}
        assert times == {time(10, 0), time(10, 20), time(10, 40), time(11, 0), time(11, 20), time(11, 40), time(12, 00)}
        assert Event.objects.get(name="Original event", start=datetime(2020, 1, 7, 10, 40, tzinfo=timezone.utc)).id == existing.id
        assert "Classes with this name already exist on 7 Jan 2020 at these times and were not cloned: " \
               "10:40" in resp.rendered_content

    @patch("studioadmin.forms.timezone")
    def test_clone_recurring_daily_intervals_nothing_to_clone(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        data = {
            "recurring_daily_date": "07-Jan-2020",
            "recurring_daily_interval": "20",
            "recurring_daily_starttime": "10:00",
            "recurring_daily_endtime": "10:10",
            "submit": "Clone at recurring intervals",
        }
        # existing event at start time, which is the only valid cloning time
        existing = baker.make_recipe(
            "booking.future_event", name="Original event", event_type=self.event.event_type,
            start=datetime(2020, 1, 7, 10, 0, tzinfo=timezone.utc)
        )
        assert Event.objects.filter(name="Original event").exclude(id__in=[self.event.id, existing.id]).exists() is False
        resp = self.client.post(self.url, data, follow=True)
        assert "Classes with this name already exist on 7 Jan 2020 at these times and were not cloned: " \
               "10:00" in resp.rendered_content

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
        dates = {cloned_event.start.date() for cloned_event in cloned_events}
        times = {cloned_event.start.time() for cloned_event in cloned_events}
        assert dates == {date(2020, 7, 1)}
        # today is BST, so times are 1 hr earlier in UTC
        assert times == {time(9, 0), time(9, 10), time(9, 20), time(9, 30)}

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
        form = resp.context_data["daily_form"]
        assert form.errors == {"recurring_daily_date": ["Date must be in the future"]}

        data = {
            "recurring_daily_date": "01-Aug-2020",
            "recurring_daily_interval": "20",
            "recurring_daily_starttime": "10:00",
            "recurring_daily_endtime": "09:00",
            "submit": "Clone at recurring intervals",
        }
        resp = self.client.post(self.url, data)
        form = resp.context_data["daily_form"]
        assert form.errors == {"recurring_daily_endtime": ["End time must be after start time"]}

    @patch("studioadmin.forms.timezone")
    def test_clone_with_no_valid_form(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 4, 1, tzinfo=timezone.utc)
        data = {
            "recurring_daily_date": "01-Mar-2020",
            "recurring_daily_interval": "20",
            "recurring_daily_starttime": "10:00",
            "recurring_daily_endtime": "12:00",
            "submit": "Unknown submission button",
        }
        resp = self.client.post(self.url, data)
        # renders the same page again
        assert resp.status_code == 200

    @patch("studioadmin.forms.timezone")
    def test_clone_ignores_other_form_fields(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 4, 1, tzinfo=timezone.utc)
        data = {
            "recurring_daily_date": "01-Apr-2020",
            "recurring_daily_interval": "30",
            "recurring_daily_starttime": "10:00",
            "recurring_daily_endtime": "10:30",
            "recurring_weekly_start": "01-Jul-2020",
            "recurring_weekly_end": "31-Jul-2020",
            "recurring_weekly_time": "10:00",
            "recurring_weekly_weekdays": [2, 6],
            "recurring_once_datetime": "04-Apr-2020 10:00",
            "submit": "Clone at recurring intervals",
        }
        self.client.post(self.url, data)
        cloned_events = Event.objects.filter(name="Original event").exclude(id=self.event.id).order_by("start")
        dates = {cloned_event.start.date() for cloned_event in cloned_events}
        times = {cloned_event.start.time() for cloned_event in cloned_events}
        assert dates == {date(2020, 4, 1)}
        # BST, stored times are in UTC
        assert times == {time(9, 0), time(9, 30)}
