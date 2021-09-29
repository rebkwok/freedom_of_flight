from model_bakery import baker

from django.core.cache import cache
from django.urls import reverse
from django.test import TestCase

from booking.models import Block, BlockConfig, Course, Event, EventType
from common.test_utils import TestUsersMixin


class BlockPurchaseViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.make_data_privacy_agreement(self.student_user)
        self.make_data_privacy_agreement(self.manager_user)
        self.make_disclaimer(self.student_user)
        self.make_disclaimer(self.child_user)
        self.login(self.student_user)

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse("booking:purchase_options")
        event_type = baker.make(EventType, track__name="test")
        cls.activeconfig = baker.make(BlockConfig, event_type=event_type, active=True)
        cls.inactiveconfig = baker.make(
            BlockConfig, event_type=event_type, active=False,
            size=4, duration=2
        )
        cls.courseconfig = baker.make(BlockConfig, course=True, event_type=event_type, size=3, active=True)

    def test_no_data_privacy_agreement(self):
        self.student_user.data_privacy_agreement.all().delete()
        cache.clear()
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == reverse('accounts:data_privacy_review') + '?next=' + self.url

    def test_list_active_block_configs(self):
        resp = self.client.get(self.url)
        assert list(resp.context["available_blocks"].keys()) == ["Drop-in Credit Blocks", "Course Credit Blocks"]
        assert [bc.id for bc in resp.context["available_blocks"]["Drop-in Credit Blocks"]] == [self.activeconfig.id]
        assert [cc.id for cc in resp.context["available_blocks"]["Course Credit Blocks"]] == [self.courseconfig.id]
        assert resp.context["user_active_blocks"] == []

    def test_course_purchase_view_shows_only_target_configs(self):
        course = baker.make(
            Course, event_type=self.courseconfig.event_type, number_of_events=3, show_on_site=True
        )
        url = reverse("booking:course_purchase_options", args=(course.slug,))
        resp = self.client.get(url)
        # Course Credit Blocks shown first
        assert list(resp.context["available_blocks"].keys()) == ["Course Credit Blocks"]
        assert [cc.id for cc in resp.context["available_blocks"]["Course Credit Blocks"]] == [self.courseconfig.id]
        assert resp.context["user_active_blocks"] == []
        assert resp.context["related_item"] == course

    def test_dropin_purchase_view_shows_only_target_configs(self):
        event = baker.make(Event, event_type=self.activeconfig.event_type)
        url = reverse("booking:event_purchase_options", args=(event.slug,))
        resp = self.client.get(url)
        # dropin blocks shown first
        assert list(resp.context["available_blocks"].keys()) == ["Drop-in Credit Blocks"]
        assert [bc.id for bc in resp.context["available_blocks"]["Drop-in Credit Blocks"]] == [self.activeconfig.id]
        assert resp.context["user_active_blocks"] == []
        assert resp.context["related_item"] == event

    def test_user_active_blocks_in_context(self):
        block = baker.make(Block, user=self.student_user, block_config=self.activeconfig, paid=True)
        # unpaid, not shown
        baker.make(Block, user=self.student_user, block_config=self.activeconfig)
        resp = self.client.get(self.url)
        assert list(resp.context["available_blocks"].keys()) == ["Drop-in Credit Blocks", "Course Credit Blocks"]
        assert [bc.id for bc in resp.context["available_blocks"]["Drop-in Credit Blocks"]] == [self.activeconfig.id]
        assert [cc.id for cc in resp.context["available_blocks"]["Course Credit Blocks"]] == [self.courseconfig.id]
        assert resp.context["user_active_blocks"] == [block]

    def test_user_and_managed_user_blocks_in_context(self):
        # make sure the manager user is also a student, otherwise payment options page doesn't show options for them
        cache.clear()
        self.manager_user.userprofile.student = True
        self.manager_user.userprofile.save()
        self.login(self.manager_user)
        block1 = baker.make(Block, user=self.child_user, block_config=self.activeconfig, paid=True)
        block2 = baker.make(Block, user=self.manager_user, block_config=self.activeconfig, paid=True)
        resp = self.client.get(self.url)
        assert list(resp.context["available_blocks"].keys()) == ["Drop-in Credit Blocks", "Course Credit Blocks"]
        assert [bc.id for bc in resp.context["available_blocks"]["Drop-in Credit Blocks"]] == [self.activeconfig.id]
        assert [cc.id for cc in resp.context["available_blocks"]["Course Credit Blocks"]] == [self.courseconfig.id]
        assert sorted([block.id for block in resp.context["user_active_blocks"]]) == sorted([block1.id, block2.id])

    def test_active_block_info(self):
        baker.make(
            Block, user=self.student_user, block_config=self.activeconfig, paid=True
        )
        resp = self.client.get(self.url)
        assert "You have active credit blocks" in resp.content.decode("utf-8")
        assert f"Student User: {self.activeconfig.name} ({self.activeconfig.size}/{self.activeconfig.size} remaining); not started" in resp.content.decode("utf-8")
