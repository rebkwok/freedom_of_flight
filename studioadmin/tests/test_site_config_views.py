# -*- coding: utf-8 -*-
from datetime import datetime
from datetime import timezone as dt_timezone

from model_bakery import baker
import json
import pytest

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from booking.models import Block, Course, Track, EventType, BlockConfig, SubscriptionConfig, Subscription
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


class BlockConfigListView(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse("studioadmin:block_configs")

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


class DisabledBlockConfigListView(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)
    
    @classmethod
    def setUpTestData(cls):
        cls.url = reverse("studioadmin:disabled_block_configs")

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def test_only_shows_enabled_block_configs(self):
        baker.make(BlockConfig, course=True, active=False)
        baker.make(BlockConfig, course=False, active=True)
        baker.make(BlockConfig, course=False, disabled=True)
        resp = self.client.get(self.url)
        block_config_groups = resp.context["block_config_groups"]
        assert len(block_config_groups["Drop-in Credit Blocks"]) == 1
        assert len(block_config_groups["Course Credit Blocks"]) == 0
        assert block_config_groups["Drop-in Credit Blocks"][0].disabled is True


class ToggleActiveBlockConfigViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)
        self.block_config = baker.make(BlockConfig, name="test", active=False)
        self.url = reverse("studioadmin:ajax_toggle_block_config_active")

    def test_toggle_block_config(self):
        assert self.block_config.active is False

        self.client.post(self.url, {"block_config_id": self.block_config.id})
        self.block_config.refresh_from_db()
        assert self.block_config.active is True

        self.client.post(self.url, {"block_config_id": self.block_config.id})
        self.block_config.refresh_from_db()
        assert self.block_config.active is False


class ToggleDisabledBlockConfigViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.login(self.staff_user)
        self.block_config = baker.make(BlockConfig, name="test", active=True)
        self.enable_url = reverse("studioadmin:enable_block_config", args=(self.block_config.id,))
        self.disable_url = reverse("studioadmin:disable_block_config", args=(self.block_config.id,))

    def test_toggle_block_config(self):
        assert self.block_config.disabled is False
        assert self.block_config.active
        self.client.get(self.disable_url)
        self.block_config.refresh_from_db()

        # disabling makes active False
        assert self.block_config.disabled is True
        assert self.block_config.active is False

        self.client.get(self.enable_url)
        self.block_config.refresh_from_db()

        # enabling keeps active False
        assert self.block_config.disabled is False
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


class SubscriptionConfigListView(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse("studioadmin:subscription_configs")

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def test_shows_all_subscription_configs(self):
        baker.make(SubscriptionConfig, active=False)
        baker.make(SubscriptionConfig, active=True)
        baker.make(SubscriptionConfig, active=False)
        resp = self.client.get(self.url)
        subscription_configs = resp.context["subscription_configs"]
        assert len(subscription_configs) == 3
        # active first
        assert subscription_configs[0].active is True

    def test_shows_purchased_subscriptions(self):
        config = baker.make(SubscriptionConfig, active=False)
        baker.make(Subscription, config=config, _quantity=2)
        baker.make(Subscription, config=config, paid=True, _quantity=7)
        resp = self.client.get(self.url)
        assert "7" in resp.content.decode("utf-8")


class ToggleActiveSubscriptionConfigViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)
        self.subscription_config = baker.make(SubscriptionConfig, name="test")
        self.url = reverse("studioadmin:ajax_toggle_subscription_config_active")

    def test_toggle_block_config(self):
        # default is True
        assert self.subscription_config.active is True

        self.client.post(self.url, {"subscription_config_id": self.subscription_config.id})
        self.subscription_config.refresh_from_db()
        assert self.subscription_config.active is False

        self.client.post(self.url, {"subscription_config_id": self.subscription_config.id})
        self.subscription_config.refresh_from_db()
        assert self.subscription_config.active is True


