# -*- coding: utf-8 -*-
from datetime import datetime, date, time
from model_bakery import baker
from unittest.mock import patch

from django import forms
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from booking.models import Event, EventType, Track
from common.test_utils import TestUsersMixin, EventTestMixin
from timetable.models import TimetableSession


class TimetableListViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.url = reverse('studioadmin:timetable')
        self.adult_sessions = baker.make(TimetableSession, event_type=self.aerial_event_type, _quantity=10)
        self.kids_sessions = baker.make(TimetableSession, event_type=self.kids_aerial_event_type, _quantity=10)
    
    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()
        
    def test_can_only_access_as_staff(self):
        resp = self.client.get(self.url)
        redirected_url = reverse('account_login') + "?next={}".format(self.url)
        assert resp.status_code == 302
        assert redirected_url in resp.url

        self.user_access_test(["staff"], self.url)

    def test_sessions_by_track(self):
        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert "track_sessions" in resp.context_data
        track_sessions = resp.context_data["track_sessions"]
        assert len(track_sessions) == 2  # 2 tracks, kids and adults
        assert track_sessions[0]["track"] == "Adults"
        assert len(track_sessions[0]["page_obj"].object_list) == TimetableSession.objects.filter(event_type__track=self.adult_track).count()
        assert track_sessions[1]["track"] == "Kids"
        assert len(track_sessions[1]["page_obj"].object_list) == TimetableSession.objects.filter(event_type__track=self.kids_track).count()

    def test_events_with_track_param(self):
        self.login(self.staff_user)
        resp = self.client.get(self.url + f"?track={self.kids_track.id}")
        track_sessions = resp.context_data["track_sessions"]
        assert track_sessions[1]["track"] == "Kids"
        assert resp.context_data["active_tab"] == 1

        resp = self.client.get(self.url + "?track=invalid-id")
        assert "active_tab" not in resp.context_data

    def test_pagination(self):
        baker.make(TimetableSession, event_type__track=self.adult_track, _quantity=20)
        self.login(self.staff_user)

        resp = self.client.get(self.url + '?page=1&tab=0')
        assert len(resp.context_data["track_sessions"][0]["page_obj"].object_list) == 20
        paginator = resp.context_data['track_sessions'][0]["page_obj"]
        self.assertEqual(paginator.number, 1)

        resp = self.client.get(self.url + '?page=2&tab=0')
        assert len(resp.context_data["track_sessions"][0]["page_obj"].object_list) == 10
        paginator = resp.context_data['track_sessions'][0]["page_obj"]
        self.assertEqual(paginator.number, 2)

        # page not a number shows page 1
        resp = self.client.get(self.url + '?page=one&tab=0')
        paginator = resp.context_data['track_sessions'][0]["page_obj"]
        self.assertEqual(paginator.number, 1)

        # page out of range shows last page
        resp = self.client.get(self.url + '?page=3&tab=0')
        assert len(resp.context_data["track_sessions"][0]["page_obj"].object_list) == 10
        paginator = resp.context_data['track_sessions'][0]["page_obj"]
        assert paginator.number == 2

    def test_pagination_with_tab(self):
        baker.make(TimetableSession, event_type__track=self.adult_track, _quantity=15)
        baker.make(TimetableSession, event_type__track=self.kids_track, _quantity=13)
        self.login(self.staff_user)

        resp = self.client.get(self.url + '?page=2&tab=1')  # get page 2 for the kids track tab
        assert len(resp.context_data["track_sessions"][0]["page_obj"].object_list) == 20
        assert resp.context_data["track_sessions"][1]["track"] == "Kids"
        assert len(resp.context_data["track_sessions"][1]["page_obj"].object_list) == 3

        resp = self.client.get(self.url + '?page=2&tab=3')  # invalid tab returns page 1 for all
        assert len(resp.context_data["track_sessions"][0]["page_obj"].object_list) == 20
        assert len(resp.context_data["track_sessions"][1]["page_obj"].object_list) == 20

        resp = self.client.get(self.url + '?page=2&tab=foo')  # invalid tab defaults to tab 0
        assert len(resp.context_data["track_sessions"][0]["page_obj"].object_list) == 5
        assert len(resp.context_data["track_sessions"][1]["page_obj"].object_list) == 20


class AjaxDeleteSessionTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.timetable_session = baker.make(TimetableSession)
        self.url = reverse("studioadmin:ajax_timetable_session_delete", args=(self.timetable_session.id,))

    def test_delete(self):
        self.login(self.staff_user)
        self.client.post(self.url)
        assert TimetableSession.objects.exists() is False


