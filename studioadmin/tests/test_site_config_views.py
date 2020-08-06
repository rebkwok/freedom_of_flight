# -*- coding: utf-8 -*-
from model_bakery import baker
import json
import pytest

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from booking.models import Track
from common.test_utils import EventTestMixin, TestUsersMixin, make_disclaimer_content


class TrackListViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()
        cls.url = reverse("studioadmin:tracks")

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def test_toggle_track_default(self):
        # self.adult_track is set to default
        assert self.adult_track.default is True
        # toggle off
        self.client.get(reverse("studioadmin:toggle_track_default", args=(self.adult_track.id,)))
        self.adult_track.refresh_from_db()
        assert self.adult_track.default is False

        # toggle on again
        self.client.get(reverse("studioadmin:toggle_track_default", args=(self.adult_track.id,)))
        self.adult_track.refresh_from_db()
        assert self.adult_track.default is True

        # toggle different track
        self.client.get(reverse("studioadmin:toggle_track_default", args=(self.kids_track.id,)))
        self.adult_track.refresh_from_db()
        self.kids_track.refresh_from_db()
        assert self.adult_track.default is False
        assert self.kids_track.default is True


class AddTrackViewTests(TestUsersMixin, TestCase):
    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse("studioadmin:add_track")

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def test_add_track(self):
        assert Track.objects.exists() is False
        self.client.post(self.url, {"name": "test track", "default": False})
        new_track = Track.objects.first()
        assert new_track.name == "test track"


class EditTrackViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)
        self.url = reverse("studioadmin:edit_track", args=(self.adult_track.slug,))

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def test_edit_track(self):
        assert self.adult_track.name == "Adults"
        self.client.post(self.url, {"name": "Test", "default": False})
        self.adult_track.refresh_from_db()
        assert self.adult_track.name == "Test"


class EventTypeListView(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse("studioadmin:event_types")

    def test_instructor_or_staff(self):
        self.user_access_test(["staff"], self.url)


class AddEventTypeViewTests(TestUsersMixin, TestCase):

    def test_choose_track_for_event_type(self):
        pass


class EditEventTypeViewTests(TestUsersMixin, TestCase):
    pass


class DeleteEventTypeViewTests(TestUsersMixin, TestCase):
    pass


class BlockConfigListView(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse("studioadmin:block_configs")

    def test_instructor_or_staff(self):
        self.user_access_test(["staff"], self.url)


class AddBlockConfigViewTests(TestUsersMixin, TestCase):

    def test_choose_event_type_for_block_config(self):
        pass


class UpdateBlockConfigViewTests(TestUsersMixin, TestCase):
    pass


class DeleteBlockConfigViewTests(TestUsersMixin, TestCase):
    pass

