# -*- coding: utf-8 -*-
from model_bakery import baker
import pytest

from django.urls import reverse
from django.test import TestCase

from merchandise.models import ProductCategory, Product, ProductVariant, ProductPurchase

from common.test_utils import TestUsersMixin


class ProductListViewTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse('merchandise:products')

    def setUp(self):
        self.create_users()
        self.make_disclaimer(self.student_user)
        self.make_data_privacy_agreement(self.student_user)

        self.category = baker.make(ProductCategory, name="Clothing")
        self.product = baker.make(Product, name="Hoodie", category=self.category)

        variants = [
            baker.make(ProductVariant, product=self.product, size=size, cost=10)
            for size in ['s', 'm', 'l']
        ]
        for variant in variants:
            variant.update_stock(10)

    def test_access_without_login(self):
        resp = self.client.get(self.url)
        assert resp.status_code == 200

    def test_active_categories_listed(self):
        assert self.product.active is True
        inactive_category = baker.make(ProductCategory, name="foo")
        inactive_product = baker.make(Product, category=inactive_category, active=False)
        resp = self.client.get(self.url)
        assert ProductCategory.objects.count() == 2
        assert resp.context_data["categories"].count() == 1
        inactive_product.active = True
        inactive_product.save()
        resp = self.client.get(self.url)
        assert resp.context_data["categories"].count() == 2
        assert resp.context_data["selected_category"] is None
        assert resp.context_data["selected_category_id"] == "all"

    def test_selected_category(self):
        new_cat = baker.make(ProductCategory, name="foo")
        new_product = baker.make(Product, category=new_cat)
        baker.make(ProductVariant, product=new_product)

        resp = self.client.get(self.url)
        assert resp.context_data["categories"].count() == 2
        assert resp.context_data["products"].count() == 2

        resp = self.client.get(f"{self.url}?category={new_cat.id}")
        assert resp.context_data["categories"].count() == 2
        assert resp.context_data["products"].count() == 1
        assert resp.context_data["selected_category"] == new_cat
        assert resp.context_data["selected_category_id"] == new_cat.id

    def test_unknown_selected_category(self):
        new_cat = baker.make(ProductCategory, name="foo")
        baker.make(Product, category=new_cat)

        for bad_category in [99, "foo"]:
            resp = self.client.get(f"{self.url}?category={bad_category}")
            assert resp.context_data["categories"].count() == 2
            assert resp.context_data["products"].count() == 2
            assert resp.context_data["selected_category_id"] == "all"


class ProductPurchaseViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.make_disclaimer(self.student_user)
        self.make_data_privacy_agreement(self.student_user)
        self.product = baker.make(Product, name="Hoodie")
        self.variants = [
            baker.make(ProductVariant, product=self.product, size=size, cost=10)
            for size in ['s', 'm', 'l']
        ]
        for variant in self.variants:
            variant.update_stock(10)
        self.client.login(username=self.student_user.username, password="test")

        self.url = reverse('merchandise:product', args=(self.product.id,))

    def test_access_without_login(self):
        """Page is accessible if not logged in, but no purchase option"""
        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert "Add to cart" in resp.rendered_content

        self.client.logout()
        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert "Add to cart" not in resp.rendered_content

    def test_add_item_to_cart(self):
        assert ProductPurchase.objects.exists() is False
        self.client.post(self.url, {"option": self.variants[0].id})
        assert ProductPurchase.objects.count() == 1
        purchase = ProductPurchase.objects.first()
        assert purchase.product == self.product
        assert purchase.user == self.student_user

    def test_add_out_of_stock_item_to_cart(self):
        assert ProductPurchase.objects.exists() is False
        variant = self.variants[0]
        variant.update_stock(0)
        resp = self.client.post(self.url, {"option": variant.id})
        assert ProductPurchase.objects.exists() is False
        assert resp.context_data["form"].errors == {"option": ["out of stock"]}
