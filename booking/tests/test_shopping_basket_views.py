# -*- coding: utf-8 -*-
from datetime import timedelta
from model_bakery import baker
from unittest.mock import Mock, patch

from django.contrib.sites.models import Site
from django.urls import reverse
from django.test import TestCase, override_settings
from django.utils import timezone

from stripe.error import InvalidRequestError

from booking.models import Block, BlockConfig, BlockVoucher, Subscription, SubscriptionConfig
from common.test_utils import TestUsersMixin
from payments.models import Invoice, Seller


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
        self.dropin_block_config = baker.make(BlockConfig, cost=20)
        self.course_block_config = baker.make(BlockConfig, course=True, cost=40)
        self.subscription_config = baker.make(SubscriptionConfig, cost=50)

    def test_no_unpaid_blocks(self):
        resp = self.client.get(self.url)
        assert list(resp.context_data["unpaid_block_info"]) == []
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == []
        assert resp.context_data["total_cost"] == 0
        assert "Your cart is empty" in resp.rendered_content

    def test_with_unpaid_blocks(self):
        block = baker.make_recipe("booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user)
        resp = self.client.get(self.url)
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": block, "original_cost": 20, "voucher_applied": {"code": None, "discounted_cost": None}}
        ]

        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == []
        assert resp.context_data["total_cost"] == 20

    def test_with_unpaid_subscriptions(self):
        block = baker.make_recipe("booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user)
        subscription = baker.make(Subscription, config=self.subscription_config, user=self.student_user)

        resp = self.client.get(self.url)
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": block, "original_cost": 20, "voucher_applied": {"code": None, "discounted_cost": None}}
        ]
        assert list(resp.context_data["unpaid_subscription_info"]) == [
            {"subscription": subscription, "full_cost": 50, "cost": 50}
        ]
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == []
        assert resp.context_data["total_cost"] == 70

    def test_with_unpaid_subscription_with_discount(self):
        # config does NOT allow partial purchase
        subscription_config = baker.make(
            SubscriptionConfig,
            cost=40,
            recurring=True,
            start_options="start_date",
            start_date=timezone.now()-timedelta(weeks=2),
            duration=4,
            duration_units="weeks",
            partial_purchase_allowed=False,
        )
        # an unpaid subscription that's for the current period
        subscription = baker.make(
            Subscription, config=subscription_config, user=self.student_user,
            start_date=subscription_config.get_subscription_period_start_date(),
        )

        resp = self.client.get(self.url)
        assert list(resp.context_data["unpaid_block_info"]) == []
        assert list(resp.context_data["unpaid_subscription_info"]) == [
            {"subscription": subscription, "full_cost": 40, "cost": 40}
        ]
        assert resp.context_data["total_cost"] == 40

        # config DOES allow partial purchase
        subscription_config.partial_purchase_allowed = True
        subscription_config.cost_per_week = 10
        subscription_config.save()
        resp = self.client.get(self.url)
        assert list(resp.context_data["unpaid_block_info"]) == []
        assert list(resp.context_data["unpaid_subscription_info"]) == [
            {"subscription": subscription, "full_cost": 40, "cost": 20}
        ]
        assert resp.context_data["total_cost"] == 20

    def test_shows_user_managed_unpaid_blocks_and_subscriptions(self):
        self.login(self.manager_user)
        block1 = baker.make_recipe("booking.dropin_block", block_config=self.dropin_block_config, user=self.manager_user)
        block2 = baker.make_recipe("booking.dropin_block", block_config__cost=10, user=self.child_user)
        subscription = baker.make(Subscription, config=self.subscription_config, user=self.child_user)

        resp = self.client.get(self.url)
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": block1, "original_cost": 20, "voucher_applied": {"code": None, "discounted_cost": None}},
            {"block": block2, "original_cost": 10, "voucher_applied": {"code": None, "discounted_cost": None}}
        ]
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == []
        assert list(resp.context_data["unpaid_subscription_info"]) == [
            {"subscription": subscription, "full_cost": 50, "cost": 50}
        ]
        assert resp.context_data["total_cost"] == 80

    def test_voucher_application(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50)
        voucher.block_configs.add(self.dropin_block_config)
        block = baker.make_recipe("booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user)
        resp = self.client.get(self.url)
        assert resp.context_data["total_cost"] == 20

        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": block, "original_cost": 20, "voucher_applied": {"code": "test", "discounted_cost": 10}}
        ]
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == [("test", 50, None)]
        assert resp.context_data["total_cost"] == 10
        block.refresh_from_db()
        assert block.voucher == voucher

    def test_voucher_application_fixed_amount(self):
        voucher = baker.make(BlockVoucher, code="test", discount_amount=5)
        voucher.block_configs.add(self.dropin_block_config)
        block = baker.make_recipe("booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user)
        resp = self.client.get(self.url)
        assert resp.context_data["total_cost"] == 20

        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": block, "original_cost": 20, "voucher_applied": {"code": "test", "discounted_cost": 15}}
        ]
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == [("test", None, 5)]
        assert resp.context_data["total_cost"] == 15
        block.refresh_from_db()
        assert block.voucher == voucher

    def test_remove_voucher(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50)
        voucher.block_configs.add(self.dropin_block_config)
        block = baker.make_recipe("booking.dropin_block", block_config=self.dropin_block_config,
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
        voucher.block_configs.add(self.dropin_block_config)
        block = baker.make_recipe("booking.dropin_block", block_config=self.dropin_block_config,
                                  user=self.student_user)
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "  test  "})
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": block, "original_cost": 20, "voucher_applied": {"code": "test", "discounted_cost": 10}}
        ]
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == [("test", 50, None)]
        assert resp.context_data["total_cost"] == 10

    def test_existing_voucher_removed_from_block_if_invalid(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50)
        voucher.block_configs.add(self.dropin_block_config)
        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user, voucher=voucher
        )
        voucher.activated = False
        voucher.save()
        resp = self.client.get(self.url)
        assert resp.context_data["total_cost"] == 20  # discount applied
        block.refresh_from_db()
        assert block.voucher is None

    def test_voucher_validation(self):
        voucher_with_discount = baker.make(BlockVoucher, code="test", discount=50, activated=False)
        voucher_with_discount_amount = baker.make(BlockVoucher, code="test_amount", discount_amount=10, activated=False)
        baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
        )
        for voucher in [voucher_with_discount, voucher_with_discount_amount]:
            # invalid code
            resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "foo"})
            assert resp.context_data["voucher_add_error"] == ['"foo" is not a valid code']
            assert resp.context_data["total_cost"] == 20

            # not activated yet
            resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": voucher.code})
            assert resp.context_data["voucher_add_error"] == ["Voucher has not been activated yet"]
            assert resp.context_data["total_cost"] == 20

            # voucher not valid for any blocks
            voucher.activated = True
            voucher.save()
            resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": voucher.code})
            assert resp.context_data["voucher_add_error"] == [f"Code {voucher.code} is not valid for any blocks in your cart"]
            assert resp.context_data["total_cost"] == 20

            # voucher not started
            voucher.block_configs.add(self.dropin_block_config)
            voucher.start_date = timezone.now() + timedelta(2)
            voucher.save()
            resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": voucher.code})
            assert resp.context_data["voucher_add_error"] == [
                f"Voucher code is not valid until {voucher.start_date.strftime('%d %b %y')}"
            ]
            assert resp.context_data["total_cost"] == 20

            # voucher expired
            voucher.start_date = timezone.now() - timedelta(5)
            voucher.expiry_date = timezone.now() - timedelta(2)
            voucher.save()
            resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": voucher.code})
            assert resp.context_data["voucher_add_error"] == [f"Voucher has expired"]
            assert resp.context_data["total_cost"] == 20

            # voucher max uses per user expired
            voucher.expiry_date = None
            voucher.max_per_user = 1
            voucher.save()
            baker.make(
                Block, block_config=self.dropin_block_config, user=self.student_user, voucher=voucher, paid=True
            )
            resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": voucher.code})
            assert resp.context_data["voucher_add_error"] == [
                f"Student User has already used voucher code {voucher.code} the maximum number of times (1)"]

            assert resp.context_data["total_cost"] == 20

            # voucher max total uses expired
            voucher.max_per_user = None
            voucher.max_vouchers = 2
            voucher.save()
            baker.make(Block, voucher=voucher, block_config=self.dropin_block_config, _quantity=2)

            # voucher used for only some block before it's used up
            resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": voucher.code})
            assert resp.context_data["voucher_add_error"] == [
                f"Voucher code {voucher.code} has limited number of total uses and expired before it could be used for all applicable blocks"
            ]
            assert resp.context_data["total_cost"] == 20

    def test_apply_voucher_to_multiple_blocks(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50, max_per_user=10)
        voucher.block_configs.add(self.dropin_block_config)
        baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
            _quantity=3
        )
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert resp.context_data["total_cost"] == 30

    def test_apply_multiple_vouchers(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50, max_per_user=10)
        voucher.block_configs.add(self.dropin_block_config)
        baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
            _quantity=3
        )
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert resp.context_data["total_cost"] == 30

        # second valid voucher replaces the first
        voucher1 = baker.make(BlockVoucher, code="foo", discount=20, max_per_user=10)
        voucher1.block_configs.add(self.dropin_block_config)
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "foo"})
        assert resp.context_data["total_cost"] == 48

    def test_apply_multiple_vouchers_to_different_blocks(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50, max_per_user=10)
        voucher.block_configs.add(self.dropin_block_config)
        voucher1 = baker.make(BlockVoucher, code="foo", discount=10, max_per_user=10)
        voucher1.block_configs.add(self.course_block_config)
        dropin_block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
        )
        course_block = baker.make_recipe(
            "booking.course_block", block_config=self.course_block_config, user=self.student_user,
        )
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        # applied to first block only
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": dropin_block, "original_cost": 20, "voucher_applied": {"code": "test", "discounted_cost": 10}},
            {"block": course_block, "original_cost": 40, "voucher_applied": {"code": None, "discounted_cost": None}}

        ]
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == [("test", 50, None)]
        assert resp.context_data["total_cost"] == 50

        # apply second voucher, applied to second block only
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "foo"})
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": course_block, "original_cost": 40, "voucher_applied": {"code": "foo", "discounted_cost": 36}},
            {"block": dropin_block, "original_cost": 20, "voucher_applied": {"code": "test", "discounted_cost": 10}},
        ]
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == [("foo", 10, None), ("test", 50, None)]
        assert resp.context_data["total_cost"] == 46

    @override_settings(CHECKOUT_METHOD="paypal")
    def test_payment_button_when_total_is_zero(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50, max_per_user=10)
        voucher.block_configs.add(self.dropin_block_config)
        baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
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

    @override_settings(CHECKOUT_METHOD="stripe")
    def test_stripe_payment_button_when_total_is_zero(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50, max_per_user=10)
        voucher.block_configs.add(self.dropin_block_config)
        baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
        )
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert resp.context_data["total_cost"] == 10
        assert "Checkout" in resp.rendered_content

        voucher.discount = 100
        voucher.save()
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert resp.context_data["total_cost"] == 0
        assert "Checkout" not in resp.rendered_content
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
        self.make_disclaimer(self.child_user)
        self.login(self.student_user)
        self.dropin_block_config = baker.make(BlockConfig, cost=20)
        self.course_block_config = baker.make(BlockConfig, cost=40)
        self.subscription_config = baker.make(SubscriptionConfig, cost=50)

    def test_no_unpaid_items(self):
        # If no unpaid items, ignore any cart total passed and return to shopping basket
        resp = self.client.post(self.url, data={"cart_total": 10}).json()
        assert resp["redirect"] is True
        assert resp["url"] == reverse("booking:shopping_basket")

    def test_rechecks_total(self):
        baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
        )
        # total is incorrect, redirect to basket again
        resp = self.client.post(self.url, data={"cart_total": 10}).json()
        assert resp["redirect"] is True
        assert resp["url"] == reverse("booking:shopping_basket")

    def test_rechecks_vouchers_valid(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50, max_per_user=10, activated=False)
        voucher.block_configs.add(self.dropin_block_config)
        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
            voucher=voucher
        )
        # block has invalid voucher
        resp = self.client.post(self.url, data={"cart_total": 10}).json()
        assert resp["redirect"] is True
        assert resp["url"] == reverse("booking:shopping_basket")
        block.refresh_from_db()
        assert block.voucher is None

    def test_rechecks_partial_subscription_costs(self):
        subscription_config = baker.make(
            SubscriptionConfig,
            cost=40,
            recurring=True,
            start_options="start_date",
            start_date=timezone.now() - timedelta(weeks=2),
            duration=4,
            duration_units="weeks",
            partial_purchase_allowed=True,
            cost_per_week=10,
        )
        # an unpaid subscription that's for the current period
        subscription = baker.make(
            Subscription, config=subscription_config, user=self.student_user,
            start_date=subscription_config.get_subscription_period_start_date(),
        )
        # total shows the full subscription price, but it's now half way through
        resp = self.client.post(self.url, data={"cart_total": 40}).json()
        # redirects to basket
        assert resp["redirect"] is True
        assert resp["url"] == reverse("booking:shopping_basket")
        resp = self.client.get(reverse("booking:shopping_basket"))
        # basket shows the correct cost
        assert resp.context_data["total_cost"] == 20

    def test_creates_invoice_and_applies_to_unpaid_blocks_and_subscriptions(self):
        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
        )
        subscription = baker.make(
            Subscription, config=self.subscription_config, user=self.student_user
        )
        assert Invoice.objects.exists() is False
        # total is correct
        resp = self.client.post(self.url, data={"cart_total": 70}).json()
        block.refresh_from_db()
        subscription.refresh_from_db()
        assert Invoice.objects.exists()
        invoice = Invoice.objects.first()
        assert invoice.username == self.student_user.username
        assert invoice.amount == 70
        assert block.invoice == invoice
        assert subscription.invoice == invoice
        assert "paypal_form_html" in resp

    def test_invoice_user_is_manager_user(self):
        self.login(self.manager_user)
        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.child_user,
        )
        subscription = baker.make(
            Subscription, config=self.subscription_config, user=self.child_user
        )
        assert Invoice.objects.exists() is False
        # total is correct
        self.client.post(self.url, data={"cart_total": 70}).json()
        block.refresh_from_db()
        subscription.refresh_from_db()
        assert Invoice.objects.exists()
        invoice = Invoice.objects.first()
        assert invoice.username == self.manager_user.username
        assert invoice.amount == 70
        assert block.invoice == invoice
        assert subscription.invoice == invoice

    def test_creates_invoice_and_applies_to_unpaid_blocks_with_vouchers(self):
        voucher = baker.make(BlockVoucher, discount=10)
        voucher.block_configs.add(self.dropin_block_config)
        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
            voucher=voucher
        )
        assert Invoice.objects.exists() is False
        # total is correct
        resp = self.client.post(self.url, data={"cart_total": 18}).json()
        block.refresh_from_db()
        assert Invoice.objects.exists()
        invoice = Invoice.objects.first()
        assert invoice.username == self.student_user.username
        assert invoice.amount == 18
        assert block.invoice == invoice
        assert "paypal_form_html" in resp

        paypal_form_html = resp['paypal_form_html']
        assert 'value="18.00"' in paypal_form_html

    def test_zero_total(self):
        voucher = baker.make(BlockVoucher, code="test", discount=100, max_per_user=10)
        voucher.block_configs.add(self.dropin_block_config)
        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
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
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
            invoice=invoice
        )
        # total is correct
        resp = self.client.post(self.url, data={"cart_total": 20}).json()
        block.refresh_from_db()
        assert Invoice.objects.count() == 1
        assert block.invoice == invoice
        assert "paypal_form_html" in resp


class StripeCheckoutTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse('booking:stripe_checkout')

    def get_mock_payment_intent(self, **params):
        defaults = {
            "id": "mock-intent-id",
            "amount": 1000,
            "description": "",
            "status": "succeeded",
            "metadata": {},
            "currency": "gbp",
            "client_secret": "secret"
        }
        options = {**defaults, **params}
        return Mock(**options)

    def setUp(self):
        super().setUp()
        baker.make(Seller, site=Site.objects.get_current())
        self.create_users()
        self.make_data_privacy_agreement(self.student_user)
        self.make_data_privacy_agreement(self.manager_user)
        self.make_disclaimer(self.student_user)
        self.make_disclaimer(self.child_user)
        self.login(self.student_user)
        self.dropin_block_config = baker.make(BlockConfig, cost=20)
        self.course_block_config = baker.make(BlockConfig, cost=40)
        self.subscription_config = baker.make(SubscriptionConfig, cost=50)

    @patch("booking.views.shopping_basket_views.stripe.PaymentIntent")
    def test_creates_invoice_and_applies_to_unpaid_blocks_and_subscriptions(self, mock_payment_intent):
        mock_payment_intent_obj = self.get_mock_payment_intent(id="foo")
        mock_payment_intent.create.return_value = mock_payment_intent_obj
        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
        )
        subscription = baker.make(
            Subscription, config=self.subscription_config, user=self.student_user
        )
        assert Invoice.objects.exists() is False
        # total is correct
        resp = self.client.post(self.url, data={"cart_total": 70})
        assert resp.status_code == 200
        assert resp.context_data["cart_total"] == 70.00
        block.refresh_from_db()
        subscription.refresh_from_db()
        assert Invoice.objects.exists()
        invoice = Invoice.objects.first()
        assert invoice.username == self.student_user.username
        assert invoice.amount == 70
        assert block.invoice == invoice
        assert subscription.invoice == invoice

    @patch("booking.views.shopping_basket_views.stripe.PaymentIntent")
    def test_invoice_user_is_manager_user(self, mock_payment_intent):
        mock_payment_intent_obj = self.get_mock_payment_intent(id="foo")
        mock_payment_intent.create.return_value = mock_payment_intent_obj
        self.login(self.manager_user)
        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.child_user,
        )
        subscription = baker.make(
            Subscription, config=self.subscription_config, user=self.child_user
        )
        assert Invoice.objects.exists() is False
        # total is correct
        self.client.post(self.url, data={"cart_total": 70})
        block.refresh_from_db()
        subscription.refresh_from_db()
        assert Invoice.objects.exists()
        invoice = Invoice.objects.first()
        assert invoice.username == self.manager_user.username
        assert invoice.amount == 70
        assert block.invoice == invoice
        assert subscription.invoice == invoice

    @patch("booking.views.shopping_basket_views.stripe.PaymentIntent")
    def test_creates_invoice_and_applies_to_unpaid_blocks_with_vouchers(self, mock_payment_intent):
        mock_payment_intent_obj = self.get_mock_payment_intent(id="foo")
        mock_payment_intent.create.return_value = mock_payment_intent_obj
        voucher = baker.make(BlockVoucher, discount=10)
        voucher.block_configs.add(self.dropin_block_config)
        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
            voucher=voucher
        )
        assert Invoice.objects.exists() is False
        # total is correct
        resp = self.client.post(self.url, data={"cart_total": 18})
        assert resp.status_code == 200
        block.refresh_from_db()
        assert Invoice.objects.exists()
        invoice = Invoice.objects.first()
        assert invoice.username == self.student_user.username
        assert invoice.amount == 18
        assert block.invoice == invoice
        assert resp.context_data["cart_total"] == 18.00

    @patch("booking.views.shopping_basket_views.stripe.PaymentIntent")
    def test_zero_total(self, mock_payment_intent):
        mock_payment_intent_obj = self.get_mock_payment_intent(id="foo")
        mock_payment_intent.create.return_value = mock_payment_intent_obj
        voucher = baker.make(BlockVoucher, code="test", discount=100, max_per_user=10)
        voucher.block_configs.add(self.dropin_block_config)
        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
            voucher=voucher
        )
        resp = self.client.post(self.url, data={"cart_total": 0})
        block.refresh_from_db()
        assert block.paid
        assert block.voucher == voucher
        assert resp.status_code == 302
        assert resp.url == reverse("booking:blocks")

    @patch("booking.views.shopping_basket_views.stripe.PaymentIntent")
    def test_uses_existing_invoice(self, mock_payment_intent):
        mock_payment_intent_obj = self.get_mock_payment_intent(id="foo")
        mock_payment_intent.modify.return_value = mock_payment_intent_obj
        invoice = baker.make(
            Invoice, username=self.student_user.username, amount=20, transaction_id=None, paid=False,
            stripe_payment_intent_id="foo"
        )
        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
            invoice=invoice
        )
        # total is correct
        resp = self.client.post(self.url, data={"cart_total": 20})
        block.refresh_from_db()
        assert Invoice.objects.count() == 1
        assert block.invoice == invoice
        assert resp.context_data["cart_total"] == 20.00

    def test_no_seller(self):
        Seller.objects.all().delete()
        baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
        )
        resp = self.client.post(self.url, data={"cart_total": 20})
        assert resp.status_code == 200
        assert resp.context_data["preprocessing_error"] is True

    @patch("booking.views.shopping_basket_views.stripe.PaymentIntent")
    def test_invoice_already_succeeded(self, mock_payment_intent):
        mock_payment_intent_obj = self.get_mock_payment_intent(id="foo", status="succeeded")
        mock_payment_intent.modify.side_effect = InvalidRequestError("error", None)
        mock_payment_intent.retrieve.return_value = mock_payment_intent_obj

        invoice = baker.make(
            Invoice, username=self.student_user.username, amount=20, transaction_id=None, paid=False,
            stripe_payment_intent_id="foo"
        )
        baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
            invoice=invoice
        )
        resp = self.client.post(self.url, data={"cart_total": 20})
        assert resp.context_data["preprocessing_error"] is True

    @patch("booking.views.shopping_basket_views.stripe.PaymentIntent")
    def test_other_error_modifying_payment_intent(self, mock_payment_intent):
        mock_payment_intent_obj = self.get_mock_payment_intent(id="foo", status="pending")
        mock_payment_intent.modify.side_effect = InvalidRequestError("error", None)
        mock_payment_intent.retrieve.return_value = mock_payment_intent_obj

        invoice = baker.make(
            Invoice, username=self.student_user.username, amount=20, transaction_id=None, paid=False,
            stripe_payment_intent_id="foo"
        )
        baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
            invoice=invoice
        )
        resp = self.client.post(self.url, data={"cart_total": 20})
        assert resp.context_data["preprocessing_error"] is True

    def test_check_total(self):
        # This is the last check immediately before submitting payment; just returns the current total
        # so the js can check it
        url = reverse("booking:check_total")
        resp = self.client.get(url)
        assert resp.json() == {"total": 0}

        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
        )
        subscription = baker.make(
            Subscription, config=self.subscription_config, user=self.student_user
        )
        resp = self.client.get(url)
        assert resp.json() == {"total": "70.00"}

        subscription.paid = True
        subscription.save()
        voucher = baker.make(BlockVoucher, code="test", discount=10, max_per_user=10)
        voucher.block_configs.add(self.dropin_block_config)
        block.voucher = voucher
        block.save()
        resp = self.client.get(url)
        assert resp.json() == {"total": "18.00"}
