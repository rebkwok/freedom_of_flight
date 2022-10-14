from datetime import datetime
from datetime import timezone as dt_timezone

from django.contrib.auth.models import User, Group

import pytest

from model_bakery import baker

from accounts.models import UserProfile, ChildUserProfile
from booking.models import Block, BlockConfig, Booking, Course, EventType
from booking.tests.test_course_views import CourseListViewTests
from common.test_utils import TestUsersMixin


pytestmark = pytest.mark.django_db


def make_agreements(user):
    mixin = TestUsersMixin()
    mixin.make_data_privacy_agreement(user)
    mixin.make_disclaimer(user)


@pytest.fixture
def student_user(django_user_model):
    student_user = django_user_model.objects.create_user(
        username='student@test.com', email='student@test.com', password='test',
        first_name="Student", last_name="User"
    )
    UserProfile.objects.create(
        user=student_user, address="test1", postcode="test1",
        date_of_birth=datetime(1980, 6, 7, tzinfo=dt_timezone.utc), phone="123456",
        student=True, manager=False
    )
    make_agreements(student_user)
    yield student_user


@pytest.fixture
def manager_user(django_user_model):
    manager_user = django_user_model.objects.create_user(
        username='manager@test.com', email='manager@test.com', password='test',
        first_name="Manager", last_name="User"
    )
    UserProfile.objects.create(
        user=manager_user, address="test3", postcode="test123",
        date_of_birth=datetime(1970, 6, 7, tzinfo=dt_timezone.utc), phone="789",
        student=False, manager=True
    )
    make_agreements(manager_user)
    yield manager_user


@pytest.fixture
def child_user(django_user_model, manager_user):
    child_user = django_user_model.objects.create(
        username='random-user-name', first_name="Child", last_name="User"
    )
    child_user.set_unusable_password()
    ChildUserProfile.objects.create(
        user=child_user, address="test3", postcode="test123",
        date_of_birth=datetime(2014, 6, 7, tzinfo=dt_timezone.utc), phone="789",
        parent_user_profile=manager_user.userprofile
    )
    make_agreements(child_user)
    yield child_user


@pytest.fixture
def users(django_user_model, student_user, child_user, manager_user):
    staff_user = django_user_model.objects.create_user(
        username='staff@test.com', email='staff@test.com', password='test',
        first_name="Staff", last_name="User"
    )
    staff_user.is_staff = True
    staff_user.save()

    instructor_user = django_user_model.objects.create_user(
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
    student_user1 = django_user_model.objects.create_user(
        username='student1@test.com', email='student1@test.com', password='test',
        first_name="Student1", last_name="User"
    )

    UserProfile.objects.create(
        user=student_user1, address="test2", postcode="test12",
        date_of_birth=datetime(1990, 6, 7, tzinfo=dt_timezone.utc), phone="789",
        student=True, manager=False
    )
    
    users = {
        "staff_user": staff_user,
        "instructor_user": instructor_user,
        "student_user1": student_user1,
    }
    for user in users.values():
        make_agreements(user)
    users.update(
        {
            "student_user": student_user,
            "manager_user": manager_user,
            "child_user": child_user
        }
    )        
    yield users


@pytest.fixture
def event_type():
    yield baker.make(EventType, name="test_event_type", track__name="test_track")


@pytest.fixture
def course_cart_block_config(event_type):
    # make add-to-cart config
    yield baker.make(
        BlockConfig, event_type=event_type, course=True, size=2, active=True
    )


@pytest.fixture
def dropin_cart_block_config(event_type):
    # make add-to-cart config
    yield baker.make(
        BlockConfig, event_type=event_type, course=False, size=1, active=True
    )


@pytest.fixture
def event(event_type, dropin_cart_block_config):
    yield baker.make_recipe("booking.future_event", event_type=event_type, max_participants=2)


@pytest.fixture
def course(course_cart_block_config, event_type):
    # make configured course
    course1 = baker.make(
        Course, event_type=event_type, max_participants=2, number_of_events=2,
        show_on_site=True,
    )
    baker.make_recipe(
        "booking.future_event", event_type=event_type, course=course1, _quantity=2
    )
    yield course1


@pytest.fixture
def course_event(course):
    course.events.first().delete()
    course_event = baker.make_recipe(
        "booking.future_event", event_type=event_type, max_participants=2,
        course=course    
    )
    yield course_event


@pytest.fixture
def drop_in_course(dropin_cart_block_config, course):
    course.allow_drop_in = True
    course.save()
    yield course


@pytest.fixture
def course_block(course_cart_block_config, student_user):
    yield baker.make(Block, user=student_user, block_config=course_cart_block_config, paid=True)


@pytest.fixture
def dropin_block(dropin_cart_block_config, student_user):
    yield baker.make(Block, user=student_user, block_config=dropin_cart_block_config, paid=True)


@pytest.fixture
def booking(student_user, event, dropin_block):
    yield baker.make(Booking, user=student_user, event=event, block=dropin_block)


@pytest.fixture
def course_bookings(course, student_user, course_block):
    for event in course.events.all():
        baker.make(Booking, user=student_user, event=event, block=course_block)
    yield Booking.objects.filter(event__course=course)


@pytest.fixture
def drop_in_course_bookings(drop_in_course, student_user, course_block):
    for event in drop_in_course.events.all():
        baker.make(Booking, user=student_user, event=event, block=course_block)
    yield Booking.objects.filter(event__course=drop_in_course)