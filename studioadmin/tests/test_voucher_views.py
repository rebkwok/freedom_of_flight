# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from model_bakery import baker

from django.contrib.auth.models import User
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from booking.models import Block, BlockConfig, BlockVoucher, TotalVoucher, GiftVoucher, GiftVoucherConfig
from common.test_utils import TestUsersMixin
from payments.models import Invoice


class BlockVoucherCreateUpdateViewTests(TestUsersMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.block_type = baker.make(BlockConfig, active=True)
        cls.url = reverse('studioadmin:add_voucher')

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.login(self.staff_user, password="test")

    def test_access(self):
        self.user_access_test(["staff"], self.url)

    def test_create_block_voucher(self):
        data = {
            'code': 'test_code',
            'discount': 10,
            'item_count': 1,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'total_voucher': False,
            'block_configs': [self.block_type.id]
        }
        assert BlockVoucher.objects.exists() is False
        resp = self.client.post(self.url, data)
        assert resp.url == reverse("studioadmin:vouchers")
        assert BlockVoucher.objects.count() == 1
        voucher = BlockVoucher.objects.first()
        assert voucher.check_block_config(self.block_type)

    def test_create_total_voucher(self):
        data = {
            'code': 'test_code',
            'discount': 10,
            'item_count': 1,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'total_voucher': True,
        }
        assert TotalVoucher.objects.exists() is False
        self.client.post(self.url, data)

        assert TotalVoucher.objects.count() == 1

    def test_create_gift_voucher(self):
        data = {
            'code': 'test_code',
            'discount': 10,
            'item_count': 1,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'total_voucher': False,
            'block_configs': [self.block_type.id],
        }
        assert BlockVoucher.objects.exists() is False
        resp = self.client.post(reverse("studioadmin:add_gift_voucher"), data)
        assert resp.url == reverse("studioadmin:gift_vouchers")
        assert BlockVoucher.objects.count() == 1
        voucher = BlockVoucher.objects.first()
        assert voucher.is_gift_voucher

    def test_update_voucher(self):
        data = {
            'code': 'test_code',
            'discount': 10,
            'item_count': 1,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'total_voucher': False,
            'block_configs': [self.block_type.id]
        }
        self.client.post(self.url, data, follow=True)
        voucher = BlockVoucher.objects.latest('id')

        data.update(id=voucher.id)
        data.update(code="test_new")
        resp = self.client.post(
            reverse("studioadmin:edit_voucher", args=(voucher.id,)),
            data=data,
            follow=True
        )
        assert "has been updated!" in resp.rendered_content
        voucher.refresh_from_db()
        assert voucher.code == "test_new"


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


class GiftVoucherListViewTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.block_type = baker.make(BlockConfig, active=True)
        cls.url = reverse('studioadmin:gift_vouchers')
        baker.make(BlockVoucher, discount=10, start_date=timezone.now() - timedelta(10))
        cls.total_voucher = baker.make(TotalVoucher, discount_amount=10, start_date=timezone.now() - timedelta(10))
        baker.make(GiftVoucher, gift_voucher_config__discount_amount=10, total_voucher=cls.total_voucher)

    def setUp(self):
        self.create_admin_users()

    def test_gift_vouchers_listed(self):
        self.client.login(username=self.staff_user.username, password='test')
        resp = self.client.get(self.url)
        assert len(resp.context_data['vouchers']) == 1
        assert resp.context_data['vouchers'][0] == self.total_voucher


class VoucherUsesViewTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super(VoucherUsesViewTests, cls).setUpTestData()
        cls.voucher = baker.make(BlockVoucher, discount=10)
        cls.total_voucher = baker.make(TotalVoucher, discount=10)
        cls.voucher_url = reverse('studioadmin:voucher_uses', args=[cls.voucher.pk])
        cls.total_voucher_url = reverse('studioadmin:voucher_uses', args=[cls.total_voucher.pk])

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
            assert user_item["num_uses"] == 2

    def test_total_voucher_counts_listed(self):
        user = baker.make(User, username="testvoucher@test.com", email="testvoucher@test.com")
        baker.make(
            Invoice, paid=True, total_voucher_code=self.total_voucher.code, username=user.email, _quantity=2
        )
        baker.make(
            Invoice, paid=True, total_voucher_code=self.total_voucher.code, username="non_existant_user@test.com", _quantity=2
        )

        self.client.login(username=self.staff_user.username, password='test')
        resp = self.client.get(self.total_voucher_url)
        assert len(resp.context_data['voucher_users']) == 2
        for user_item in resp.context_data['voucher_users']:
            assert user_item["num_uses"] == 2


class GiftVoucherConfigListViewTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        block_config = baker.make(BlockConfig)
        baker.make(GiftVoucherConfig, discount_amount=10, active=False)
        cls.active = baker.make(GiftVoucherConfig, block_config=block_config, active=True)
        baker.make(GiftVoucherConfig, block_config=block_config, active=False)
        cls.url = reverse('studioadmin:gift_voucher_configs')

    def setUp(self):
        self.create_admin_users()
        self.create_users()

    def test_cannot_access_if_not_staff(self):
        """
        test that the page redirects if user is not a staff user
        """
        self.user_access_test(["staff"], self.url)

    def test_configs_listed(self):
        self.login(self.staff_user, "test")
        resp = self.client.get(self.url)
        assert len(resp.context_data["gift_voucher_configs"]) == 3
        assert resp.context_data["gift_voucher_configs"][0] == self.active


class GiftVoucherConfigCreateViewTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.block_config = baker.make(BlockConfig, active=True)
        cls.url = reverse('studioadmin:add_gift_voucher_config')

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.login(self.staff_user, "test")

    def test_cannot_access_if_not_staff(self):
        """
        test that the page redirects if user is not a staff user
        """
        self.user_access_test(["staff"], self.url)

    def test_create_gift_voucher_block_config(self):
        assert GiftVoucherConfig.objects.exists() is False
        data = {"block_config": self.block_config.id, "active": True, "duration": 6}
        self.client.post(self.url, data)
        assert GiftVoucherConfig.objects.exists() is True
        new_config = GiftVoucherConfig.objects.first()
        assert new_config.active is True
        assert new_config.duration == 6

    def test_create_gift_voucher_total_config(self):
        assert GiftVoucherConfig.objects.exists() is False
        data = {"discount_amount": 20}
        self.client.post(self.url, data)
        assert GiftVoucherConfig.objects.exists() is True
        new_config = GiftVoucherConfig.objects.first()
        assert new_config.active is False
        # no duration, model default is 6
        assert new_config.duration == 6


class GiftVoucherConfigUpdateViewTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.block_config = baker.make(BlockConfig, active=True)

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.login(self.staff_user, "test")
        self.voucher_config = baker.make(GiftVoucherConfig, block_config=self.block_config)
        self.url = reverse('studioadmin:edit_gift_voucher_config', args=(self.voucher_config.id,))

    def test_cannot_access_if_not_staff(self):
        """
        test that the page redirects if user is not a staff user
        """
        self.user_access_test(["staff"], self.url)

    def test_update_gift_voucher_config(self):
        data = {"discount_amount": 10}
        self.client.post(self.url, data=data)
        self.voucher_config.refresh_from_db()
        assert self.voucher_config.block_config is None
        assert self.voucher_config.discount_amount == 10


class GiftVoucherToggleActiveViewTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.block_config = baker.make(BlockConfig, active=True)

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.login(self.staff_user, "test")
        self.voucher_config = baker.make(GiftVoucherConfig, block_config=self.block_config, active=True)
        self.url = reverse('studioadmin:ajax_toggle_gift_voucher_config_active')

    def test_toggle(self):
        resp = self.client.post(self.url, {"config_id": self.voucher_config.id})
        self.voucher_config.refresh_from_db()
        assert resp.json()["active"] is False
        assert self.voucher_config.active is False

        resp = self.client.post(self.url, {"config_id": self.voucher_config.id})
        self.voucher_config.refresh_from_db()
        assert resp.json()["active"] is True
        assert self.voucher_config.active is True
