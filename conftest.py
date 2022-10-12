from datetime import datetime
from datetime import timezone as dt_timezone

from django.contrib.auth.models import User, Group

import pytest

from model_bakery import baker

from accounts.models import UserProfile, ChildUserProfile
from booking.models import BlockConfig
from common.test_utils import TestUsersMixin

pytestmark = pytest.mark.django_db

@pytest.fixture
def users(client):
    staff_user = User.objects.create_user(
        username='staff@test.com', email='staff@test.com', password='test',
        first_name="Staff", last_name="User"
    )
    staff_user.is_staff = True
    staff_user.save()

    instructor_user = User.objects.create_user(
        username='instuctor@test.com', email='instuctor@test.com', password='test',
        first_name="Instuctor", last_name="User"
    )
    instructor_group, _ = Group.objects.get_or_create(name="instructors")
    instructor_user.groups.add(instructor_group)
    UserProfile.objects.create(
        user=staff_user, address="test", postcode="test",
        date_of_birth=datetime(1990, 6, 7, tzinfo=dt_timezone.utc), phone="123455",
        student=False, manager=False
    )
    UserProfile.objects.create(
        user=instructor_user, address="test", postcode="test",
        date_of_birth=datetime(1990, 6, 7, tzinfo=dt_timezone.utc), phone="123455",
        student=False, manager=False
    )
    student_user = User.objects.create_user(
        username='student@test.com', email='student@test.com', password='test',
        first_name="Student", last_name="User"
    )
    student_user1 = User.objects.create_user(
        username='student1@test.com', email='student1@test.com', password='test',
        first_name="Student1", last_name="User"
    )

    manager_user = User.objects.create_user(
        username='manager@test.com', email='manager@test.com', password='test',
        first_name="Manager", last_name="User"
    )

    child_user = User.objects.create(
        username='random-user-name', first_name="Child", last_name="User"
    )
    child_user.set_unusable_password()

    UserProfile.objects.create(
        user=student_user, address="test1", postcode="test1",
        date_of_birth=datetime(1980, 6, 7, tzinfo=dt_timezone.utc), phone="123456",
        student=True, manager=False
    )
    UserProfile.objects.create(
        user=student_user1, address="test2", postcode="test12",
        date_of_birth=datetime(1990, 6, 7, tzinfo=dt_timezone.utc), phone="789",
        student=True, manager=False
    )
    parent_profile = UserProfile.objects.create(
        user=manager_user, address="test3", postcode="test123",
        date_of_birth=datetime(1970, 6, 7, tzinfo=dt_timezone.utc), phone="789",
        student=False, manager=True
    )
    ChildUserProfile.objects.create(
        user=child_user, address="test3", postcode="test123",
        date_of_birth=datetime(2014, 6, 7, tzinfo=dt_timezone.utc), phone="789",
        parent_user_profile=parent_profile
    )
    users = {
        "staff_user": staff_user,
        "instructor_user": instructor_user,
        "student_user": student_user,
        "student_user1": student_user1,
        "manager_user": manager_user,
        "child_user": child_user
    }
    for user in users.values():
        mixin = TestUsersMixin()
        mixin.make_data_privacy_agreement(user)
        mixin.make_disclaimer(user)
    yield users
