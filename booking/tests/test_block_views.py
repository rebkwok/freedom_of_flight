from datetime import timedelta
from model_bakery import baker

from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from booking.models import Block
from common.test_utils import TestUsersMixin


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
        # unpaid
        baker.make(Block, user=self.student_user, block_config__size=2)
        # expired paid
        baker.make(
            Block, user=self.student_user, block_config__size=2, paid=True,
            expiry_date=timezone.now() - timedelta(2))
        self.login(self.student_user)
        resp = self.client.get(self.url)
        blocks = resp.context_data["blocks"]
        assert len(blocks) == 1

        resp = self.client.get(self.url + "?include-expired=true")
        blocks = resp.context_data["blocks"]
        assert len(blocks) == 2


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
        assert len(resp.context_data['blocks']) == 0
