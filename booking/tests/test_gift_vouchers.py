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
        self.make_disclaimer(self.student_user)
        self.make_data_privacy_agreement(self.student_user)
        self.login(self.student_user)

    def test_login_not_required(self):
        self.client.logout()
        resp = self.client.get(self.url)
        assert resp.status_code == 200
        # only active voucher configs shown
        assert [config.id for config in resp.context_data['gift_voucher_configs']] == [self.config_block.id, self.config_total.id]
        assert "<form" in resp.rendered_content
        assert "Please check your email address is correct" in resp.rendered_content

        self.login(self.student_user)
        resp = self.client.get(self.url)
        # email check warning only shown for not-logged in users
        assert "Please check your email address is correct" not in resp.rendered_content

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

    def test_gift_voucher_purchase_mismatched_emails(self):
        self.client.logout()
        assert GiftVoucher.objects.exists() is False
        data = {
            "gift_voucher_config": self.config_block.id,
            "user_email": self.student_user.email,
            "user_email1": "foo@foo.com",
            "recipient_name": "Donald Duck",
            "message": "Happy Birthday"

        }
        resp = self.client.post(self.url, data)
        form = resp.context_data["form"]
        assert form.is_valid() is False
        assert form.errors == {
            "user_email1": ["Email addresses do not match"]
        }

    def test_gift_voucher_purchase_no_login(self):
        self.client.logout()
        assert "purchases" not in self.client.session
        assert GiftVoucher.objects.exists() is False
        data = {
            "gift_voucher_config": self.config_block.id,
            "user_email": "unknown@test.com",
            "user_email1": "unknown@test.com",
        }
        resp = self.client.post(self.url, data)
        assert GiftVoucher.objects.exists() is True
        gift_voucher = GiftVoucher.objects.first()
        assert gift_voucher.paid is False
        assert gift_voucher.voucher.purchaser_email == "unknown@test.com"

        assert resp.url == reverse("booking:guest_shopping_basket")
        assert self.client.session["purchases"] == {"gift_vouchers": [gift_voucher.id]}


class GiftVoucherPurchaseUpdateViewTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        block_config = baker.make(BlockConfig, active=True, cost=10)
        cls.config_total = baker.make(GiftVoucherConfig, discount_amount=10, active=True)
        cls.config_block = baker.make(GiftVoucherConfig, block_config=block_config, active=True)
        cls.config_inactive = baker.make(GiftVoucherConfig, discount_amount=20, active=False)

    def setUp(self):
        self.create_users()
        self.make_disclaimer(self.student_user)
        self.make_data_privacy_agreement(self.student_user)
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
        resp = self.client.post(self.url, data)
        self.gift_voucher.refresh_from_db()
        assert isinstance(self.gift_voucher.voucher, BlockVoucher)
        assert TotalVoucher.objects.exists() is False
        assert resp.url == reverse("booking:shopping_basket")

    def test_gift_voucher_change_anon_user(self):
        self.client.logout()
        voucher = baker.make_recipe(
            "booking.gift_voucher_10", paid=False, total_voucher__purchaser_email="anon@test.com"
        )
        data = {
            "gift_voucher_config": voucher.gift_voucher_config.id,
            "user_email": "anon@test.com",
            "user_email1": "anon@test.com",
            "recipient_name": "Donald Duck",
            "message": "Happy Birthday"

        }
        url = reverse('booking:gift_voucher_update', args=(voucher.slug,))
        resp = self.client.post(url, data)
        voucher.refresh_from_db()
        assert voucher.voucher.purchaser_email == "anon@test.com"
        assert voucher.voucher.name == "Donald Duck"
        assert resp.url == reverse("booking:guest_shopping_basket")

    def test_gift_voucher_update_paid_voucher(self):
        self.gift_voucher.paid = True
        self.gift_voucher.save()
        data = {
            "gift_voucher_config": self.config_block.id,
            "user_email": self.student_user.email,
            "user_email1": self.student_user.email,
            "recipient_name": "Mickey Mouse",
            "message": "Happy Birthday"
        }
        resp = self.client.post(self.url, data)
        self.gift_voucher.refresh_from_db()
        assert self.gift_voucher.voucher.name == "Mickey Mouse"
        assert resp.url == reverse("booking:gift_voucher_details", args=(self.gift_voucher.slug,))


class GiftVoucherDetailViewTests(TestUsersMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        block_config = baker.make(BlockConfig, active=True, cost=10)
        cls.config_total = baker.make(GiftVoucherConfig, discount_amount=10, active=True)
        cls.config_block = baker.make(GiftVoucherConfig, block_config=block_config, active=True)

    def setUp(self):
        self.create_users()
        self.make_disclaimer(self.student_user)
        self.make_data_privacy_agreement(self.student_user)
        self.gift_voucher = baker.make(GiftVoucher, gift_voucher_config=self.config_block)
        self.gift_voucher.voucher.purchaser_email = self.student_user.email
        self.gift_voucher.voucher.save()
        self.total_gift_voucher = baker.make(GiftVoucher, gift_voucher_config=self.config_total)
        self.total_gift_voucher.voucher.purchaser_email = self.student_user.email
        self.total_gift_voucher.voucher.save()
        self.block_voucher_url = reverse('booking:gift_voucher_details', args=(self.gift_voucher.slug,))
        self.total_voucher_url = reverse('booking:gift_voucher_details', args=(self.total_gift_voucher.slug,))

    def test_login_not_required(self):
        self.client.logout()
        resp = self.client.get(self.block_voucher_url)
        assert resp.status_code == 200

    def test_voucher_instructions(self):
        resp = self.client.get(self.block_voucher_url)
        assert "Go to Payment Plans and select" in resp.rendered_content
        assert "Go to Shop and add items to shopping cart" not in resp.rendered_content

        resp = self.client.get(self.total_voucher_url)
        assert "Go to Shop and add items to shopping cart" in resp.rendered_content
        assert "Go to Payment Plans and select" not in resp.rendered_content


class VoucherDetailViewTests(TestUsersMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.config_total = baker.make(GiftVoucherConfig, discount_amount=10, active=True)

    def setUp(self):
        self.create_users()
        self.make_disclaimer(self.student_user)
        self.make_data_privacy_agreement(self.student_user)
        self.gift_voucher = baker.make(GiftVoucher, gift_voucher_config=self.config_total)
        self.voucher = baker.make(TotalVoucher, discount_amount=10)

    def test_login_not_required(self):
        self.client.logout()
        resp = self.client.get(reverse("booking:voucher_details", args=(self.voucher.code,)))
        assert resp.status_code == 200
        assert resp.context["voucher"] == self.voucher

    def test_gift_voucher_redirect(self):
        resp = self.client.get(reverse("booking:voucher_details", args=(self.gift_voucher.code,)))
        assert resp.status_code == 302
        assert resp.url == reverse('booking:gift_voucher_details', args=(self.gift_voucher.slug,))
