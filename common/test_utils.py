from datetime import datetime
import random

from django.contrib.auth.models import User
from django.utils import timezone

from model_bakery import baker

from accounts.models import (
    DisclaimerContent, has_active_data_privacy_agreement, DataPrivacyPolicy,
    SignedDataPrivacy, OnlineDisclaimer, has_active_disclaimer, NonRegisteredDisclaimer,
    UserProfile, ChildUserProfile
)

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
    defaults={
        "health_questionnaire_responses": [],
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
    defaults={
        "first_name": "test",
        "last_name": "user",
        "email": "test@test.com",
        "address": "test",
        "postcode": "test",
        "date_of_birth": datetime(1990, 6, 7, tzinfo=timezone.utc),
        "phone": "123455",
        "event_date": datetime(2020, 10, 1, tzinfo=timezone.utc),
        "health_questionnaire_responses": [],
        "terms_accepted": True,
        "emergency_contact_name": "test",
        "emergency_contact_relationship": "test",
        "emergency_contact_phone": "123",
    }
    data = {**defaults, **kwargs}
    return NonRegisteredDisclaimer.objects.create(**data)


class TestUsersMixin:

    def create_users(self):
        self.staff_user = User.objects.create_user(
            username='staff@test.com', email='staff@test.com', password='test',
            first_name="Staff", last_name="User"
        )
        self.staff_user.is_staff = True
        self.staff_user.save()
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
            user=self.staff_user, address="test", postcode="test",
            date_of_birth=datetime(1990, 6, 7, tzinfo=timezone.utc), phone="123455",
            student=False, manager=False
        )
        UserProfile.objects.create(
            user=self.student_user, address="test1", postcode="test1",
            date_of_birth=datetime(1980, 6, 7, tzinfo=timezone.utc), phone="123456",
            student=True, manager=False
        )
        UserProfile.objects.create(
            user=self.student_user1, address="test2", postcode="test12",
            date_of_birth=datetime(1990, 6, 7, tzinfo=timezone.utc), phone="789",
            student=True, manager=False
        )
        parent_profile = UserProfile.objects.create(
            user=self.manager_user, address="test3", postcode="test123",
            date_of_birth=datetime(1970, 6, 7, tzinfo=timezone.utc), phone="789",
            student=False, manager=True
        )
        ChildUserProfile.objects.create(
            user=self.child_user, address="test3", postcode="test123",
            date_of_birth=datetime(2014, 6, 7, tzinfo=timezone.utc), phone="789",
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
            make_online_disclaimer(user=user, version=DisclaimerContent.current_version())