class AddSubscriptionConfigViewTests(EventTestMixin, TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def test_staff_only(self):
        url = reverse("studioadmin:add_subscription_config", args=("one_off",))
        self.user_access_test(["staff"], url)

        url = reverse("studioadmin:add_subscription_config", args=("recurring",))
        self.user_access_test(["staff"], url)

    def test_choose_type_for_subscription_config(self):
        url = reverse("studioadmin:choose_subscription_config_type")
        resp = self.client.get(url)
        assert "Adding New Subscription/Membership" in resp.content.decode("utf-8")

    def test_choose_type_for_subscription_config_redirect(self):
        url = reverse("studioadmin:choose_subscription_config_type")
        resp = self.client.post(url, {"one_off": "One-off"})
        assert resp.url == reverse("studioadmin:add_subscription_config", args=("one_off",))

        resp = self.client.post(url, {"recurring": "Recurring"})
        assert resp.url == reverse("studioadmin:add_subscription_config", args=("recurring",))

    def test_bookable_event_type_options(self):
        url = reverse("studioadmin:add_subscription_config", args=("one_off",))
        resp = self.client.get(url)
        formset = resp.context_data["bookable_event_types_formset"]
        assert len(formset.forms) == EventType.objects.count()
        form = formset.forms[0]
        assert sorted(evtype.id for evtype in form.fields["event_type"].queryset) == sorted(EventType.objects.values_list("id", flat=True))

    def test_add_one_off_subscription_config(self):
        assert SubscriptionConfig.objects.exists() is False
        url = reverse("studioadmin:add_subscription_config", args=("one_off",))
        data = {
            "name": "Test subscription",
            "description": "test",
            "duration": 1,
            "duration_units": "months",
            "start_date": "01-Mar-2020",
            "start_options": "start_date",
            "recurring": False,
            "cost": 20,
            "active": False,
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 1,
            "form-MAX_FORMS": 1,
            "form-0-event_type": "",
            "form-0-allowed_number": "",
            "form-0-allowed_unit": "",
        }
        self.client.post(url, data)
        assert SubscriptionConfig.objects.filter(name="Test subscription").exists()
        config = SubscriptionConfig.objects.first()
        assert config.start_date == datetime(2020, 3, 1, 0, 0, tzinfo=dt_timezone.utc)
        assert config.bookable_event_types == {}

    def test_add_recurring_subscription_config(self):
        assert SubscriptionConfig.objects.exists() is False
        url = reverse("studioadmin:add_subscription_config", args=("recurring",))
        data = {
            "name": "Test subscription",
            "description": "test",
            "duration": 1,
            "duration_units": "months",
            "start_date": "",
            "start_options": "signup_date",
            "recurring": True,
            "cost": 20,
            "active": False,
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 1,
            "form-MAX_FORMS": 1,
            "form-0-event_type": "",
            "form-0-allowed_number": "",
            "form-0-allowed_unit": "",
        }
        self.client.post(url, data)
        assert SubscriptionConfig.objects.filter(name="Test subscription").exists()
        config = SubscriptionConfig.objects.first()
        assert not config.start_date
        assert config.bookable_event_types == {}

    def test_subscription_config_with_bookable_event_types(self):
        assert SubscriptionConfig.objects.exists() is False
        url = reverse("studioadmin:add_subscription_config", args=("one_off",))
        data = {
            "name": "Test subscription",
            "description": "test",
            "duration": 1,
            "duration_units": "months",
            "start_date": "01-Mar-2020",
            "start_options": "start_date",
            "recurring": False,
            "cost": 20,
            "active": False,
            "form-TOTAL_FORMS": 2,
            "form-INITIAL_FORMS": 2,
            "form-MAX_FORMS": 2,
            "form-0-event_type": self.aerial_event_type.id,
            "form-0-allowed_number": 2,
            "form-0-allowed_unit": "day",
            "form-1-event_type": self.kids_aerial_event_type.id,
            "form-1-allowed_number": 10,
            "form-1-allowed_unit": "month",
        }
        self.client.post(url, data)
        config = SubscriptionConfig.objects.first()
        assert config.bookable_event_types == {
            # jsonfield keys are always strings
            str(self.aerial_event_type.id): {"allowed_number": 2, "allowed_unit": "day"},
            str(self.kids_aerial_event_type.id): {"allowed_number": 10, "allowed_unit": "month"}
        }

    def test_bookable_event_type_validation(self):
        url = reverse("studioadmin:add_subscription_config", args=("one_off",))
        data = {
            "name": "Test subscription",
            "description": "test",
            "duration": 1,
            "duration_units": "months",
            "start_date": "01-Mar-2020",
            "start_options": "start_date",
            "recurring": False,
            "cost": 20,
            "active": False,
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 1,
            "form-MAX_FORMS": 1,
            "form-0-event_type": self.aerial_event_type.id,
            "form-0-allowed_number": 2,
            "form-0-allowed_unit": "week",
        }

        # monthly/weekly units must match
        resp = self.client.post(url, data)
        form = resp.context_data["form"]
        assert form.errors == {
            "__all__": [
                "Cannot specify weekly usage for a subscription with a monthly duration. Specify usage per month instead."
            ]
        }

        # monthly/weekly units must match
        resp = self.client.post(url, {**data, "duration_units": "weeks", "form-0-allowed_unit": "month"})
        form = resp.context_data["form"]
        assert form.errors == {
            "__all__": [
                "Cannot specify monthly usage for a subscription with a weekly duration. Specify usage per week instead."
            ]
        }

        # can't specify same event type twice
        updated = {
            "duration_units": "weeks",
            "form-TOTAL_FORMS": 2,
            "form-INITIAL_FORMS": 2,
            "form-MAX_FORMS": 2,
            "form-1-event_type": self.aerial_event_type.id,
            "form-1-allowed_number": 2,
            "form-1-allowed_unit": "week"
        }
        resp = self.client.post(url, {**data, **updated})
        form = resp.context_data["form"]
        assert form.errors == {
            "__all__": [
                f"Usage specified twice for event type {self.aerial_event_type.name} (track {self.adult_track})"
            ]
        }

        # ignore validation for units if no max number
        resp = self.client.post(url, {**data, "form-0-allowed_number": ""})
        assert resp.status_code == 302


class UpdateSubscriptionConfigViewTests(EventTestMixin, TestUsersMixin, TestCase):
    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)
        self.subscription_config = baker.make(SubscriptionConfig, name="test")
        self.url = reverse("studioadmin:edit_subscription_config", args=(self.subscription_config.id,))
        self.form_data = {
            "id": self.subscription_config.id,
            "name": "Test subscription",
            "description": "test",
            "duration": 1,
            "duration_units": "months",
            "start_date": "01-Mar-2020",
            "start_options": "start_date",
            "recurring": False,
            "cost": 20,
            "active": True,
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 1,
            "form-MAX_FORMS": 1,
            "form-0-event_type": self.aerial_event_type.id,
            "form-0-allowed_number": 2,
            "form-0-allowed_unit": "day",
        }

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def test_edit_subscription_config(self):
        self.client.post(self.url, self.form_data)
        self.subscription_config.refresh_from_db()
        assert self.subscription_config.name == "Test subscription"

    def test_can_delete_bookable_event_type(self):
        self.client.post(self.url, {**self.form_data, "form-0-DELETE": True})
        self.subscription_config.refresh_from_db()
        assert self.subscription_config.bookable_event_types == {}

    def test_start_date_disable_for_one_off_with_purchased_subscriptions(self):
        # no subscriptions
        self.subscription_config.recurring = False
        self.subscription_config.save()
        resp = self.client.get(self.url)
        assert "readonly" not in resp.context_data["form"].fields["start_date"].widget.attrs

        # unpaid subscription
        subscription = baker.make(Subscription, config=self.subscription_config, paid=False)
        resp = self.client.get(self.url)
        assert "readonly" not in resp.context_data["form"].fields["start_date"].widget.attrs

        # paid subscription
        subscription.paid = True
        subscription.save()
        resp = self.client.get(self.url)
        assert "readonly" in resp.context_data["form"].fields["start_date"].widget.attrs

        # recurring config
        self.subscription_config.recurring = True
        self.subscription_config.save()
        resp = self.client.get(self.url)
        assert "readonly" not in resp.context_data["form"].fields["start_date"].widget.attrs


class DeleteSubscriptionConfigViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)
        self.subscription_config = baker.make(SubscriptionConfig, name="test")
        self.url = reverse("studioadmin:delete_subscription_config", args=(self.subscription_config.id,))

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def test_delete_subscription_config(self):
        self.client.post(self.url)
        assert SubscriptionConfig.objects.filter(id=self.subscription_config.id).exists() is False

    def test_delete_subscription_config_if_subscriptions_paid(self):
        subscription = baker.make(Subscription, config=self.subscription_config, paid=True)
        resp = self.client.post(self.url)
        assert resp.status_code == 400
        assert SubscriptionConfig.objects.filter(id=self.subscription_config.id).exists() is True

        subscription.paid = False
        subscription.save()
        self.client.post(self.url)
        assert SubscriptionConfig.objects.filter(id=self.subscription_config.id).exists() is False


class CloneSubscriptionConfigViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)
        self.subscription_config = baker.make(SubscriptionConfig, name="test")
        self.url = reverse("studioadmin:clone_subscription_config", args=(self.subscription_config.id,))

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url, expected_redirect=reverse("studioadmin:subscription_configs"))

    def test_clone_subscription_config(self):
        assert SubscriptionConfig.objects.count() == 1
        self.client.post(self.url)
        assert SubscriptionConfig.objects.count() == 2
        assert SubscriptionConfig.objects.latest("id").name == "Copy of test"
        assert SubscriptionConfig.objects.latest("id").active is False

        self.client.post(self.url)
        assert SubscriptionConfig.objects.count() == 3
        assert SubscriptionConfig.objects.latest("id").name == "Copy of Copy of test"
