# -*- coding: utf-8 -*-
from model_bakery import baker
import json
import pytest

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from booking.models import Block, Course, Track, EventType, BlockConfig
from common.test_utils import EventTestMixin, TestUsersMixin


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

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)


class AddEventTypeViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)
        self.form_data = {
            "track": self.adult_track.id,
            "name": "Party",
            "label": "party",
            "plural_suffix": "",
            "description": "Test",
            "booking_restriction": 15,
            "cancellation_period": 48,
            "email_studio_when_booked": False,
            "allow_booking_cancellation": True,
            "is_online": False,
        }

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def url(self, track):
        return reverse("studioadmin:add_event_type", args=(track.id,))

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url(self.adult_track))

    def test_choose_track_for_event_type(self):
        url = reverse("studioadmin:choose_track_for_event_type")
        resp = self.client.get(url)
        assert [track.id for track in resp.context["form"].fields["track"].queryset] == [self.adult_track.id, self.kids_track.id]

        resp = self.client.post(url, {"track": self.adult_track.id})
        assert resp.url == self.url(self.adult_track)

    def test_context(self):
        resp = self.client.get(self.url(self.adult_track))
        assert "creating" in resp.context_data
        assert resp.context_data["track"] == self.adult_track

    def test_create_event_type(self):
        assert EventType.objects.filter(name="party").exists() is False
        self.client.post(self.url(self.adult_track), data=self.form_data)
        assert EventType.objects.filter(name="party").exists() is True

    def test_create_with_same_name(self):
        baker.make(EventType, name="party", track=self.adult_track)
        assert EventType.objects.filter(name="party").count() == 1
        # can't make event type with same name and track
        resp = self.client.post(self.url(self.adult_track), data=self.form_data)
        assert resp.status_code == 200
        assert EventType.objects.filter(name="party").count() == 1

        # can make event type with same name but different track track
        self.client.post(self.url(self.kids_track), data={**self.form_data, "track": self.kids_track.id})
        assert EventType.objects.filter(name="party").count() == 2


class EditEventTypeViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)
        self.form_data = {
            "id": self.aerial_event_type.id,
            "track": self.adult_track.id,
            "name": "Party",
            "label": "party",
            "plural_suffix": "",
            "description": "Test",
            "booking_restriction": 15,
            "cancellation_period": 48,
            "email_studio_when_booked": False,
            "allow_booking_cancellation": True,
            "is_online": False,
        }
        self.url = reverse("studioadmin:edit_event_type", args=(self.aerial_event_type.id,))

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def test_create_event_type(self):
        self.client.post(self.url, data=self.form_data)
        self.aerial_event_type.refresh_from_db()
        assert self.aerial_event_type.name == "party"


class DeleteEventTypeViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.create_events_and_course()
        self.login(self.staff_user)
        self.event_type = baker.make(EventType, name="test", track=self.adult_track)

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def url(self, event_type):
        return reverse("studioadmin:delete_event_type", args=(event_type.id,))

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url(self.event_type))

    def test_delete_event_type(self):
        self.client.post(self.url(self.event_type))
        assert EventType.objects.filter(id=self.event_type.id).exists() is False

    def test_delete_event_type_with_events(self):
        resp = self.client.post(self.url(self.aerial_event_type))
        assert EventType.objects.filter(id=self.aerial_event_type.id).exists() is True
        assert resp.status_code == 400

    def test_delete_event_type_with_course(self):
        baker.make(Course, event_type=self.event_type)
        resp = self.client.post(self.url(self.event_type))
        assert EventType.objects.filter(id=self.event_type.id).exists() is True
        assert resp.status_code == 400


