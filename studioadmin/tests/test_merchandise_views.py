# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from model_bakery import baker

from django.contrib.auth.models import User
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from booking.models import Product, ProductVariant, ProductStock, ProductPurchase, ProductCategory
from common.test_utils import TestUsersMixin
from payments.models import Invoice


class ProductCategoryListViewTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.category = baker.make(ProductCategory, name="test category")
        cls.url = reverse('studioadmin:product_categories')

    def setUp(self):
        self.create_admin_users()
        self.create_users()

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def test_categories_listed(self):
        baker.make(ProductCategory, name="foo")
        baker.make(ProductCategory, name="bar")

        self.client.login(
            username=self.staff_user.username, password='test'
        )
        resp = self.client.get(self.url)
        assert [category.name for category in resp.context_data['categories']] == \
               ["bar", "foo", "test category"]
