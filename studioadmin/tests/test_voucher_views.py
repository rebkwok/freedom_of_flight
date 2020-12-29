# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from model_bakery import baker

from django.contrib.auth.models import User
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from booking.models import Block, BlockConfig, BlockVoucher, TotalVoucher
from common.test_utils import TestUsersMixin


class BlockVoucherListViewTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.block_type = baker.make(BlockConfig, active=True)
        cls.url = reverse('studioadmin:vouchers')

    def setUp(self):
        self.create_admin_users()
        self.create_users()

    def test_cannot_access_if_not_logged_in(self):
        """
        test that the page redirects if user is not logged in
        """
        resp = self.client.get(self.url)
        redirected_url = reverse('account_login') + "?next={}".format(self.url)
        assert resp.status_code == 302
        assert redirected_url in resp.url

    def test_cannot_access_if_not_staff(self):
        """
        test that the page redirects if user is not a staff user
        """
        self.user_access_test(["staff"], self.url)

    def test_vouchers_listed(self):
        # start date in past
        baker.make(
            BlockVoucher, discount=10, start_date=timezone.now() - timedelta (10), _quantity=2
        )
        # start date in future
        baker.make(
            BlockVoucher, discount=10, start_date=timezone.now() + timedelta (10), _quantity=2
        )
        # expired
        baker.make(
            BlockVoucher, discount=10, expiry_date=timezone.now() - timedelta (10), _quantity=2
        )
        self.client.login(
            username=self.staff_user.username, password='test'
        )
        resp = self.client.get(self.url)
        assert len(resp.context_data['vouchers']) == 6

    def test_vouchers_expired(self):
        """
        Grey out expired/used vouchers
        """
        # active
        voucher = baker.make(BlockVoucher, discount=10)
        self.client.login(
            username=self.staff_user.username, password='test'
        )
        resp = self.client.get(self.url)
        assert 'class="expired"' not in resp.rendered_content

        voucher.delete()
        # expired
        voucher = baker.make(
            BlockVoucher, discount=10, expiry_date=timezone.now() - timedelta(10)
        )
        resp = self.client.get(self.url)
        assert 'class="expired"' in resp.rendered_content

        voucher.delete()
        # max used
        voucher = baker.make(BlockVoucher, discount=10, max_vouchers=1)
        baker.make(Block, paid=True, voucher=voucher)
        resp = self.client.get(self.url)
        assert 'class="expired"' in resp.rendered_content


class VoucherUsesViewTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super(VoucherUsesViewTests, cls).setUpTestData()
        cls.voucher = baker.make(BlockVoucher, discount=10, )
        cls.voucher_url = reverse(
            'studioadmin:voucher_uses', args=[cls.voucher.pk]
        )

    def setUp(self):
        self.create_admin_users()

    def test_voucher_counts_listed(self):
        users = baker.make(User, _quantity=2)
        for user in users:
            baker.make(
                Block, paid=True, voucher=self.voucher, user=user, _quantity=2
            )

        self.client.login(
            username=self.staff_user.username, password='test'
        )
        resp = self.client.get(self.voucher_url)
        assert len(resp.context_data['voucher_users']) == 2
        for user_item in resp.context_data['voucher_users']:
            assert user_item.num_uses == 2


class GiftVoucherConfigListViewTests(TestCase):
    # TODO
    pass


class GiftVoucherConfigCreateViewTests(TestCase):
    # TODO
    pass


class GiftVoucherConfigUpdateViewTests(TestCase):
    # TODO
    pass