class ChooseEventTypeToCreateTests(EventTestMixin, TestUsersMixin, TestCase):
    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.url = reverse("studioadmin:choose_event_type_timetable_session_to_create")
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def test_only_staff(self):
        self.user_access_test(["staff"], self.url)

    def test_event_types_in_context(self):
        resp = self.client.get(self.url)
        context_event_type_ids = sorted(et.id for et in resp.context["event_types"])
        expected_event_type_ids = sorted(et.id for et in EventType.objects.all())
        assert len(context_event_type_ids) == 4
        assert context_event_type_ids == expected_event_type_ids


class TimetableSessionCreateViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.url = reverse("studioadmin:create_timetable_session", args=(self.aerial_event_type.id,))
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def form_data(self):
        return {
            "name": "test",
            "description": "",
            "event_type": self.aerial_event_type.id,
            "day": "0",
            "time": "16:00",
            "max_participants": 10,
            "duration": 90,
        }

    def test_only_staff(self):
        self.user_access_test(["staff"], self.url)

    def test_create_timetable_session(self):
        assert TimetableSession.objects.exists() is False
        resp = self.client.post(self.url, data=self.form_data())
        assert TimetableSession.objects.exists() is True
        new_session = TimetableSession.objects.first()
        assert new_session.name == "test"

    def test_redirects_to_timetable_on_save(self):
        resp = self.client.post(self.url, data=self.form_data())
        assert resp.status_code == 302
        assert resp.url == reverse("studioadmin:timetable") + f"?track={self.aerial_event_type.track.id}"


class TimetableSessionUpdateViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.timetable_session = baker.make(TimetableSession, name="foo", event_type=self.aerial_event_type)
        self.url = reverse("studioadmin:update_timetable_session", args=(self.timetable_session.id,))
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def form_data(self):
        return {
            "id": self.timetable_session.id,
            "name": "test",
            "description": "",
            "event_type": self.aerial_event_type.id,
            "day": "0",
            "time": "16:00",
            "max_participants": 10,
            "duration": 90,
        }

    def test_update_timetable_session(self):
        assert self.timetable_session.name == "foo"
        resp = self.client.post(self.url, data=self.form_data())
        self.timetable_session.refresh_from_db()
        assert self.timetable_session.name == "test"

    def test_redirects_to_timetable_on_save(self):
        resp = self.client.post(self.url, data=self.form_data())
        assert resp.status_code == 302
        assert resp.url == reverse("studioadmin:timetable") + f"?track={self.aerial_event_type.track.id}"


