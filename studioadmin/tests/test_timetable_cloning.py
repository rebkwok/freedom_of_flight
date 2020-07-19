from datetime import time
from model_bakery import baker

from django.urls import reverse
from django.test import TestCase

from common.test_utils import TestUsersMixin, EventTestMixin
from timetable.models import TimetableSession


class CloneTimetableTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.login(self.staff_user)
        self.timetable_session = baker.make(
            TimetableSession, day=0, time=time(10, 0), name="Original session", max_participants=4,
            event_type=self.aerial_event_type,
        )
        self.url = reverse("studioadmin:clone_timetable_session", args=(self.timetable_session.id,))

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

    def test_name_prepopulated(self):
        resp = self.client.get(self.url)
        form = resp.context_data["form"]
        assert form.initial["name"] == self.timetable_session.name

    def test_clone_single_day(self):
        data = {
            "days": ["2"],
            "time": "11:00",
            "name": "",  # no name, default to original name
            "submit": "Clone",
        }
        self.client.post(self.url, data)
        cloned_timetable_session = TimetableSession.objects.latest("id")
        assert cloned_timetable_session.id != self.timetable_session.id
        # cloned properties
        assert cloned_timetable_session.name == self.timetable_session.name
        assert cloned_timetable_session.max_participants == self.timetable_session.max_participants
        # from form
        assert cloned_timetable_session.day == "2"
        assert cloned_timetable_session.time == time(11, 0)

    def test_clone_with_new_name(self):
        data = {
            "days": ["1"],
            "time": "10:00",
            "name": "A cloned session",  # no name, default to original name
            "submit": "Clone",
        }
        self.client.post(self.url, data)
        cloned_timetable_session = TimetableSession.objects.latest("id")
        assert cloned_timetable_session.id != self.timetable_session.id
        # cloned properties
        assert cloned_timetable_session.name == "A cloned session"
        assert cloned_timetable_session.max_participants == self.timetable_session.max_participants
        # from form
        assert cloned_timetable_session.day == "1"
        assert cloned_timetable_session.time == time(10, 0)

    def test_clone_already_exists(self):
        # make another timetable_session with the same name, event type, day and time we're about to try to clone to
        baker.make(
            TimetableSession, day=0, time=time(10, 0), name="Original session",
            event_type=self.aerial_event_type,
        )
        assert TimetableSession.objects.filter(name="Original session").count() == 2
        data = {
            "days": ["0"],
            "time": "10:00",
            "name": "Original session",
            "submit": "Clone",
        }
        resp = self.client.post(self.url, data, follow=True)
        assert TimetableSession.objects.filter(name="Original session").count() == 2
        assert "Session with name Original session at 10:00 already exists for the requested day(s) (Monday)" \
               in resp.rendered_content

    def test_redirect_to_timetable_with_track(self):
        data = {
            "days": ["2"],
            "time": "11:00",
            "name": "",  # no name, default to original name
            "submit": "Clone",
        }
        resp = self.client.post(self.url, data)
        assert resp.url == reverse("studioadmin:timetable") + f"?track={self.timetable_session.event_type.track.id}"

    def test_clone_multiple_days(self):
        data = {
            "days": ["0", "1", "2"],  # Monday is not cloned, already exists
            "time": "10:00",
            "name": "",  # no name, default to original name
            "submit": "Clone",
        }
        self.client.post(self.url, data)
        timetable_sessions = TimetableSession.objects.filter(name="Original session")
        assert timetable_sessions.count() == 3
        cloned_sessions = timetable_sessions.exclude(id=self.timetable_session.id)
        assert cloned_sessions.count() == 2
        for cloned_timetable_session in cloned_sessions:
            assert cloned_timetable_session.name == self.timetable_session.name
            assert cloned_timetable_session.max_participants == self.timetable_session.max_participants
            assert cloned_timetable_session.time == time(10, 0)

