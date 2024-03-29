from datetime import datetime
from datetime import timezone as dt_timezone

import random

from django.contrib.auth.models import User, Group
from django.utils import timezone
from django.shortcuts import reverse

from model_bakery import baker

from accounts.models import (
    DisclaimerContent, has_active_data_privacy_agreement, DataPrivacyPolicy,
    SignedDataPrivacy, OnlineDisclaimer, has_active_disclaimer, NonRegisteredDisclaimer,
    UserProfile, ChildUserProfile, ArchivedDisclaimer
)
from booking.models import Event, EventType, Course, Track


def make_disclaimer_content(**kwargs):
    defaults = {
        "disclaimer_terms": f"test content {random.randint(0, 100000)}",
        "form": [],
        "version": None,
        "is_draft": False
    }
    data = {**defaults, **kwargs}
    return DisclaimerContent.objects.create(**data)


def make_online_disclaimer(**kwargs):
    if "version" not in kwargs:
        kwargs["version"] = DisclaimerContent.current_version()
    defaults = {
        "health_questionnaire_responses": {},
        "terms_accepted": True,
        "emergency_contact_name": "test",
        "emergency_contact_relationship": "test",
        "emergency_contact_phone": "123",
    }
    data = {**defaults, **kwargs}
    return OnlineDisclaimer.objects.create(**data)


def make_nonregistered_disclaimer(**kwargs):
    if "version" not in kwargs:
        kwargs["version"] = DisclaimerContent.current_version()
    defaults = {
        "first_name": "test",
        "last_name": "user",
        "email": "test@test.com",
        "address": "test",
        "postcode": "test",
        "date_of_birth": datetime(1990, 6, 7, tzinfo=dt_timezone.utc),
        "phone": "123455",
        "event_date": datetime(2020, 10, 1, tzinfo=dt_timezone.utc),
        "health_questionnaire_responses": {},
        "terms_accepted": True,
        "emergency_contact_name": "test",
        "emergency_contact_relationship": "test",
        "emergency_contact_phone": "123",
    }
    data = {**defaults, **kwargs}
    return NonRegisteredDisclaimer.objects.create(**data)


def make_archived_disclaimer(**kwargs):
    if "version" not in kwargs:
        kwargs["version"] = DisclaimerContent.current_version()
    defaults = {
        "name": "Test User",
        "address": "test",
        "postcode": "test",
        "date_of_birth": datetime(1990, 6, 7, tzinfo=dt_timezone.utc),
        "date_archived": timezone.now(),
        "event_date": None,
        "phone": "123455",
        "health_questionnaire_responses": {},
        "terms_accepted": True,
        "emergency_contact_name": "test",
        "emergency_contact_relationship": "test",
        "emergency_contact_phone": "123",
    }
    data = {**defaults, **kwargs}
    return ArchivedDisclaimer.objects.create(**data)


