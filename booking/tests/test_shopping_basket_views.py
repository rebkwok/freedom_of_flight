# -*- coding: utf-8 -*-
from datetime import timedelta
from model_bakery import baker
from unittest.mock import Mock, patch

from django.contrib.sites.models import Site
from django.urls import reverse
from django.test import TestCase, override_settings
from django.utils import timezone

from stripe.error import InvalidRequestError

from booking.models import (
    Block, BlockConfig, BlockVoucher, Subscription, SubscriptionConfig, TotalVoucher, GiftVoucher
)
from common.test_utils import TestUsersMixin
from merchandise.models import Product, ProductVariant, ProductPurchase
from merchandise.tests.utils import make_purchase
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
        self.product = baker.make(Product, active=True)
        self.variant = baker.make(ProductVariant, product=self.product, cost=10, size=None)
        self.variant.update_stock(5)
        self.variant.save()

    def test_not_logged_in(self):
        self.client.logout()
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == f"{reverse('account_login')}?next={self.url}"
        gift_voucher = baker.make_recipe("booking.gift_voucher_10")
        session = self.client.session
        session.update({"purchases": {"gift_vouchers": [gift_voucher.id]}})
        session.save()
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == reverse("booking:guest_shopping_basket")

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

    def test_merchandise(self):
        resp = self.client.get(self.url)
        assert list(resp.context_data["unpaid_merchandise"]) == []
        assert resp.context_data["total_cost"] == 0
        assert "Your cart is empty" in resp.rendered_content

        p1 = baker.make(
            ProductPurchase, user=self.student_user, product=self.product,
            cost=self.variant.cost, size=None, paid=False
        )
        baker.make(
            ProductPurchase, user=self.student_user, product=self.product,
            cost=self.variant.cost, size=None, paid=True
        )
        resp = self.client.get(self.url)
        assert [pp.id for pp in resp.context_data["unpaid_merchandise"]] == [p1.id]
        assert resp.context_data["total_cost"] == 10

    def test_merchandise_no_matching_variant(self):
        variant = baker.make(ProductVariant, product=self.product, cost=8, size="unknown")
        variant.update_stock(1)
        p1 = baker.make(
            ProductPurchase, user=self.student_user, product=self.product,
            cost=variant.cost, size=variant.size, paid=False
        )
        p2 = baker.make(
            ProductPurchase, user=self.student_user, product=self.product,
            cost=self.variant.cost, size=None, paid=False
        )
        variant.delete()
        resp = self.client.get(self.url)
        # purchase without current matching variant is deleted and doesn't get included in cart
        assert [pp.id for pp in resp.context_data["unpaid_merchandise"]] == [p2.id]
        assert resp.context_data["total_cost"] == 10
        assert ProductPurchase.objects.count() == 1

    def test_merchandise_expired_purchase(self):
        baker.make(
            ProductPurchase, user=self.student_user, product=self.product,
            cost=self.variant.cost, size=None, paid=False, created_at=timezone.now() - timedelta(minutes=16)
        )
        p2 = baker.make(
            ProductPurchase, user=self.student_user, product=self.product,
            cost=self.variant.cost, size=None, paid=False
        )
        resp = self.client.get(self.url)
        # expired purchase is deleted and doesn't get included in cart
        assert [pp.id for pp in resp.context_data["unpaid_merchandise"]] == [p2.id]
        assert resp.context_data["total_cost"] == 10
        assert ProductPurchase.objects.count() == 1

    def test_shows_user_managed_unpaid_blocks_and_subscriptions_and_merch(self):
        self.login(self.manager_user)
        block1 = baker.make_recipe("booking.dropin_block", block_config=self.dropin_block_config, user=self.manager_user)
        block2 = baker.make_recipe("booking.dropin_block", block_config__cost=10, user=self.child_user)
        subscription = baker.make(Subscription, config=self.subscription_config, user=self.child_user)
        product_purchase = baker.make(
            ProductPurchase, user=self.manager_user, product=self.product,
            cost=self.variant.cost, size=None
        )

        resp = self.client.get(self.url)
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": block1, "original_cost": 20, "voucher_applied": {"code": None, "discounted_cost": None}},
            {"block": block2, "original_cost": 10, "voucher_applied": {"code": None, "discounted_cost": None}}
        ]
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == []
        assert list(resp.context_data["unpaid_subscription_info"]) == [
            {"subscription": subscription, "full_cost": 50, "cost": 50}
        ]
        assert [pp.id for pp in resp.context_data["unpaid_merchandise"]] == [product_purchase.id]
        assert resp.context_data["total_cost"] == 90

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

    def test_total_voucher_application(self):
        voucher = baker.make(TotalVoucher, code="test", discount=50)
        block = baker.make_recipe("booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user)
        resp = self.client.get(self.url)
        assert resp.context_data["total_cost"] == 20

        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        # no voucher code for block
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": block, "original_cost": 20, 'voucher_applied': {'code': None, 'discounted_cost': None}}
        ]
        # but voucher code here because it's a total one
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == [("test", 50, None)]
        assert resp.context_data['total_cost_without_total_voucher'] == 20
        assert resp.context_data["total_cost"] == 10

        block.refresh_from_db()
        assert block.voucher is None
        assert self.client.session["total_voucher_code"] == "test"

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

    def test_remove_total_voucher(self):
        baker.make(TotalVoucher, code="test", discount=50)
        baker.make_recipe("booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user)
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert resp.context_data["total_cost"] == 10  # discount applied
        assert resp.context_data['total_cost_without_total_voucher'] == 20
        assert self.client.session["total_voucher_code"] == "test"

        # remove it
        resp = self.client.post(self.url, data={"remove_voucher_code": "remove_voucher_code", "code": "test"})
        assert resp.context_data["total_cost"] == 20
        assert "total_voucher_code" not in self.client.session

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
        assert resp.context_data["total_cost"] == 20  # discount not applied
        block.refresh_from_db()
        assert block.voucher is None

    def test_refresh_voucher(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50)
        voucher.block_configs.add(self.dropin_block_config)
        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user, voucher=voucher
        )
        resp = self.client.get(self.url)
        assert resp.context_data["total_cost"] == 10  # discount applied

        voucher.activated = False
        voucher.save()
        resp = self.client.post(self.url, {"code": "test", "refresh_voucher_code": True})
        assert resp.context_data["total_cost"] == 20  # discount not applied
        block.refresh_from_db()
        assert block.voucher is None

    def test_voucher_application_multiple_items(self):
        voucher = baker.make(BlockVoucher, code="test", discount=50, item_count=2)
        voucher.block_configs.add(self.dropin_block_config)
        # make 1 block; 2 are required for this voucher
        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user
        )
        resp = self.client.get(self.url)
        assert resp.context_data["total_cost"] == 20

        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert list(resp.context_data["unpaid_block_info"]) == [
            {"block": block, "original_cost": 20, "voucher_applied": {"code": None, "discounted_cost": None}}
        ]
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == []
        assert resp.context_data["total_cost"] == 20

        # make 2 more
        block1, block2 = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
            _quantity=2
        )

        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert list(resp.context_data["unpaid_block_info"]) == [
            {
                "block": block, "original_cost": 20, "voucher_applied": {"code": "test", "discounted_cost": 10}
            },
            {
                "block": block1, "original_cost": 20, "voucher_applied": {"code": "test", "discounted_cost": 10}
            },
            {
                "block": block2, "original_cost": 20, "voucher_applied": {"code": None, "discounted_cost": None}
            },
        ]
        assert list(resp.context_data["applied_voucher_codes_and_discount"]) == [("test", 50, None)]
        assert resp.context_data["total_cost"] == 40
        for bl in [block, block1, block2]:
            bl.refresh_from_db()
        assert block.voucher == voucher
        assert block1.voucher == voucher
        assert block2.voucher is None

        # Delete block 1 and get again; voucher is now applied to block 2
        block1.delete()
        resp = self.client.get(self.url)
        assert resp.context_data["total_cost"] == 20
        assert list(resp.context_data["unpaid_block_info"]) == [
            {
                "block": block, "original_cost": 20,
                "voucher_applied": {"code": "test", "discounted_cost": 10}
            },
            {
                "block": block2, "original_cost": 20,
                "voucher_applied": {"code": "test", "discounted_cost": 10}
            },
        ]

    def test_voucher_validation(self):
        voucher_with_discount = baker.make(BlockVoucher, code="test", discount=50, activated=False)
        voucher_with_discount_amount = baker.make(BlockVoucher, code="test_amount", discount_amount=10, activated=False)

        for voucher in [voucher_with_discount, voucher_with_discount_amount]:
            Block.objects.all().delete()
            baker.make_recipe(
                "booking.dropin_block", block_config=self.dropin_block_config,
                user=self.student_user,
            )
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
            assert resp.context_data["voucher_add_error"] == [f"Code '{voucher.code}' is not valid for any blocks in your cart"]
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
            block = baker.make(
                Block, block_config=self.dropin_block_config, user=self.student_user, voucher=voucher, paid=True
            )
            resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": voucher.code})
            assert resp.context_data["voucher_add_error"] == [
                f"Student User has already used voucher code {voucher.code} the maximum number of times (1)"]

            # voucher existing unpaid block voucher already applied
            voucher.expiry_date = None
            voucher.max_per_user = 3
            voucher.save()

            # voucher already applied, but block not yet paid.  With the 2 block already created in
            # this test (one paid, one unpaid), this will make the total max per user, allowed
            baker.make(
                Block, block_config=self.dropin_block_config, user=self.student_user,
                voucher=voucher, paid=False
            )
            resp = self.client.post(self.url,
                                    data={"add_voucher_code": "add_voucher_code",
                                          "code": voucher.code})
            assert resp.context_data["voucher_add_error"] == []
            # voucher applied to the two unpaid blocks
            assert resp.context_data["total_cost"] == 20

            # voucher max total uses expired
            voucher.max_per_user = None
            voucher.max_vouchers = 3
            voucher.save()
            baker.make(Block, voucher=voucher, block_config=self.dropin_block_config, _quantity=2)

            # voucher used for only some block before it's used up
            resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": voucher.code})
            assert resp.context_data["voucher_add_error"] == [
                f"Voucher code {voucher.code} has limited number of total uses and expired before it could be used for all applicable blocks"
            ]
            # 50% discount applied to 2 blocks only, total == 10 + 10 + 20
            assert resp.context_data["total_cost"] == 40

    def test_total_voucher_validation(self):
        voucher_with_discount = baker.make(TotalVoucher, code="test", discount=50, activated=False)
        voucher_with_discount_amount = baker.make(TotalVoucher, code="test_amount", discount_amount=10, activated=False)
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

            voucher.activated = True
            voucher.save()
            # voucher not started
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
            invoice = baker.make(
                Invoice, username=self.student_user.email, total_voucher_code=voucher.code
            )
            invoice.paid = True
            invoice.save()
            resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": voucher.code})
            assert resp.context_data["voucher_add_error"] == [
                f"You have already used voucher code {voucher.code} the maximum number of times (1)"]
            assert resp.context_data["total_cost"] == 20

            # voucher max total uses expired
            voucher.max_per_user = None
            voucher.max_vouchers = 2
            voucher.save()
            invoices = baker.make(
                Invoice, username=self.student_user.email, total_voucher_code=voucher.code, _quantity=2
            )
            for invoice in invoices:
                invoice.paid = True
                invoice.save()
            resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": voucher.code})
            assert resp.context_data["voucher_add_error"] == [
                f"Voucher code {voucher.code} has limited number of total uses and has expired"]
            assert resp.context_data["total_cost"] == 20

    def test_voucher_validation_with_item_count(self):
        voucher_with_discount = baker.make(
            BlockVoucher, code="test", discount=50, activated=False, item_count=2
        )
        voucher_with_discount_amount = baker.make(
            BlockVoucher, code="test_amount", discount_amount=10, activated=False,
            item_count=2
        )

        for voucher in [voucher_with_discount, voucher_with_discount_amount]:
            Block.objects.all().delete()
            baker.make_recipe(
                "booking.dropin_block", block_config=self.dropin_block_config,
                user=self.student_user,
            )

            # not activated yet
            resp = self.client.post(
                self.url, data={"add_voucher_code": "add_voucher_code", "code": voucher.code}
            )
            assert resp.context_data["voucher_add_error"] == [ "Voucher has not been activated yet"]
            assert resp.context_data["total_cost"] == 20

            # voucher not valid for any blocks
            voucher.activated = True
            voucher.save()
            resp = self.client.post(
                self.url, data={"add_voucher_code": "add_voucher_code", "code": voucher.code}
            )
            assert resp.context_data["voucher_add_error"] == [
                f"Code '{voucher.code}' is not valid for any blocks in your cart"]
            assert resp.context_data["total_cost"] == 20

            # voucher not started
            voucher.block_configs.add(self.dropin_block_config)
            voucher.start_date = timezone.now() + timedelta(2)
            voucher.save()
            resp = self.client.post(
                self.url, data={"add_voucher_code": "add_voucher_code", "code": voucher.code}
            )
            assert resp.context_data["voucher_add_error"] == [
                f"Voucher code is not valid until {voucher.start_date.strftime('%d %b %y')}"
            ]
            assert resp.context_data["total_cost"] == 20

            # voucher expired
            voucher.start_date = timezone.now() - timedelta(5)
            voucher.expiry_date = timezone.now() - timedelta(2)
            voucher.save()
            resp = self.client.post(
                self.url, data={"add_voucher_code": "add_voucher_code", "code": voucher.code}
            )
            assert resp.context_data["voucher_add_error"] == [f"Voucher has expired"]
            assert resp.context_data["total_cost"] == 20

            # voucher max uses per user
            voucher.expiry_date = None
            voucher.save()
            resp = self.client.post(
                self.url, data={"add_voucher_code": "add_voucher_code", "code": voucher.code}
            )

            # voucher has not expired, but this voucher has a required item_count, and there is
            # only 1 unpaid block in the basket, so it's still not valid
            assert resp.context_data["voucher_add_error"] == [
                f"Code '{voucher.code}' can only be used for purchases of 2 valid blocks"
            ]

            # make another block for the cart so it's got a valid number of items
            baker.make_recipe(
                "booking.dropin_block", block_config=self.dropin_block_config,
                user=self.student_user, paid=False
            )
            # max uses 1
            voucher.max_per_user = 1
            voucher.save()

            # make 2 paid blocks with the voucher already applied
            baker.make(
                Block, block_config=self.dropin_block_config, user=self.student_user,
                voucher=voucher, paid=True, _quantity=2
            )
            # Uses is counted as the number of time the voucher has been used; if it's required
            # to be used for 2 blocks, 2 blocks counts as 1 voucher use
            assert voucher.uses() == 1

            resp = self.client.post(
                self.url,
                data={"add_voucher_code": "add_voucher_code", "code": voucher.code}
            )
            assert resp.context_data["voucher_add_error"] == [
                f"Student User has already used voucher code {voucher.code} the maximum number of times (1)"]

            # update max per user so we can use it 2 more times (for 4 more blocks in total)
            voucher.max_per_user = 3
            voucher.save()

            # now it is valid
            resp = self.client.post(
                self.url,
                data={"add_voucher_code": "add_voucher_code", "code": voucher.code}
            )
            # voucher applied to the two unpaid blocks; total == 10 + 10
            assert resp.context_data["voucher_add_error"] == []
            assert resp.context_data["total_cost"] == 20

            # With 3 unpaid blocks, it's valid but only applied to the first 2
            baker.make(
                Block, block_config=self.dropin_block_config, user=self.student_user,
                paid=False, _quantity=1
            )
            resp = self.client.post(
                self.url,
                data={"add_voucher_code": "add_voucher_code", "code": voucher.code}
            )
            # 50% discount applied to 2 blocks only, total == 10 + 10 + 20
            assert resp.context_data["voucher_add_error"] == []
            assert resp.context_data["total_cost"] == 40

            # make a 4th, now it can be applied to all 4
            baker.make(
                Block, block_config=self.dropin_block_config, user=self.student_user,
                paid=False, _quantity=1
            )
            resp = self.client.post(
                self.url,
                data={"add_voucher_code": "add_voucher_code", "code": voucher.code}
            )
            # voucher applied to the two unpaid blocks
            # 50% discount applied to 4 blocks only, total == 10 + 10 + 10 + 10
            assert resp.context_data["total_cost"] == 40

            # voucher uses only applies to paid blocks, so the uses is still 1
            # however the user has 2 uses (4 blocks) in their basket
            assert voucher.uses() == 1

            # voucher max total uses now expired
            voucher.max_per_user = None
            voucher.max_vouchers = 3
            voucher.save()
            # Make another 2 blocks, not for this user, that use the voucher
            baker.make(
                Block,
                voucher=voucher,
                block_config=self.dropin_block_config,
                paid=True,
               _quantity=2
            )

            # voucher used for only some block before it's used up
            resp = self.client.post(
                self.url,
                data={"add_voucher_code": "add_voucher_code", "code": voucher.code}
            )
            assert resp.context_data["voucher_add_error"] == [
                f"Voucher code {voucher.code} has limited number of total uses and expired before it could be used for all applicable blocks"
            ]
            # 50% discount can only be applied for 1 use (2 blocks) only, total == 10 + 10 + 20 + 20
            assert resp.context_data["total_cost"] == 60

    def test_total_voucher_greater_than_checkout_amount(self):
        voucher = baker.make(TotalVoucher, code="test_amount", discount_amount=10, activated=True)
        baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
        )
        # block cost is 20, total shows block cost minus voucher
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test_amount"})
        assert resp.context_data["total_cost"] == 10

        # voucher is valid for x2 block costs, total shows 0
        voucher.discount_amount = 40
        voucher.save()
        resp = self.client.post(self.url, data={"add_voucher_code": "add_voucher_code", "code": "test_amount"})
        assert resp.context_data["total_cost"] == 0

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
            {"block": dropin_block, "original_cost": 20, "voucher_applied": {"code": "test", "discounted_cost": 10}},
            {"block": course_block, "original_cost": 40, "voucher_applied": {"code": "foo", "discounted_cost": 36}},
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