class TimetableUploadViewTests(EventTestMixin, TestUsersMixin, TestCase):
    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.create_events_and_course()
        self.url = reverse("studioadmin:upload_timetable")
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def test_only_staff(self):
        self.user_access_test(["staff"], self.url)

    def test_separate_forms_per_track(self):
        # track form fields are labelled with track index
        # tracks with no events are omitted
        baker.make(TimetableSession, event_type__track=self.adult_track, _quantity=2)
        baker.make(Track, name="unknown_track")
        baker.make(TimetableSession, event_type__track=self.kids_track, _quantity=2)
        resp = self.client.get(self.url)
        assert len(resp.context_data["track_sessions"]) == 2
        adult_track, kids_track = resp.context_data["track_sessions"]
        assert adult_track["track"] == "Adults"
        assert adult_track["index"] == 0
        assert kids_track["track"] == "Kids"
        assert kids_track["index"] == 1
        assert f"sessions_0" in adult_track["form"].fields
        assert f"sessions_1" in kids_track["form"].fields

    def test_with_tab(self):
        baker.make(TimetableSession, event_type__track=self.adult_track, _quantity=2)
        baker.make(Track, name="unknown_track")
        baker.make(TimetableSession, event_type__track=self.kids_track, _quantity=2)
        resp = self.client.get(self.url + "?tab=1")
        assert len(resp.context_data["track_sessions"]) == 2
        assert resp.context_data["tab"] == "1"
        assert resp.context_data["track_sessions"][1]["track"] == "Kids"

        # invalid tab defaults to 0
        resp = self.client.get(self.url + "?tab=foo")
        assert resp.context_data["tab"] == "0"

    @patch("studioadmin.forms.timezone")
    def test_upload_timetable_for_correct_track(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 7, 1, tzinfo=timezone.utc)
        baker.make(TimetableSession, event_type__track=self.adult_track, _quantity=2)
        kids_session1 = baker.make(
            TimetableSession, event_type__track=self.kids_track, day=1, time=time(10, 0),
            name="test"
        )
        kids_session2 = baker.make(
            TimetableSession, event_type__track=self.kids_track, day=3, time=time(12, 30),
            max_participants=30
        )
        assert Event.objects.filter(event_type__track=self.adult_track).count() == 6
        assert Event.objects.filter(event_type__track=self.kids_track).count() == 6
        existing_ids = list(Event.objects.filter(event_type__track=self.kids_track).values_list("id", flat=True))
        data = {
            "track": self.kids_track.id,
            "track_index": 1,
            "sessions_1": [kids_session1.id, kids_session2.id],
            "show_on_site": False,
            "start_date": "07-Jul-2020",
            "end_date": "21-Jul-2020"
        }
        # uploading session1 on Tues, session2 on Thurs between 7th and 21st Jul 2020
        # expected uploaded dates = Tues 7th, 14th, 21st and Thurs 9th, 16th
        self.client.post(self.url, data=data)
        assert Event.objects.filter(event_type__track=self.kids_track).count() == 11
        assert Event.objects.filter(event_type__track=self.adult_track).count() == 6
        uploaded_events = Event.objects.filter(event_type__track=self.kids_track).exclude(id__in=existing_ids)
        tues_uploaded_events = uploaded_events.filter(start__time=time(10, 0)).order_by("start")
        thurs_uploaded_events = uploaded_events.filter(start__time=time(12, 30)).order_by("start")
        assert [event.start.date() for event in tues_uploaded_events] == [date(2020, 7, 7), date(2020, 7, 14), date(2020, 7, 21)]
        assert [event.start.date() for event in thurs_uploaded_events] == [date(2020, 7, 9), date(2020, 7, 16)]
        for event in uploaded_events:
            assert event.show_on_site is False
        for event in tues_uploaded_events:
            assert event.name == "test"
        for event in thurs_uploaded_events:
            assert event.max_participants == 30

    @patch("studioadmin.forms.timezone")
    def test_upload_timetable_existing_events(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        tsession = baker.make(
            TimetableSession, event_type=self.aerial_event_type, day=0, time=time(10, 0), name="test"
        )
        # an event that will clash with the upload
        event = baker.make(Event, event_type=self.aerial_event_type, name="test", start=datetime(2020, 2, 3, 10, 0, tzinfo=timezone.utc))
        assert Event.objects.filter(event_type=self.aerial_event_type).count() == 4
        assert Event.objects.filter(event_type=self.aerial_event_type, name="test").count() == 1
        data = {
            "track": self.adult_track.id,
            "track_index": 0,
            "sessions_0": [tsession.id],
            "show_on_site": False,
            "start_date": "01-Feb-2020",
            "end_date": "15-Feb-2020"
        }
        self.client.post(self.url, data=data)
        # uploading session on Mon, between 1st and 15th Feb 2020
        # expected uploaded dates = Mon 3rd (duplicate), 10th
        # only one created
        assert Event.objects.filter(event_type=self.aerial_event_type).count() == 5
        uploaded = Event.objects.latest("id")
        test_events = Event.objects.filter(event_type=self.aerial_event_type, name="test")
        assert test_events.count() == 2
        assert sorted([test_event.id for test_event in test_events]) == sorted([event.id, uploaded.id])

    @patch("studioadmin.forms.timezone")
    def test_upload_timetable_subset_of_sessions(self, mock_tz):
        mock_tz.now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        tsession = baker.make(
            TimetableSession, event_type=self.aerial_event_type, day=0, time=time(10, 0), name="test"
        )
        baker.make(
            TimetableSession, event_type=self.aerial_event_type, day=3, time=time(10, 0), name="test1"
        )
        assert Event.objects.filter(event_type=self.aerial_event_type).count() == 3
        assert Event.objects.filter(event_type=self.aerial_event_type, name="test").exists() is False
        data = {
            "track": self.adult_track.id,
            "track_index": 0,
            "sessions_0": [tsession.id],
            "show_on_site": False,
            "start_date": "01-Feb-2020",
            "end_date": "15-Feb-2020"
        }
        self.client.post(self.url, data=data)
        # uploading only 1 of the 2 sessions on Mon, between 1st and 15th Feb 2020
        assert Event.objects.filter(event_type=self.aerial_event_type).count() == 5
        test_events = Event.objects.filter(event_type=self.aerial_event_type, name="test")
        assert test_events.count() == 2
        for test_event in test_events:
            assert test_event.start.weekday() == 0

    def test_upload_timetable_with_errors(self):
        baker.make(
            TimetableSession, event_type=self.aerial_event_type, day=0, time=time(10, 0), name="test"
        )
        tsession = baker.make(
            TimetableSession, event_type=self.kids_aerial_event_type, day=3, time=time(10, 0), name="test1"
        )
        data = {
            "track": self.kids_track.id,
            "track_index": 1,
            "sessions_1": [tsession.id],
            "show_on_site": False,
            "start_date": "01-Feb-2020",
            "end_date": "15-Feb-2020"
        }
        resp = self.client.post(self.url, data=data)
        track_sessions = resp.context_data["track_sessions"]
        form = track_sessions[1]["form"]
        assert form.errors == {
            "start_date": ["Date must be in the future"],
            "end_date": ["Date must be in the future"]
        }
        # goes to the tab for the invalid form
        assert resp.context_data["tab"] == 1