class TestUsersMixin:

    def create_admin_users(self):
        self.staff_user = User.objects.create_user(
            username='staff@test.com', email='staff@test.com', password='test',
            first_name="Staff", last_name="User"
        )
        self.staff_user.is_staff = True
        self.staff_user.save()

        self.instructor_user = User.objects.create_user(
            username='instuctor@test.com', email='instuctor@test.com', password='test',
            first_name="Instuctor", last_name="User"
        )
        instructor_group, _ = Group.objects.get_or_create(name="instructors")
        self.instructor_user.groups.add(instructor_group)
        UserProfile.objects.create(
            user=self.staff_user, address="test", postcode="test",
            date_of_birth=datetime(1990, 6, 7, tzinfo=dt_timezone.utc), phone="123455",
            student=False, manager=False
        )
        UserProfile.objects.create(
            user=self.instructor_user, address="test", postcode="test",
            date_of_birth=datetime(1990, 6, 7, tzinfo=dt_timezone.utc), phone="123455",
            student=False, manager=False
        )

    def create_users(self):
        self.student_user = User.objects.create_user(
            username='student@test.com', email='student@test.com', password='test',
            first_name="Student", last_name="User"
        )
        self.student_user1 = User.objects.create_user(
            username='student1@test.com', email='student1@test.com', password='test',
            first_name="Student1", last_name="User"
        )

        self.manager_user = User.objects.create_user(
            username='manager@test.com', email='manager@test.com', password='test',
            first_name="Manager", last_name="User"
        )

        self.child_user = User.objects.create(
            username='random-user-name', first_name="Child", last_name="User"
        )
        self.child_user.set_unusable_password()

        UserProfile.objects.create(
            user=self.student_user, address="test1", postcode="test1",
            date_of_birth=datetime(1980, 6, 7, tzinfo=dt_timezone.utc), phone="123456",
            student=True, manager=False
        )
        UserProfile.objects.create(
            user=self.student_user1, address="test2", postcode="test12",
            date_of_birth=datetime(1990, 6, 7, tzinfo=dt_timezone.utc), phone="789",
            student=True, manager=False
        )
        parent_profile = UserProfile.objects.create(
            user=self.manager_user, address="test3", postcode="test123",
            date_of_birth=datetime(1970, 6, 7, tzinfo=dt_timezone.utc), phone="789",
            student=False, manager=True
        )
        ChildUserProfile.objects.create(
            user=self.child_user, address="test3", postcode="test123",
            date_of_birth=datetime(2014, 6, 7, tzinfo=dt_timezone.utc), phone="789",
            parent_user_profile=parent_profile
        )

    def login(self, user, password=None):
        self.client.login(username=user.username, password=password or "test")

    def make_data_privacy_agreement(self, user):
        if not has_active_data_privacy_agreement(user):
            if DataPrivacyPolicy.current_version() == 0:
                baker.make(DataPrivacyPolicy, content='Foo', version=1)
            baker.make(SignedDataPrivacy, user=user, version=DataPrivacyPolicy.current_version())

    def make_disclaimer(self, user):
        if not has_active_disclaimer(user):
            if DisclaimerContent.current_version() == 0:
                make_disclaimer_content(version=1)
            return make_online_disclaimer(user=user, version=DisclaimerContent.current_version())

    def user_access_test(self, allowed, url, expected_redirect=None, post_data=None):
        users = {
            "student": self.student_user,
            "staff": self.staff_user,
            "instructor": self.instructor_user
        }
        for user_type, user in users.items():
            self.login(user)
            if post_data is not None:
                resp = self.client.post(url, data=post_data)
            else:
                resp = self.client.get(url)
            if user_type in allowed:
                if expected_redirect is not None:
                    assert resp.status_code == 302
                    assert resp.url == expected_redirect
                else:
                    assert resp.status_code == 200
            else:
                assert resp.status_code == 302
                assert resp.url == reverse("booking:permission_denied")


class EventTestMixin:

    def create_test_setup(self):
        self.create_tracks_and_event_types()
        self.create_events_and_course()
    
    @classmethod
    def create_cls_tracks_and_event_types(cls):
        cls.adult_track = baker.make(Track, name="Adults", default=True)
        cls.kids_track = baker.make(Track, name="Kids")

        cls.aerial_event_type = baker.make(EventType, name="aerial", track=cls.adult_track)
        cls.floor_event_type = baker.make(EventType, name="floor", track=cls.adult_track)
        cls.kids_aerial_event_type = baker.make(EventType, name="aerial", track=cls.kids_track)
        cls.kids_floor_event_type = baker.make(EventType, name="floor", track=cls.kids_track)

    def create_tracks_and_event_types(self):
        self.adult_track = baker.make(Track, name="Adults", default=True)
        self.kids_track = baker.make(Track, name="Kids")

        self.aerial_event_type = baker.make(EventType, name="aerial", track=self.adult_track)
        self.floor_event_type = baker.make(EventType, name="floor", track=self.adult_track)
        self.kids_aerial_event_type = baker.make(EventType, name="aerial", track=self.kids_track)
        self.kids_floor_event_type = baker.make(EventType, name="floor", track=self.kids_track)

    def create_events_and_course(self):
        self.aerial_events = baker.make_recipe("booking.future_event", event_type=self.aerial_event_type,  _quantity=2)
        self.floor_events = baker.make_recipe("booking.future_event", event_type=self.floor_event_type,  _quantity=3)
        self.kids_aerial_events = baker.make_recipe("booking.future_event", event_type=self.kids_aerial_event_type,  _quantity=3)
        self.kids_floor_events = baker.make_recipe("booking.future_event", event_type=self.kids_floor_event_type,  _quantity=3)
        self.course = baker.make(
            Course, name="This month's aerial course", event_type=self.aerial_event_type, number_of_events=3,
            max_participants=2, show_on_site=True
        )
        self.course_event = baker.make_recipe(
            "booking.future_event", event_type=self.aerial_event_type, course=self.course,
        )
