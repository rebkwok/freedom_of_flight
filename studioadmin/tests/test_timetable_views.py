# -*- coding: utf-8 -*-
from model_bakery import baker

from django import forms
from django.urls import reverse
from django.test import TestCase

from booking.models import EventType
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

        self.login(self.student_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == reverse('booking:permission_denied')

        self.login(self.instructor_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == reverse('booking:permission_denied')

        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 200

    def test_sessions_by_track(self):
        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert "track_sessions" in resp.context_data
        track_sessions = resp.context_data["track_sessions"]
        assert len(track_sessions) == 2  # 2 tracks, kids and adults
        assert track_sessions[0]["track"] == "Adults"
        assert len(track_sessions[0]["queryset"].object_list) == TimetableSession.objects.filter(event_type__track=self.adult_track).count()
        assert track_sessions[1]["track"] == "Kids"
        assert len(track_sessions[1]["queryset"].object_list) == TimetableSession.objects.filter(event_type__track=self.kids_track).count()

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

        resp = self.client.get(self.url + '?page=1')
        assert len(resp.context_data["track_sessions"][0]["queryset"].object_list) == 20
        paginator = resp.context_data['track_sessions'][0]["queryset"]
        self.assertEqual(paginator.number, 1)

        resp = self.client.get(self.url + '?page=2&tab=0')
        assert len(resp.context_data["track_sessions"][0]["queryset"].object_list) == 10
        paginator = resp.context_data['track_sessions'][0]["queryset"]
        self.assertEqual(paginator.number, 2)

        # page not a number shows page 1
        resp = self.client.get(self.url + '?page=one')
        paginator = resp.context_data['track_sessions'][0]["queryset"]
        self.assertEqual(paginator.number, 1)

        # page out of range shows page 1
        resp = self.client.get(self.url + '?page=3')
        assert len(resp.context_data["track_sessions"][0]["queryset"].object_list) == 20
        paginator = resp.context_data['track_sessions'][0]["queryset"]
        assert paginator.number == 1

    def test_pagination_with_tab(self):
        baker.make(TimetableSession, event_type__track=self.adult_track, _quantity=15)
        baker.make(TimetableSession, event_type__track=self.kids_track, _quantity=13)
        self.login(self.staff_user)

        resp = self.client.get(self.url + '?page=2&tab=1')  # get page 2 for the kids track tab
        assert len(resp.context_data["track_sessions"][0]["queryset"].object_list) == 20
        assert resp.context_data["track_sessions"][1]["track"] == "Kids"
        assert len(resp.context_data["track_sessions"][1]["queryset"].object_list) == 3

        resp = self.client.get(self.url + '?page=2&tab=3')  # invalid tab returns page 1 for all
        assert len(resp.context_data["track_sessions"][0]["queryset"].object_list) == 20
        assert len(resp.context_data["track_sessions"][1]["queryset"].object_list) == 20

        resp = self.client.get(self.url + '?page=2&tab=foo')  # invalid tab defaults to tab 0
        assert len(resp.context_data["track_sessions"][0]["queryset"].object_list) == 5
        assert len(resp.context_data["track_sessions"][1]["queryset"].object_list) == 20


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


class TimetableUploadViewTests(EventTestMixin, TestUsersMixin, TestCase):
    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.url = reverse("studioadmin:upload_timetable")
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

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

    def test_separate_forms_per_track(self):
        # track form fields are labelled with track index
        # tracks with no events are omitted
        pass

    def test_upload_timetable_for_correct_track(self):
        pass

    def test_upload_timetable_existing_events(self):
        pass

    def test_upload_timetable_subset_of_sessions(self):
        pass
