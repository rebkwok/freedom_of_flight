# -*- coding: utf-8 -*-
from model_bakery import baker

from django.urls import reverse
from django.test import TestCase

from booking.models import GiftVoucherConfig, GiftVoucher, BlockConfig, BlockVoucher, TotalVoucher

from common.test_utils import TestUsersMixin, EventTestMixin


class GiftVoucherPurchaseViewTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse('booking:buy_gift_voucher')
        block_config = baker.make(BlockConfig, active=True, cost=10)
        cls.config_total = baker.make(GiftVoucherConfig, discount_amount=10, active=True)
        cls.config_block = baker.make(GiftVoucherConfig, block_config=block_config, active=True)
        cls.config_inactive = baker.make(GiftVoucherConfig, discount_amount=20, active=False)

    def setUp(self):
        self.create_users()
        for user in [self.student_user, self.manager_user, self.child_user]:
            self.make_disclaimer(user)
            self.make_data_privacy_agreement(user)
        self.login(self.student_user)

    def test_login_required(self):
        """
        test that purchase form not shown if not logged in
        """
        self.client.logout()
        resp = self.client.get(self.url)
        assert resp.status_code == 200
        # only active voucher configs shown
        assert [config.id for config in resp.context_data['gift_voucher_configs']] == [self.config_block.id, self.config_total.id]
        assert "<form" not in resp.rendered_content
        assert "Gift vouchers are available to purchase for the following" in resp.rendered_content

    def test_gift_voucher_purchase_options(self):
        resp = self.client.get(self.url)
        form = resp.context_data["form"]
        assert [config.id for config in form.fields["gift_voucher_config"].queryset] == [self.config_block.id, self.config_total.id]
        assert form.fields["user_email"].initial == self.student_user.email

    def test_gift_voucher_purchase(self):
        assert GiftVoucher.objects.exists() is False
        data = {
            "gift_voucher_config": self.config_block.id,
            "user_email": self.student_user.email,
            "user_email1": self.student_user.email,
            "recipient_name": "Donald Duck",
            "message": "Happy Birthday"

        }
        self.client.post(self.url, data)
        assert GiftVoucher.objects.exists() is True
        gift_voucher = GiftVoucher.objects.first()
        assert gift_voucher.paid is False
        assert isinstance(gift_voucher.voucher, BlockVoucher)
        assert gift_voucher.voucher.purchaser_email == self.student_user.email
        assert gift_voucher.voucher.name == "Donald Duck"
        assert gift_voucher.voucher.message == "Happy Birthday"


class GiftVoucherPurchaseUpdateViewTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        block_config = baker.make(BlockConfig, active=True, cost=10)
        cls.config_total = baker.make(GiftVoucherConfig, discount_amount=10, active=True)
        cls.config_block = baker.make(GiftVoucherConfig, block_config=block_config, active=True)
        cls.config_inactive = baker.make(GiftVoucherConfig, discount_amount=20, active=False)

    def setUp(self):
        self.create_users()
        for user in [self.student_user, self.manager_user, self.child_user]:
            self.make_disclaimer(user)
            self.make_data_privacy_agreement(user)
        self.gift_voucher = baker.make(GiftVoucher, gift_voucher_config=self.config_block)
        self.gift_voucher.voucher.purchaser_email = self.student_user.email
        self.gift_voucher.voucher.save()
        self.url = reverse('booking:gift_voucher_update', args=(self.gift_voucher.slug,))
        self.login(self.student_user)

    def test_login_required(self):
        """
        test that purchase update form is shown if not logged in
        """
        self.client.logout()
        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert "<form" in resp.rendered_content

    def test_gift_voucher_purchase_options(self):
        resp = self.client.get(self.url)
        form = resp.context_data["form"]
        assert form.fields["gift_voucher_config"].disabled is False

        self.gift_voucher.activate()
        resp = self.client.get(self.url)
        form = resp.context_data["form"]
        assert form.fields["gift_voucher_config"].disabled is True

    def test_gift_voucher_change_type(self):
        assert isinstance(self.gift_voucher.voucher, BlockVoucher)
        assert TotalVoucher.objects.exists() is False
        data = {
            "gift_voucher_config": self.config_total.id,
            "user_email": self.student_user.email,
            "user_email1": self.student_user.email,
            "recipient_name": "Donald Duck",
            "message": "Happy Birthday"

        }
        self.client.post(self.url, data)
        self.gift_voucher.refresh_from_db()
        assert isinstance(self.gift_voucher.voucher, TotalVoucher)
        assert BlockVoucher.objects.exists() is False

        data.update({"gift_voucher_config": self.config_block.id})
        self.client.post(self.url, data)
        self.gift_voucher.refresh_from_db()
        assert isinstance(self.gift_voucher.voucher, BlockVoucher)
        assert TotalVoucher.objects.exists() is False
