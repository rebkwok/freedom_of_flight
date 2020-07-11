# -*- coding: utf-8 -*-
from datetime import timedelta
from model_bakery import baker

from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from booking.models import Block, DropInBlockConfig, CourseBlockConfig, BlockVoucher
from common.test_utils import TestUsersMixin
from payments.models import Invoice


class ShoppingBasketViewTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse('booking:shopping_basket')

    def setUp(self):
        super().setUp()
        self.create_users()
        self.make_data_privacy_agreement(self.student_user)
        self.make_data_privacy_agreement(self.manager_user)
        self.make_disclaimer(self.student_user)
        self.login(self.student_user)
        self.dropin_block_config = baker.make(DropInBlockConfig, cost=20)
        self.course_block_config = baker.make(CourseBlockConfig, cost=40)

    def test_no_unpaid_blocks(self):
        resp = self.client.get(self.url)
        assert list(resp.context_data["unpaid_block_info"]) == []
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == []
        assert resp.context_data["total_cost"] == 0
        assert "Your cart is empty" in resp.rendered_content

    def test_with_unpaid_blocks(self):
        block = baker.make_recipe("booking.dropin_block", dropin_block_config=self.dropin_block_config, user=self.student_user)
        resp = self.client.get(self.url)
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": block, "original_cost": 20, "voucher_applied": {"code": None, "discounted_cost": None}}
        ]

        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == []
        assert resp.context_data["total_cost"] == 20

    def test_shows_user_managed_unpaid_blocks(self):
        self.login(self.manager_user)
        block1 = baker.make_recipe("booking.dropin_block", dropin_block_config=self.dropin_block_config, user=self.manager_user)
        block2 = baker.make_recipe("booking.dropin_block", dropin_block_config__cost=10, user=self.child_user)

        resp = self.client.get(self.url)
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": block1, "original_cost": 20, "voucher_applied": {"code": None, "discounted_cost": None}},
            {"block": block2, "original_cost": 10, "voucher_applied": {"code": None, "discounted_cost": None}}
        ]
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == []
        assert resp.context_data["total_cost"] == 30

    def test_voucher_application(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50)
        voucher.dropin_block_configs.add(self.dropin_block_config)
        block = baker.make_recipe("booking.dropin_block", dropin_block_config=self.dropin_block_config, user=self.student_user)
        resp = self.client.get(self.url)
        assert resp.context_data["total_cost"] == 20

        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": block, "original_cost": 20, "voucher_applied": {"code": "test", "discounted_cost": 10}}
        ]
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == [("test", 50)]
        assert resp.context_data["total_cost"] == 10
        block.refresh_from_db()
        assert block.voucher == voucher

    def test_remove_voucher(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50)
        voucher.dropin_block_configs.add(self.dropin_block_config)
        block = baker.make_recipe("booking.dropin_block", dropin_block_config=self.dropin_block_config,
                                  user=self.student_user, voucher=voucher)
        resp = self.client.get(self.url)
        assert resp.context_data["total_cost"] == 10  # discount applied

        # adding it again doesn't do anything
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert resp.context_data["total_cost"] == 10

        # remove it
        resp = self.client.post(self.url, data={"remove_voucher_code": "remove_voucher_code", "code": "test"})
        assert resp.context_data["total_cost"] == 20
        block.refresh_from_db()
        assert block.voucher is None

    def test_voucher_whitespace_removed(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50)
        voucher.dropin_block_configs.add(self.dropin_block_config)
        block = baker.make_recipe("booking.dropin_block", dropin_block_config=self.dropin_block_config,
                                  user=self.student_user)
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "  test  "})
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": block, "original_cost": 20, "voucher_applied": {"code": "test", "discounted_cost": 10}}
        ]
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == [("test", 50)]
        assert resp.context_data["total_cost"] == 10

    def test_existing_voucher_removed_from_block_if_invalid(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50)
        voucher.dropin_block_configs.add(self.dropin_block_config)
        block = baker.make_recipe(
            "booking.dropin_block", dropin_block_config=self.dropin_block_config, user=self.student_user, voucher=voucher
        )
        voucher.activated = False
        voucher.save()
        resp = self.client.get(self.url)
        assert resp.context_data["total_cost"] == 20  # discount applied
        block.refresh_from_db()
        assert block.voucher is None

    def test_voucher_validation(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50, activated=False)
        baker.make_recipe(
            "booking.dropin_block", dropin_block_config=self.dropin_block_config, user=self.student_user,
        )

        # invalid code
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "foo"})
        assert resp.context_data["voucher_add_error"] == ['"foo" is not a valid code']
        assert resp.context_data["total_cost"] == 20

        # not activated yet
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert resp.context_data["voucher_add_error"] == ["Voucher has not been activated yet"]
        assert resp.context_data["total_cost"] == 20

        # voucher not valid for any blocks
        voucher.activated = True
        voucher.save()
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert resp.context_data["voucher_add_error"] == ["Code is not valid for any blocks in your cart"]
        assert resp.context_data["total_cost"] == 20

        # voucher not started
        voucher.dropin_block_configs.add(self.dropin_block_config)
        voucher.start_date = timezone.now() + timedelta(2)
        voucher.save()
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert resp.context_data["voucher_add_error"] == [
            f"Voucher code is not valid until {voucher.start_date.strftime('%d %b %y')}"
        ]
        assert resp.context_data["total_cost"] == 20

        # voucher expired
        voucher.start_date = timezone.now() - timedelta(5)
        voucher.expiry_date = timezone.now() - timedelta(2)
        voucher.save()
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert resp.context_data["voucher_add_error"] == [f"Voucher has expired"]
        assert resp.context_data["total_cost"] == 20

        # voucher max uses per user expired
        voucher.expiry_date = None
        voucher.max_per_user = 1
        voucher.save()
        baker.make(
            Block, dropin_block_config=self.dropin_block_config, user=self.student_user, voucher=voucher, paid=True
        )
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert resp.context_data["voucher_add_error"] == [
            "Student User has already used this voucher the maximum number of times (1)"]

        assert resp.context_data["total_cost"] == 20

        # voucher max total uses expired
        voucher.max_per_user = None
        voucher.max_vouchers = 2
        voucher.save()
        baker.make(Block, voucher=voucher, dropin_block_config=self.dropin_block_config, _quantity=2)

        # voucher used for only some block before it's used up
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert resp.context_data["voucher_add_error"] == [
            "Voucher has limited number of uses and expired before it could be used for all your applicable blocks"
        ]
        assert resp.context_data["total_cost"] == 20

    def test_apply_voucher_to_multiple_blocks(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50, max_per_user=10)
        voucher.dropin_block_configs.add(self.dropin_block_config)
        baker.make_recipe(
            "booking.dropin_block", dropin_block_config=self.dropin_block_config, user=self.student_user,
            _quantity=3
        )
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert resp.context_data["total_cost"] == 30

    def test_apply_multiple_vouchers(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50, max_per_user=10)
        voucher.dropin_block_configs.add(self.dropin_block_config)
        baker.make_recipe(
            "booking.dropin_block", dropin_block_config=self.dropin_block_config, user=self.student_user,
            _quantity=3
        )
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert resp.context_data["total_cost"] == 30

        # second valid voucher replaces the first
        voucher1 = baker.make(BlockVoucher, code="foo", discount=20, max_per_user=10)
        voucher1.dropin_block_configs.add(self.dropin_block_config)
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "foo"})
        assert resp.context_data["total_cost"] == 48

    def test_apply_multiple_vouchers_to_different_blocks(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50, max_per_user=10)
        voucher.dropin_block_configs.add(self.dropin_block_config)
        voucher1 = baker.make(BlockVoucher, code="foo", discount=10, max_per_user=10)
        voucher1.course_block_configs.add(self.course_block_config)
        dropin_block = baker.make_recipe(
            "booking.dropin_block", dropin_block_config=self.dropin_block_config, user=self.student_user,
        )
        course_block = baker.make_recipe(
            "booking.course_block", course_block_config=self.course_block_config, user=self.student_user,
        )
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        # applied to first block only
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": dropin_block, "original_cost": 20, "voucher_applied": {"code": "test", "discounted_cost": 10}},
            {"block": course_block, "original_cost": 40, "voucher_applied": {"code": None, "discounted_cost": None}}

        ]
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == [("test", 50)]
        assert resp.context_data["total_cost"] == 50

        # apply second voucher, applied to second block only
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "foo"})
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": course_block, "original_cost": 40, "voucher_applied": {"code": "foo", "discounted_cost": 36}},
            {"block": dropin_block, "original_cost": 20, "voucher_applied": {"code": "test", "discounted_cost": 10}},
        ]
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == [("foo", 10), ("test", 50)]
        assert resp.context_data["total_cost"] == 46

    def test_payment_button_when_total_is_zero(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50, max_per_user=10)
        voucher.dropin_block_configs.add(self.dropin_block_config)
        baker.make_recipe(
            "booking.dropin_block", dropin_block_config=self.dropin_block_config, user=self.student_user,
        )
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert resp.context_data["total_cost"] == 10
        assert "Checkout with PayPal" in resp.rendered_content

        voucher.discount = 100
        voucher.save()
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert resp.context_data["total_cost"] == 0
        assert "Checkout with PayPal" not in resp.rendered_content
        assert "Submit" in resp.rendered_content


class AjaxShoppingBasketCheckoutTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse('booking:ajax_checkout')

    def setUp(self):
        super().setUp()
        self.create_users()
        self.make_data_privacy_agreement(self.student_user)
        self.make_data_privacy_agreement(self.manager_user)
        self.make_disclaimer(self.student_user)
        self.login(self.student_user)
        self.dropin_block_config = baker.make(DropInBlockConfig, cost=20)
        self.course_block_config = baker.make(CourseBlockConfig, cost=40)

    def test_rechecks_total(self):
        baker.make_recipe(
            "booking.dropin_block", dropin_block_config=self.dropin_block_config, user=self.student_user,
        )
        # total is incorrect, redirect to basket again
        resp = self.client.post(self.url, data={"cart_total": 10}).json()
        assert resp["redirect"] is True
        assert resp["url"] == reverse("booking:shopping_basket")

    def test_rechecks_vouchers_valid(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50, max_per_user=10, activated=False)
        voucher.dropin_block_configs.add(self.dropin_block_config)
        block = baker.make_recipe(
            "booking.dropin_block", dropin_block_config=self.dropin_block_config, user=self.student_user,
            voucher=voucher
        )
        # block has invalid voucher
        resp = self.client.post(self.url, data={"cart_total": 10}).json()
        assert resp["redirect"] is True
        assert resp["url"] == reverse("booking:shopping_basket")
        block.refresh_from_db()
        assert block.voucher is None

    def test_creates_invoice_and_applies_to_unpaid_blocks(self):
        block = baker.make_recipe(
            "booking.dropin_block", dropin_block_config=self.dropin_block_config, user=self.student_user,
        )
        assert Invoice.objects.exists() is False
        # total is correct
        resp = self.client.post(self.url, data={"cart_total": 20}).json()
        block.refresh_from_db()
        assert Invoice.objects.exists()
        invoice = Invoice.objects.first()
        assert invoice.username == self.student_user.username
        assert invoice.amount == 20
        assert block.invoice == invoice
        assert "paypal_form_html" in resp

    def test_zero_total(self):
        voucher = baker.make(BlockVoucher, code="test", discount=100, max_per_user=10)
        voucher.dropin_block_configs.add(self.dropin_block_config)
        block = baker.make_recipe(
            "booking.dropin_block", dropin_block_config=self.dropin_block_config, user=self.student_user,
            voucher=voucher
        )
        resp = self.client.post(self.url, data={"cart_total": 0}).json()
        block.refresh_from_db()
        assert block.paid
        assert block.voucher == voucher
        assert resp["redirect"] is True
        assert resp["url"] == reverse("booking:blocks")

    def test_uses_existing_invoice(self):
        invoice = baker.make(
            Invoice, username=self.student_user.username, amount=20, transaction_id=None
        )
        block = baker.make_recipe(
            "booking.dropin_block", dropin_block_config=self.dropin_block_config, user=self.student_user,
            invoice=invoice
        )
        # total is correct
        resp = self.client.post(self.url, data={"cart_total": 20}).json()
        block.refresh_from_db()
        assert Invoice.objects.count() == 1
        assert block.invoice == invoice
        assert "paypal_form_html" in resp