class BlockConfigListView(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse("studioadmin:block_configs")
        cls.create_cls_tracks_and_event_types()

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def test_shows_all_block_configs(self):
        baker.make(BlockConfig, course=True, active=False)
        baker.make(BlockConfig, course=False, active=True)
        baker.make(BlockConfig, course=False, active=False)
        resp = self.client.get(self.url)
        block_config_groups = resp.context["block_config_groups"]
        assert len(block_config_groups["Drop-in Credit Blocks"]) == 2
        assert len(block_config_groups["Course Credit Blocks"]) == 1
        # active first
        assert block_config_groups["Drop-in Credit Blocks"][0].active is True


class ToggleActiveBlockConfigViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)
        self.block_config = baker.make(BlockConfig, name="test", event_type=self.aerial_event_type)
        self.url = reverse("studioadmin:ajax_toggle_block_config_active")

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def test_toggle_block_config(self):
        assert self.block_config.active is False

        self.client.post(self.url, {"block_config_id": self.block_config.id})
        self.block_config.refresh_from_db()
        assert self.block_config.active is True

        self.client.post(self.url, {"block_config_id": self.block_config.id})
        self.block_config.refresh_from_db()
        assert self.block_config.active is False


class AddBlockConfigViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def test_staff_only(self):
        url = reverse("studioadmin:add_block_config", args=("dropin",))
        self.user_access_test(["staff"], url)

        url = reverse("studioadmin:add_block_config", args=("course",))
        self.user_access_test(["staff"], url)

    def test_choose_event_type_for_block_config(self):
        url = reverse("studioadmin:choose_block_config_type")
        resp = self.client.get(url)
        assert "Adding New Credit Block" in resp.content.decode("utf-8")

    def test_choose_event_type_for_block_config_redirect(self):
        url = reverse("studioadmin:choose_block_config_type")
        resp = self.client.post(url, {"dropin": "Drop in"})
        assert resp.url == reverse("studioadmin:add_block_config", args=("dropin",))

        resp = self.client.post(url, {"course": "Course"})
        assert resp.url == reverse("studioadmin:add_block_config", args=("course",))

    def test_add_dropin_block_config(self):
        url = reverse("studioadmin:add_block_config", args=("dropin",))
        data = {
            "event_type": self.aerial_event_type.id,
            "name": "Test block",
            "description": "test",
            "size": 2,
            "duration": 1,
            "cost": 20,
            "active": False
        }
        self.client.post(url, data)
        assert BlockConfig.objects.filter(name="Test block").exists()


class UpdateBlockConfigViewTests(EventTestMixin, TestUsersMixin, TestCase):
    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)
        self.block_config = baker.make(BlockConfig, name="test", event_type=self.aerial_event_type)
        self.url = reverse("studioadmin:edit_block_config", args=(self.block_config.id,))
        self.form_data = {
            "id": self.block_config.id,
            "event_type": self.aerial_event_type.id,
            "name": "Test block",
            "description": "test",
            "size": 2,
            "duration": 1,
            "cost": 20,
            "active": False
        }

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def test_edit_block_config(self):
        self.client.post(self.url, self.form_data)
        self.block_config.refresh_from_db()
        assert self.block_config.name == "Test block"

    def test_fields_disabled_if_blocks_paid(self):
        block = baker.make(Block, block_config=self.block_config, paid=False)
        resp = self.client.get(self.url)
        form = resp.context_data["form"]
        assert form.existing_blocks is False

        block.paid = True
        block.save()
        resp = self.client.get(self.url)
        form = resp.context_data["form"]
        assert form.existing_blocks is True
        for field_name, field in form.fields.items():
            if field_name in ["event_type", "size", "duration"]:
                field.widget.attrs["readonly"] = True


class DeleteBlockConfigViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)
        self.block_config = baker.make(BlockConfig, name="test", event_type=self.aerial_event_type)
        self.url = reverse("studioadmin:delete_block_config", args=(self.block_config.id,))

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def test_delete_block_config(self):
        self.client.post(self.url)
        assert BlockConfig.objects.filter(id=self.block_config.id).exists() is False

    def test_delete_block_config_if_blocks_paid(self):
        block = baker.make(Block, block_config=self.block_config, paid=True)
        resp = self.client.post(self.url)
        assert resp.status_code == 400
        assert BlockConfig.objects.filter(id=self.block_config.id).exists() is True

        block.paid = False
        block.save()
        self.client.post(self.url)
        assert BlockConfig.objects.filter(id=self.block_config.id).exists() is False
