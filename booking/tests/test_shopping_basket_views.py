# -*- coding: utf-8 -*-
import json

from datetime import timedelta
from decimal import Decimal
from model_bakery import baker
from urllib.parse import urlsplit

from django.core import mail
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from accounts.models import DataPrivacyPolicy
from booking.models import Event, Booking, Block
from common.test_utils import make_disclaimer_content, make_online_disclaimer, TestUsersMixin, EventTestMixin



class ShoppingBasketViewTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.url = reverse('booking:shopping_basket')

    def setUp(self):
        super().setUp()
        self.create_users()

    def test_no_unpaid_blocks(self):
        pass

    def test_with_unpaid_blocks(self):
        pass

    def test_shows_user_managed_unpaid_blocks(self):
        pass

    def test_block_user_data(self):
        pass

    def test_total_display(self):
        pass

    def test_voucher_application(self):
        pass

    def test_voucher_validation(self):
        pass

    def test_payment_button_when_total_is_zero(self):
        pass


class AjaxShoppingBasketCheckoutTests(TestUsersMixin, TestCase):

    def test_rechecks_total(self):
        pass

    def test_rechecks_vouchers_valid(self):
        pass

    def test_creates_invoice_and_applies_to_unpaid_blocks(self):
        pass

    def test_uses_existing_invoice(self):
        pass

    def test_paypal_cart_form_created_and_rendered(self):
        pass
