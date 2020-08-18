from model_bakery import baker

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
        cls.url = reverse("booking:block_purchase")
        event_type = baker.make(EventType)
        cls.activeconfig = baker.make(BlockConfig, event_type=event_type, active=True)
        cls.inactiveconfig = baker.make(
            BlockConfig, event_type=event_type, active=False,
            size=4, duration=2
        )
        cls.courseconfig = baker.make(BlockConfig, course=True, event_type=event_type, size=3, active=True)

    def test_list_active_block_configs(self):
        resp = self.client.get(self.url)
        assert list(resp.context["available_blocks"].keys()) == ["Drop-in Credit Blocks", "Course Credit Blocks"]
        assert [bc.id for bc in resp.context["available_blocks"]["Drop-in Credit Blocks"]] == [self.activeconfig.id]
        assert [cc.id for cc in resp.context["available_blocks"]["Course Credit Blocks"]] == [self.courseconfig.id]
        assert resp.context["user_active_blocks"] == []

    def test_course_purchase_view_shows_target_configs_at_start(self):
        course = baker.make(Course, event_type=self.courseconfig.event_type, number_of_events=3, show_on_site=True)
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
        event = baker.make(Event, event_type=self.activeconfig.event_type)
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
        block = baker.make(Block, user=self.student_user, block_config=self.activeconfig, paid=True)
        # unpaid, not shown
        baker.make(Block, user=self.student_user, block_config=self.activeconfig)
        resp = self.client.get(self.url)
        assert list(resp.context["available_blocks"].keys()) == ["Drop-in Credit Blocks", "Course Credit Blocks"]
        assert [bc.id for bc in resp.context["available_blocks"]["Drop-in Credit Blocks"]] == [self.activeconfig.id]
        assert [cc.id for cc in resp.context["available_blocks"]["Course Credit Blocks"]] == [self.courseconfig.id]
        assert resp.context["user_active_blocks"] == [block]

    def test_user_and_managed_user_blocks_in_context(self):
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


class BlockListViewTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse("booking:blocks")

    def setUp(self):
        self.create_users()
        self.make_data_privacy_agreement(self.student_user)
        self.make_data_privacy_agreement(self.student_user1)
        self.make_data_privacy_agreement(self.manager_user)
        self.make_disclaimer(self.student_user)
        self.make_disclaimer(self.student_user1)
        self.make_disclaimer(self.child_user)

    def tearDown(self):
        del self.client.session["user_id"]

    def test_list_logged_in_users_blocks_by_default(self):
        baker.make(Block, user=self.student_user, block_config__size=1, paid=True)
        baker.make(Block, user=self.student_user1, block_config__size=1, paid=True)

        self.login(self.student_user)
        resp = self.client.get(self.url)
        assert len(resp.context_data["blocks"]) == 1
        assert resp.context_data["blocks"][0].user == self.student_user

        self.login(self.student_user1)
        resp = self.client.get(self.url)
        assert len(resp.context_data["blocks"]) == 1
        assert resp.context_data["blocks"][0].user == self.student_user1

    def test_unpaid_blocks_not_listed(self):
        baker.make(Block, user=self.student_user, block_config__size=2, paid=True)
        baker.make(Block, user=self.student_user, block_config__size=2)
        self.login(self.student_user)
        resp = self.client.get(self.url)
        blocks = resp.context_data["blocks"]
        assert len(blocks) == 1

    def test_block_list_by_managed_user(self):
        baker.make(Block, user=self.child_user, block_config__size=1, paid=True)
        # by default view_as_user for manager user is child user
        self.login(self.manager_user)
        resp = self.client.get(self.url)
        assert len(resp.context_data["blocks"]) == 1
        assert self.client.session["user_id"] == self.child_user.id
        assert resp.context_data["blocks"][0].user == self.child_user

        # post sets the session user id and redirects to the booking page again
        resp = self.client.post(self.url, data={"view_as_user": self.manager_user.id}, follow=True)
        assert self.client.session["user_id"] == self.manager_user.id
        assert resp.context_data['blocks'].count() == 0
