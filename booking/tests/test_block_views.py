from model_bakery import baker

from django.urls import reverse
from django.test import TestCase

from booking.models import Block, DropInBlockConfig, CourseBlockConfig, Course, Event, EventType
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
        cls.url = reverse("booking:block_purchase")
        event_type = baker.make(EventType)
        cls.activeconfig = baker.make(DropInBlockConfig, event_type=event_type, active=True)
        cls.inactiveconfig = baker.make(
            DropInBlockConfig, event_type=event_type, active=False,
            size=4, duration=2
        )
        cls.courseconfig = baker.make(CourseBlockConfig, course_type__number_of_events=3, active=True)

    def test_list_active_block_configs(self):
        resp = self.client.get(self.url)
        assert list(resp.context["available_blocks"].keys()) == ["Drop-in Credit Blocks", "Course Credit Blocks"]
        assert [bc.id for bc in resp.context["available_blocks"]["Drop-in Credit Blocks"]] == [self.activeconfig.id]
        assert [cc.id for cc in resp.context["available_blocks"]["Course Credit Blocks"]] == [self.courseconfig.id]
        assert resp.context["user_active_blocks"] == []

    def test_course_purchase_view_shows_target_configs_at_start(self):
        course = baker.make(Course, course_type=self.courseconfig.course_type, show_on_site=True)
        url = reverse("booking:course_block_purchase", args=(course.slug,))
        resp = self.client.get(url)
        # Course Credit Blocks shown first
        assert list(resp.context["available_blocks"].keys()) == ["Course Credit Blocks", "Drop-in Credit Blocks"]
        assert [bc.id for bc in resp.context["available_blocks"]["Drop-in Credit Blocks"]] == [self.activeconfig.id]
        assert [cc.id for cc in resp.context["available_blocks"]["Course Credit Blocks"]] == [self.courseconfig.id]
        assert resp.context["user_active_blocks"] == []
        assert resp.context["related_item"] == course
        assert resp.context["target_configs"] == [self.courseconfig]

    def test_dropin_purchase_view_shows_target_configs_at_start(self):
        event = baker.make(Event, event_type=self.activeconfig.event_type   )
        url = reverse("booking:dropin_block_purchase", args=(event.slug,))
        resp = self.client.get(url)
        # dropin blocks shown first
        assert list(resp.context["available_blocks"].keys()) == ["Drop-in Credit Blocks", "Course Credit Blocks"]
        assert [bc.id for bc in resp.context["available_blocks"]["Drop-in Credit Blocks"]] == [self.activeconfig.id]
        assert [cc.id for cc in resp.context["available_blocks"]["Course Credit Blocks"]] == [self.courseconfig.id]
        assert resp.context["user_active_blocks"] == []
        assert resp.context["related_item"] == event
        assert resp.context["target_configs"] == [self.activeconfig]

    def test_user_active_blocks_in_context(self):
        block = baker.make(Block, user=self.student_user, dropin_block_config=self.activeconfig, paid=True)
        # unpaid, not shown
        baker.make(Block, user=self.student_user, dropin_block_config=self.activeconfig)
        resp = self.client.get(self.url)
        assert list(resp.context["available_blocks"].keys()) == ["Drop-in Credit Blocks", "Course Credit Blocks"]
        assert [bc.id for bc in resp.context["available_blocks"]["Drop-in Credit Blocks"]] == [self.activeconfig.id]
        assert [cc.id for cc in resp.context["available_blocks"]["Course Credit Blocks"]] == [self.courseconfig.id]
        assert resp.context["user_active_blocks"] == [block]

    def test_user_and_managed_user_blocks_in_context(self):
        self.login(self.manager_user)
        block1 = baker.make(Block, user=self.child_user, dropin_block_config=self.activeconfig, paid=True)
        block2 = baker.make(Block, user=self.manager_user, dropin_block_config=self.activeconfig, paid=True)
        resp = self.client.get(self.url)
        assert list(resp.context["available_blocks"].keys()) == ["Drop-in Credit Blocks", "Course Credit Blocks"]
        assert [bc.id for bc in resp.context["available_blocks"]["Drop-in Credit Blocks"]] == [self.activeconfig.id]
        assert [cc.id for cc in resp.context["available_blocks"]["Course Credit Blocks"]] == [self.courseconfig.id]
        assert sorted([block.id for block in resp.context["user_active_blocks"]]) == sorted([block1.id, block2.id])

    def test_active_block_info(self):
        block1 = baker.make(
            Block, user=self.student_user, dropin_block_config=self.activeconfig, paid=True
        )
        resp = self.client.get(self.url)
        assert "You have active credit blocks" in resp.content.decode("utf-8")
        assert f"Student User: {self.activeconfig.identifier} ({self.activeconfig.size}/{self.activeconfig.size} remaining); not started" in resp.content.decode("utf-8")


class BlockListViewTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse("booking:blocks")

    def setUp(self):
        self.create_users()
        self.make_data_privacy_agreement(self.student_user)
        self.make_data_privacy_agreement(self.manager_user)
        self.make_disclaimer(self.student_user)
        self.make_disclaimer(self.child_user)

    def test_only_list_users_and_managed_users_blocks(self):
        baker.make(Block, user=self.student_user, dropin_block_config__size=2, paid=True)
        baker.make(Block, user=self.manager_user, dropin_block_config__size=2, paid=True)
        baker.make(Block, user=self.child_user, dropin_block_config__size=2, paid=True)

        self.login(self.student_user)
        resp = self.client.get(self.url)
        assert len(resp.context_data["active_blocks_by_config"]) == 1
        assert len(list(resp.context_data["active_blocks_by_config"].values())[0]) == 1

        self.login(self.manager_user)
        resp = self.client.get(self.url)
        assert len(resp.context_data["active_blocks_by_config"]) == 2
        for group in resp.context_data["active_blocks_by_config"].values():
            assert len(group) == 1

    def test_blocks_grouped_by_block_config(self):
        block = baker.make(Block, user=self.student_user, dropin_block_config__size=2, paid=True)
        block_config1 = block.block_config
        block1 = baker.make(Block, user=self.student_user, dropin_block_config=block_config1, paid=True)
        block2 = baker.make(Block, user=self.student_user, dropin_block_config__size=2, paid=True)

        self.login(self.student_user)
        resp = self.client.get(self.url)
        blocks_by_config = resp.context_data["active_blocks_by_config"]
        assert len(blocks_by_config) == 2 # 3 blocks, in 2 groups by config
        for config, blocks in blocks_by_config.items():
            if config == block_config1:
                assert len(blocks) == 2
                assert sorted([block.id for block in blocks]) == sorted([block.id, block1.id])
            else:
                assert len(blocks) == 1
                assert blocks[0] == block2

    def test_unpaid_blocks_not_listed(self):
        paid_block = baker.make(Block, user=self.student_user, dropin_block_config__size=2, paid=True)
        baker.make(Block, user=self.student_user, dropin_block_config__size=2)
        self.login(self.student_user)
        resp = self.client.get(self.url)
        blocks_by_config = resp.context_data["active_blocks_by_config"]
        assert len(blocks_by_config) == 1
        assert list(blocks_by_config.values())[0] == [paid_block]