class GuestShoppingBasketTests(TestUsersMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.create_users()

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.url = reverse("booking:guest_shopping_basket")

    def test_with_logged_in_user(self):
        self.login(self.student_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == reverse("booking:shopping_basket")

        self.client.logout()
        resp = self.client.get(self.url)
        assert resp.status_code == 200

    def test_no_voucher(self):
        resp = self.client.get(self.url)
        assert resp.context_data["unpaid_items"] is False
        assert resp.context_data["unpaid_gift_voucher_info"] == []
        assert resp.context_data["total_cost"] == 0

    def test_with_voucher(self):
        session = self.client.session
        gift_voucher = baker.make_recipe("booking.gift_voucher_10")
        session.update({"purchases": {"gift_vouchers": [gift_voucher.id]}})
        session.save()
        resp = self.client.get(self.url)
        assert resp.context_data["unpaid_items"]
        assert resp.context_data["unpaid_gift_voucher_info"] == [
            {"gift_voucher": gift_voucher, "cost": 10}
        ]
        assert resp.context_data["total_cost"] == 10

    def test_with_multiple_vouchers(self):
        session = self.client.session
        gift_voucher1 = baker.make_recipe("booking.gift_voucher_10")
        gift_voucher2 = baker.make_recipe("booking.gift_voucher_10")
        session.update({"purchases": {"gift_vouchers": [gift_voucher1.id, gift_voucher2.id]}})
        session.save()
        resp = self.client.get(self.url)
        assert resp.context_data["unpaid_items"]
        assert resp.context_data["total_cost"] == 20
        assert resp.context_data["unpaid_gift_voucher_info"] == [
            {"gift_voucher": gift_voucher1, "cost": 10},
            {"gift_voucher": gift_voucher2, "cost": 10}
        ]

    def test_with_invalid_vouchers(self):
        session = self.client.session
        gift_voucher1 = baker.make_recipe("booking.gift_voucher_10", paid=True)
        gift_voucher2 = baker.make_recipe("booking.gift_voucher_10")
        session.update({"purchases": {"gift_vouchers": [gift_voucher1.id, gift_voucher2.id, 999]}})
        session.save()
        resp = self.client.get(self.url)
        assert resp.context_data["unpaid_items"]
        assert resp.context_data["total_cost"] == 10
        assert resp.context_data["unpaid_gift_voucher_info"] == [
            {"gift_voucher": gift_voucher2, "cost": 10}
        ]


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

    def test_rechecks_total_vouchers_valid(self):
        # active voucher
        voucher = baker.make(TotalVoucher, code="test_total", discount=50, max_per_user=10, activated=True)
        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
        )
        # Add voucher code to session
        session = self.client.session
        session.update({"total_voucher_code": "test_total"})
        session.save()
        # total includes valid voucher code
        self.client.post(self.url, data={"cart_total": 10}).json()
        block.refresh_from_db()
        assert block.invoice.total_voucher_code == "test_total"

        # make voucher invalid and post again
        voucher.activated = False
        voucher.save()
        resp = self.client.post(self.url, data={"cart_total": 10}).json()
        assert resp["redirect"] is True
        assert resp["url"] == reverse("booking:shopping_basket")
        assert "total_voucher_code" not in self.client.session

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

    def test_rechecks_product_expiry(self):
        product = baker.make(Product)
        variant = baker.make(ProductVariant, product=product, cost=7)
        variant.update_stock(5)
        purchase = baker.make(ProductPurchase, product=product, user=self.student_user, cost=7)
        purchase1 = baker.make(ProductPurchase, product=product, user=self.student_user, cost=7)
        resp = self.client.post(self.url, data={"cart_total": 14}).json()
        assert "redirect" not in resp

        # make one expired
        purchase.created_at = timezone.now() - timedelta(60*60)
        purchase.save()
        resp = self.client.post(self.url, data={"cart_total": 14}).json()
        # redirects to basket
        assert resp["redirect"] is True
        assert resp["url"] == reverse("booking:shopping_basket")
        resp = self.client.get(reverse("booking:shopping_basket"))
        # basket shows the correct cost
        assert resp.context_data["total_cost"] == 7

    def test_creates_invoice_and_applies_to_unpaid_items(self):
        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
        )
        subscription = baker.make(
            Subscription, config=self.subscription_config, user=self.student_user
        )
        gift_voucher = baker.make(GiftVoucher, gift_voucher_config__discount_amount=15)
        gift_voucher.voucher.purchaser_email = self.student_user.email
        gift_voucher.voucher.save()
        product_purchase = make_purchase("S", 10, user=self.student_user)

        assert Invoice.objects.exists() is False
        # total is correct
        resp = self.client.post(self.url, data={"cart_total": 90}).json()
        block.refresh_from_db()
        subscription.refresh_from_db()
        gift_voucher.refresh_from_db()
        product_purchase.refresh_from_db()

        assert Invoice.objects.exists()
        invoice = Invoice.objects.first()
        assert invoice.username == self.student_user.username
        assert invoice.amount == 90
        for item in [block, subscription, gift_voucher, product_purchase]:
            assert item.invoice == invoice

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
        assert resp["url"] == reverse("booking:schedule")

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
        self.product = baker.make(Product, name="Hoodie")
        self.variants = [
            baker.make(ProductVariant, product=self.product, size=size, cost=10)
            for size in ['s', 'm', 'l']
        ]
        for variant in self.variants:
            variant.update_stock(10)

    def test_anon_user_no_unpaid_items(self):
        self.client.logout()
        # If no unpaid items, ignore any cart total passed and return to shopping basket
        resp = self.client.post(self.url, data={"cart_total": 10})
        assert resp.status_code == 302
        assert resp.url == reverse("booking:guest_shopping_basket")

    def test_rechecks_total_anon_user(self):
        self.client.logout()
        session = self.client.session
        gift_voucher1 = baker.make_recipe("booking.gift_voucher_10")
        gift_voucher2 = baker.make_recipe("booking.gift_voucher_10")
        session.update(
            {"purchases": {"gift_vouchers": [gift_voucher1.id, gift_voucher2.id]}})
        session.save()

        # total is incorrect, redirect to basket again
        resp = self.client.post(self.url, data={"cart_total": 10})
        assert resp.status_code == 302
        # redirects to basket, which will do the redirect to guest basket
        assert resp.url == reverse("booking:shopping_basket")

    @patch("booking.views.shopping_basket_views.stripe.PaymentIntent")
    def test_creates_invoice_and_applies_to_unpaid_blocks_and_subscriptions_and_merch(self, mock_payment_intent):
        mock_payment_intent_obj = self.get_mock_payment_intent(id="foo")
        mock_payment_intent.create.return_value = mock_payment_intent_obj
        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
        )
        subscription = baker.make(
            Subscription, config=self.subscription_config, user=self.student_user
        )
        product_purchase = ProductPurchase.objects.create(
            product=self.product, user=self.student_user, cost=10, size="s"
        )
        assert Invoice.objects.exists() is False
        # total is correct
        resp = self.client.post(self.url, data={"cart_total": 80})
        assert resp.status_code == 200
        assert resp.context_data["cart_total"] == 80.00
        block.refresh_from_db()
        subscription.refresh_from_db()
        product_purchase.refresh_from_db()
        assert Invoice.objects.exists()
        invoice = Invoice.objects.first()
        assert invoice.username == self.student_user.username
        assert invoice.amount == 80
        assert block.invoice == invoice
        assert subscription.invoice == invoice
        assert product_purchase.invoice == invoice

    @patch("booking.views.shopping_basket_views.stripe.PaymentIntent")
    def test_creates_invoice_and_applies_to_unpaid_gift_vouchers_anon_user(
            self, mock_payment_intent
    ):
        mock_payment_intent_obj = self.get_mock_payment_intent(id="foo")
        mock_payment_intent.create.return_value = mock_payment_intent_obj
        self.client.logout()
        session = self.client.session
        gift_voucher1 = baker.make_recipe("booking.gift_voucher_10")
        gift_voucher2 = baker.make_recipe("booking.gift_voucher_10")
        session.update(
            {"purchases": {"gift_vouchers": [gift_voucher1.id, gift_voucher2.id]}})
        session.save()

        assert Invoice.objects.exists() is False
        # total is correct
        resp = self.client.post(self.url, data={"cart_total": 20})
        assert resp.status_code == 200
        assert resp.context_data["cart_total"] == 20.00

        gift_voucher1.refresh_from_db()
        gift_voucher2.refresh_from_db()

        assert Invoice.objects.exists()
        invoice = Invoice.objects.first()
        assert invoice.username == ""
        assert invoice.amount == 20
        assert gift_voucher1.invoice == invoice
        assert gift_voucher2.invoice == invoice

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
        assert resp.url == reverse("booking:schedule")

    @patch("booking.views.shopping_basket_views.stripe.PaymentIntent")
    def test_zero_total_with_total_voucher(self, mock_payment_intent):
        mock_payment_intent_obj = self.get_mock_payment_intent(id="foo")
        mock_payment_intent.create.return_value = mock_payment_intent_obj
        baker.make(TotalVoucher, activated=True, code="test", discount_amount=100, max_per_user=10)

        block = baker.make_recipe(
            "booking.dropin_block", block_config=self.dropin_block_config, user=self.student_user,
        )
        gift_voucher = baker.make(
            GiftVoucher,
            gift_voucher_config__discount_amount=10,
        )
        gift_voucher.voucher.purchaser_email = self.student_user.email
        gift_voucher.voucher.save()
        subscription = baker.make(
            Subscription, config=self.subscription_config, user=self.student_user
        )
        product_purchase = make_purchase(user=self.student_user)

        # Call shopping basket view to apply the total voucher code
        self.client.post(reverse('booking:shopping_basket'), data={"add_voucher_code": "add_voucher_code", "code": "test"})
        assert self.client.session["total_voucher_code"] == "test"

        resp = self.client.post(self.url, data={"cart_total": 0})
        for item in [block, gift_voucher, subscription, product_purchase]:
            item.refresh_from_db()
            assert item.paid is True
        assert gift_voucher.voucher.activated is True
        assert resp.status_code == 302
        assert resp.url == reverse("booking:schedule")

        invoice = Invoice.objects.latest("id")
        assert block in invoice.blocks.all()
        assert gift_voucher in invoice.gift_vouchers.all()
        assert product_purchase in invoice.product_purchases.all()
        assert subscription in invoice.subscriptions.all()
        assert invoice.paid is True

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

    def test_check_total_anon_user(self):
        self.client.logout()
        url = reverse("booking:check_total")
        resp = self.client.get(url)
        assert resp.json() == {"total": 0}

        session = self.client.session
        gift_voucher1 = baker.make_recipe("booking.gift_voucher_10")
        gift_voucher2 = baker.make_recipe("booking.gift_voucher_10")
        session.update(
            {"purchases": {"gift_vouchers": [gift_voucher1.id, gift_voucher2.id]}})
        session.save()

        url = reverse("booking:check_total")
        resp = self.client.get(url)
        assert resp.json() == {"total": "20.00"}
