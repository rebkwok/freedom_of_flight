import os
import pytest

from unittest.mock import patch

from model_bakery import baker
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

from django.core.cache import cache
from django.urls import reverse
from django.test import TestCase
from django.contrib.auth.models import Permission
from django.utils import timezone

from accounts.models import DataPrivacyPolicy, SignedDataPrivacy
from accounts.models import has_active_data_privacy_agreement

from booking.models import Event, Booking, Course, Track, EventType
from booking.views import EventListView, EventDetailView
from common.test_utils import make_disclaimer_content, make_online_disclaimer, TestUsersMixin


class EventTestMixin:
    @classmethod
    def setUpTestData(cls):
        cls.adult_track = baker.make(Track, name="Adults", default=True)
        cls.kids_track = baker.make(Track, name="Kids")

        cls.aerial_event_type = baker.make(EventType, name="aerial", track=cls.adult_track)
        cls.floor_event_type = baker.make(EventType, name="floor", track=cls.adult_track)
        cls.kids_aerial_event_type = baker.make(EventType, name="aerial", track=cls.kids_track)
        cls.kids_floor_event_type = baker.make(EventType, name="floor", track=cls.kids_track)

        cls.aerial_events = baker.make_recipe("booking.future_event", event_type=cls.aerial_event_type,  _quantity=2)
        cls.floor_events = baker.make_recipe("booking.future_event", event_type=cls.floor_event_type,  _quantity=3)
        cls.kids_aerial_events = baker.make_recipe("booking.future_event", event_type=cls.kids_aerial_event_type,  _quantity=3)
        cls.kids_floor_events = baker.make_recipe("booking.future_event", event_type=cls.kids_floor_event_type,  _quantity=3)
        cls.course = baker.make(Course, course_type__event_type=cls.aerial_event_type)
        cls.course_event = baker.make_recipe(
            "booking.future_event", event_type=cls.aerial_event_type, course=cls.course
        )


class EventListViewTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.url = reverse('booking:schedule')
        cls.adult_url = reverse('booking:events', args=(cls.adult_track.slug,))
        cls.kids_url = reverse('booking:events', args=(cls.kids_track.slug,))

    def setUp(self):
        self.create_users()
        self.login(self.student_user)
        self.make_data_privacy_agreement(self.student_user)
        self.make_data_privacy_agreement(self.manager_user)

    def test_schedule(self):
        """
        With no track, redirects to the default track
        """
        self.client.logout()
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == self.adult_url

        resp = self.client.get(self.url, follow=True)
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 6
        assert "Log in</a> to book</span>" in resp.rendered_content

    def test_event_list_logged_in_no_data_protection_policy(self):
        DataPrivacyPolicy.objects.all().delete()
        SignedDataPrivacy.objects.all().delete()
        assert has_active_data_privacy_agreement(self.student_user) is False
        resp = self.client.get(self.adult_url)
        assert resp.status_code == 200

        DataPrivacyPolicy.objects.create(content='Foo')
        cache.clear()
        resp = self.client.get(self.adult_url)
        assert resp.status_code == 302
        assert reverse('accounts:data_privacy_review') + '?next=/adults/' in resp.url

        self.make_data_privacy_agreement(self.student_user)
        resp = self.client.get(self.adult_url)
        assert resp.status_code == 200

    def test_event_list_past_event(self):
        """
        Test that past events is not listed
        """
        baker.make_recipe('booking.past_event', event_type=self.aerial_event_type)
        # check there are now 7 events
        assert Event.objects.filter(event_type__track=self.adult_track).count() == 7
        resp = self.client.get(self.adult_url)

        # event listing should still only show future events
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 6

    def test_event_list_past_event_within_10_mins_is_listed(self):
        """
        Test that past events is not listed
        """
        past = baker.make_recipe(
            'booking.past_event', event_type=self.aerial_event_type, start=timezone.now() - timedelta(minutes=30)
        )
        # check there are now 7 events
        assert Event.objects.filter(event_type__track=self.adult_track).count() == 7
        resp = self.client.get(self.adult_url)

        # event listing should still only show future events
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 6
        past.start = timezone.now() - timedelta(minutes=7)
        past.save()
        resp = self.client.get(self.adult_url)
        # event listing should shows future events plus pas within 10 mins
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 7

    def test_event_list_with_anonymous_user(self):
        """
        Test that no booked_events in context
        """
        self.client.logout()
        resp = self.client.get(self.adult_url)
        assert 'booked_event_ids' not in resp.context

        self.login(self.student_user)
        resp = self.client.get(self.adult_url)
        assert 'booked_event_ids' in resp.context

    def test_event_list_with_booked_events(self):
        """
        test that booked events are shown on listing
        """
        resp = self.client.get(self.adult_url)
        # check there are no booked events yet
        assert len(resp.context_data['booked_event_ids']) == 0

        # create a booking for this user
        event = self.aerial_events[0]
        baker.make(Booking, user=self.student_user, event=event)
        resp = self.client.get(self.adult_url)
        booked_events = [event for event in resp.context_data['booked_event_ids']]
        assert len(booked_events) == 1
        assert event.id in booked_events

    def test_event_list_with_booked_events_manager_user(self):
        """
        test that booked events are shown on listing
        """
        self.login(self.manager_user)
        resp = self.client.get(self.kids_url)
        # user is not a student, view as user set to child user

        # check there are no booked events yet
        assert len(resp.context_data['booked_event_ids']) == 0

        # create a booking for the managed user
        event = self.kids_aerial_events[0]
        baker.make(Booking, user=self.child_user, event=event)
        resp = self.client.get(self.kids_url)
        booked_events = [event for event in resp.context_data['booked_event_ids']]
        assert len(booked_events) == 1
        assert event.id in booked_events

    def test_event_list_booked_events_no_disclaimer(self):
        make_disclaimer_content()
        resp = self.client.get(self.adult_url)
        assert "Complete a disclaimer" in resp.rendered_content

    def test_event_list_booked_events(self):
        """
        test that booked events are shown on listing
        """
        self.make_disclaimer(self.student_user)
        for event in self.aerial_events:
            # create a booking for this user for all events
            baker.make(
                Booking, block__dropin_block_config__event_type=self.aerial_event_type,
                user=self.student_user, event=event
            )

        resp = self.client.get(self.adult_url)
        booked_events = [event for event in resp.context_data['booked_event_ids']]
        assert len(booked_events) == 2
        # cancel button shown for the booked events
        assert 'Cancel' in resp.rendered_content
        # course details button shown for the unbooked course
        assert 'Course details' in resp.rendered_content

    def test_cancelled_events_are_not_listed(self):
        resp = self.client.get(self.adult_url)
        baker.make_recipe('booking.future_event', event_type=self.aerial_event_type, cancelled=True)
        assert Event.objects.filter(event_type__track=self.adult_track).count() == 7
        resp = self.client.get(self.adult_url)
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 6

    def test_show_on_site_events_only_are_not_listed(self):
        baker.make_recipe('booking.future_event', event_type=self.aerial_event_type, show_on_site=False)
        assert Event.objects.filter(event_type__track=self.adult_track).count() == 7
        resp = self.client.get(self.adult_url)
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 6

    # def test_online_event_video_link(self):
    #     online_class = baker.make_recipe(
    #         'booking.future_CL', event_type__subtype="Online class", video_link="https://foo.test"
    #     )
    #     active_video_link_id = f"video_link_id_{online_class.id}"
    #     disabled_video_link_id = f"video_link_id_disabled_{online_class.id}"
    #
    #     url = reverse('booking:lessons')
    #
    #     # User is not booked, no links shown
    #     resp = self.client.get(url)
    #     assert active_video_link_id not in resp.rendered_content
    #     assert disabled_video_link_id not in resp.rendered_content
    #
    #     booking = baker.make_recipe("booking.booking", event=online_class, user=self.user)
    #     # User is booked but not paid, no links shown
    #     resp = self.client.get(url)
    #     assert active_video_link_id not in resp.rendered_content
    #     assert disabled_video_link_id not in resp.rendered_content
    #
    #     # User is booked and paid but class is more than 20 mins ahead
    #     booking.paid = True
    #     booking.save()
    #     resp = self.client.get(url)
    #     assert active_video_link_id not in resp.rendered_content
    #     assert disabled_video_link_id in resp.rendered_content
    #
    #     # User is booked and paid, class is less than 20 mins ahead
    #     online_class.date = timezone.now() + timedelta(minutes=10)
    #     online_class.save()
    #     resp = self.client.get(url)
    #     assert active_video_link_id in resp.rendered_content
    #     assert disabled_video_link_id not in resp.rendered_content
    #
    #     # User is no show
    #     booking.no_show = True
    #     booking.save()
    #     resp = self.client.get(url)
    #     assert active_video_link_id not in resp.rendered_content
    #     assert disabled_video_link_id not in resp.rendered_content
    #
    #     # user has cancelled
    #     booking.no_show = False
    #     booking.status = "CANCELLED"
    #     booking.save()
    #     resp = self.client.get(url)
    #     assert active_video_link_id not in resp.rendered_content
    #     assert disabled_video_link_id not in resp.rendered_content


class EventDetailViewTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.event = cls.aerial_events[0]

    def setUp(self):
        self.create_users()
        self.login(self.student_user)
        self.make_data_privacy_agreement(self.student_user)
        self.make_data_privacy_agreement(self.manager_user)

    def test_get(self):
        url = reverse('booking:event', args=[self.event.slug])
        resp = self.client.get(url)
        assert resp.status_code == 200

    def test_with_booked_event(self):
        """
        Test that booked event is shown as booked
        """
        #create a booking for this event and user
        url = reverse('booking:event', args=[self.event.slug])
        baker.make(Booking, event=self.event, user=self.student_user)
        resp = self.client.get(url)
        assert "You have booked for this event" in resp.rendered_content

    def test_with_booked_event_for_managed_user(self):
        #create a booking for this event and user
        self.login(self.manager_user)
        url = reverse('booking:event', args=[self.event.slug])
        baker.make(Booking, event=self.event, user=self.child_user)
        resp = self.client.get(url)
        assert f"{self.child_user.first_name} {self.child_user.last_name} has booked for this event" in resp.rendered_content


class CourseListViewTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.course_event1 = baker.make_recipe(
            "booking.future_event", event_type=cls.aerial_event_type, course=cls.course
        )
        cls.url = reverse("booking:course_events", args=(cls.course.slug,))

    def setUp(self):
        self.create_users()
        self.login(self.student_user)
        self.make_data_privacy_agreement(self.student_user)
        self.make_data_privacy_agreement(self.manager_user)

    def test_course_list(self):
        resp = self.client.get(self.url)
        # course events are displayed
        response_events = sum(list(resp.context_data['events_by_date'].values()), [])
        assert len(response_events) == 2
        for event in response_events:
            assert event.course == self.course

    def test_course_list_shows_past_events(self):
        baker.make_recipe(
            "booking.past_event", event_type=self.aerial_event_type, course=self.course
        )
        resp = self.client.get(self.url)
        # course events are displayed
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 3

    def test_course_list_with_booked_course(self):
        baker.make(Booking, event=self.course_event, user=self.student_user)
        baker.make(Booking, event=self.course_event1, user=self.student_user)
        resp = self.client.get(self.url)
        assert resp.context_data["already_booked"] is True

    def test_course_list_with_booked_events_manager_user(self):
        """
        test that booked events are shown on listing
        """
        self.login(self.manager_user)
        resp = self.client.get(self.url)
        # user is not a student, view as user set to child user
        assert "Complete a disclaimer" in resp.rendered_content

        resp = self.client.get(self.url)
        self.make_disclaimer(self.child_user)
        assert "Payment Options" in resp.rendered_content
        # check there are no booked events yet
        assert resp.context_data["already_booked"] is False

        # create a booking for the managed user
        baker.make(Booking, event=self.course_event, user=self.child_user)
        baker.make(Booking, event=self.course_event1, user=self.child_user)
        resp = self.client.get(self.url)
        assert "Payment Options" not in resp.rendered_content
        assert resp.context_data["already_booked"] is True
