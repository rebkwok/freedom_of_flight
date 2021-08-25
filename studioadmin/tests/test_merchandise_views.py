# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from model_bakery import baker

from django.contrib.auth.models import User
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from merchandise.models import Product, ProductVariant, ProductStock, ProductPurchase, ProductCategory
from common.test_utils import TestUsersMixin
from payments.models import Invoice


class StaffLoginMixin:
    def _login(self):
        self.client.login(username=self.staff_user.username, password='test')


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


class ProductCategoryCreateViewTests(TestUsersMixin, StaffLoginMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse('studioadmin:add_product_category')

    def setUp(self):
        self.create_admin_users()
        self.create_users()

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def test_create_category(self):
        self._login()
        assert ProductCategory.objects.exists() is False
        self.client.post(self.url, {"name": "Foo"})
        assert ProductCategory.objects.count() == 1
        assert ProductCategory.objects.first().name == "Foo"


class ProductCategoryUpdateViewTests(TestUsersMixin, StaffLoginMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.category = baker.make(ProductCategory, name="foo")
        self.url = reverse('studioadmin:edit_product_category', args=(self.category.id,))

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def test_update_category(self):
        self._login()
        self.client.post(self.url, {"name": "Bar"})
        assert ProductCategory.objects.count() == 1
        category = ProductCategory.objects.first()
        assert category.id == self.category.id
        assert category.name == "Bar"


class ProductListViewTests(TestUsersMixin, StaffLoginMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        baker.make(Product, name="test product", category__name="A")
        cls.url = reverse('studioadmin:products')

    def setUp(self):
        self.create_admin_users()
        self.create_users()

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def test_categories_listed(self):
        category = baker.make(ProductCategory, name="B")
        baker.make(Product, name="foo", category=category)
        baker.make(Product, name="bar", category=category)

        self._login()
        resp = self.client.get(self.url)
        # ordering is by category, then product name
        assert [product.name for product in resp.context_data['products']] == \
               ["test product", "bar", "foo"]


class ProductCreateUpdateViewTests(TestUsersMixin, StaffLoginMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.category = baker.make(ProductCategory, name="Test")
        cls.url = reverse('studioadmin:add_product')

    def setUp(self):
        self.create_admin_users()
        self.create_users()

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def create_product_with_category(self):
        self._login()
        resp = self.client.get(self.url)
        assert resp.context_data["form"].fields["category"].initial is None

        resp = self.client.get(self.url + f"?category={self.category.id}")
        assert resp.context_data["form"].fields["category"].initial == self.category.id

    def test_create_product(self):
        self._login()
        assert Product.objects.exists() is False
        assert ProductVariant.objects.exists() is False
        assert ProductStock.objects.exists() is False

        data = {
            "category": self.category.id,
            "name": "Test Product",
            "active": True,
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 0,
            "form-0-size": "xs",
            "form-0-cost": 10,
            "form-0-quantity_in_stock": 5,
        }
        self.client.post(self.url, data)
        # One product and associated variants and stock created
        assert Product.objects.count() == 1
        assert ProductVariant.objects.count() == 1
        assert ProductStock.objects.count() == 1

        product = Product.objects.first()
        assert product.name == "Test Product"
        assert product.active is True
        assert product.variants.count() == 1
        variant = product.variants.first()
        assert variant.cost == 10
        assert variant.size == "xs"
        assert variant.stock.quantity == 5

    def test_create_product_no_variants(self):
        self._login()
        data = {
            "category": self.category.id,
            "name": "Test Product",
            "active": True,
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 0,
            "form-0-size": "",
            "form-0-cost": "",
            "form-0-quantity_in_stock": ""
        }
        response = self.client.post(self.url, data)
        formset = response.context_data["product_variant_formset"]
        assert formset.is_valid() is False
        assert formset.non_form_errors() == ["At least one purchase option is needed."]

    def test_create_product_variant_error(self):
        self._login()
        data = {
            "category": self.category.id,
            "name": "Test Product",
            "active": True,
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 0,
            "form-0-size": "sm",
            "form-0-cost": "",
            "form-0-quantity_in_stock": 1
        }
        response = self.client.post(self.url, data)
        formset = response.context_data["product_variant_formset"]
        assert formset.is_valid() is False
        assert formset.non_form_errors() == []
        assert formset.errors == [{"cost": ["This field is required."]}]

    def test_create_product_duplicate_variant_names(self):
        self._login()
        data = {
            "category": self.category.id,
            "name": "Test Product",
            "active": True,
            "form-TOTAL_FORMS": 2,
            "form-INITIAL_FORMS": 0,
            "form-0-size": "sm",
            "form-0-cost": 5,
            "form-0-quantity_in_stock": 1,
            "form-1-size": "sm",
            "form-1-cost": 10,
            "form-1-quantity_in_stock": 1
        }
        response = self.client.post(self.url, data)
        formset = response.context_data["product_variant_formset"]
        assert formset.is_valid() is False
        assert formset.non_form_errors() == ["Sizes must not be duplicated."]

    def test_create_product_only_one_empty_variant_name_allowed(self):
        self._login()
        data = {
            "category": self.category.id,
            "name": "Test Product",
            "active": True,
            "form-TOTAL_FORMS": 2,
            "form-INITIAL_FORMS": 0,
            "form-0-size": "",
            "form-0-cost": 5,
            "form-0-quantity_in_stock": 1,
            "form-1-size": "sm",
            "form-1-cost": 10,
            "form-1-quantity_in_stock": 1
        }
        response = self.client.post(self.url, data)
        formset = response.context_data["product_variant_formset"]
        assert formset.is_valid() is False
        assert formset.non_form_errors() == ["If more than one option is specified, size is required."]

    def test_create_product_delete_ignored(self):
        self._login()
        assert Product.objects.exists() is False
        assert ProductVariant.objects.exists() is False
        assert ProductStock.objects.exists() is False
        data = {
            "category": self.category.id,
            "name": "Test Product",
            "active": True,
            "form-TOTAL_FORMS": 2,
            "form-INITIAL_FORMS": 0,
            "form-0-size": "",
            "form-0-cost": 5,
            "form-0-quantity_in_stock": 1,
            "form-1-size": "",
            "form-1-cost": 10,
            "form-1-quantity_in_stock": 1,
            "form-1-DELETE": True
        }
        self.client.post(self.url, data)
        assert Product.objects.count() == 1
        assert ProductVariant.objects.count() == 1
        assert ProductStock.objects.count() == 1

    def test_create_product_delete_ignored(self):
        self._login()
        assert Product.objects.exists() is False
        assert ProductVariant.objects.exists() is False
        assert ProductStock.objects.exists() is False
        data = {
            "category": self.category.id,
            "name": "Test Product",
            "active": True,
            "form-TOTAL_FORMS": 2,
            "form-INITIAL_FORMS": 0,
            "form-0-size": "",
            "form-0-cost": 5,
            "form-0-quantity_in_stock": 1,
            "form-1-size": "",
            "form-1-cost": 10,
            "form-1-quantity_in_stock": 1,
            "form-1-DELETE": True
        }
        self.client.post(self.url, data)
        assert Product.objects.count() == 1
        assert ProductVariant.objects.count() == 1
        assert ProductStock.objects.count() == 1

    def test_update_product(self):
        self._login()
        product = baker.make(Product, name="Test", category=self.category)
        variant1 = baker.make(ProductVariant, product=product, size="sm", cost=10)
        baker.make(ProductStock, product_variant=variant1, quantity=2)
        variant2 = baker.make(ProductVariant, product=product, size="md", cost=10)
        baker.make(ProductStock, product_variant=variant2, quantity=2)

        data = {
            "category": self.category.id,
            "name": "Test Product",
            "active": True,
            "form-TOTAL_FORMS": 2,
            "form-INITIAL_FORMS": 2,
            "form-0-size": "sm",
            "form-0-cost": 5,
            "form-0-quantity_in_stock": 1,
            "form-1-size": "md",
            "form-1-cost": 10,
            "form-1-quantity_in_stock": 2,
            "form-1-DELETE": True
        }
        self.client.post(reverse('studioadmin:edit_product', args=(product.id,)), data)
        product.refresh_from_db()
        assert product.variants.count() == 1
        variant1.refresh_from_db()
        assert variant1.cost == 5
        assert variant1.stock.quantity == 1
        assert ProductVariant.objects.filter(size="md").exists() is False


class ProductPurchaseListViewTests(TestUsersMixin, StaffLoginMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.product = baker.make(Product, name="test product", category__name="A")
        product_variant = baker.make(ProductVariant, product=cls.product, size='xs', cost=10)
        baker.make(ProductStock, product_variant=product_variant, quantity=10)
        cls.url = reverse('studioadmin:product_purchases', args=(cls.product.id,))

    def setUp(self):
        self.create_admin_users()
        self.create_users()

    def test_staff_only(self):
        self.user_access_test(["staff"], self.url)

    def test_no_purchases(self):
        self._login()
        resp = self.client.get(self.url)
        assert list(resp.context_data['purchases']) == []

    def test_list_purchases_most_recently_created_first(self):
        self._login()
        purchase1 = baker.make(
            ProductPurchase, user=self.student_user, product=self.product, created_at=timezone.now() - timedelta(3),
            size='xs', cost=10
        )
        purchase2 = baker.make(
            ProductPurchase, user=self.manager_user, product=self.product, created_at=timezone.now() - timedelta(2),
            size='xs', cost=10
        )
        resp = self.client.get(self.url)
        # ordered by reverse date created
        assert [purchase.id for purchase in resp.context_data['purchases']] == \
               [purchase2.id, purchase1.id]

    def test_invalid_product(self):
        self._login()
        resp = self.client.get('/studioadmin/merchandise/products/foo/purchases')
        assert resp.status_code == 404

        url = reverse('studioadmin:product_purchases', args=(9999,))
        resp = self.client.get(url)
        assert resp.status_code == 404


class ProductPurchaseCreateUpdateViewTests(TestUsersMixin, StaffLoginMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.product = baker.make(Product, name="test product", category__name="A")
        cls.product_variant = baker.make(ProductVariant, product=cls.product, size='xs', cost=10)
        cls.product_variant1 = baker.make(ProductVariant, product=cls.product, size='sm', cost=10)
        cls.add_url = reverse('studioadmin:add_purchase', args=(cls.product.id,))

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.product_variant.update_stock(10)
        self.product_variant1.update_stock(10)

    def test_staff_only(self):
        self.user_access_test(["staff"], self.add_url)

    def test_create_product_purchase(self):
        self._login()
        assert ProductPurchase.objects.exists() is False

        data = {
            "product": self.product.id,
            "user": self.student_user.id,
            "option": self.product_variant.id
        }
        self.client.post(self.add_url, data)
        # One purchase created
        assert ProductPurchase.objects.count() == 1

        purchase = ProductPurchase.objects.first()
        assert purchase.product == self.product
        assert purchase.size == self.product_variant.size
        assert purchase.cost == self.product_variant.cost
        # relevant stock depleted
        self.product_variant.refresh_from_db()
        self.product_variant1.refresh_from_db()
        assert self.product_variant.current_stock == 9
        assert self.product_variant1.current_stock == 10

    def test_create_product_purchase_out_of_stock(self):
        self._login()
        assert ProductPurchase.objects.exists() is False
        out_of_stock_variant = baker.make(ProductVariant, product=self.product, size="lg", cost=10)
        out_of_stock_variant.update_stock(0)
        data = {
            "product": self.product.id,
            "user": self.student_user.id,
            "option": out_of_stock_variant.id
        }
        resp = self.client.post(self.add_url, data)
        form = resp.context_data["form"]
        assert form.is_valid() is False
        assert form.errors == {"option": ["Out of stock"]}
        # No purchase created
        assert ProductPurchase.objects.exists() is False

    def test_update_product_purchase(self):
        self._login()
        purchase = baker.make(ProductPurchase, product=self.product, size=self.product_variant.size, cost=self.product_variant.cost)
        # confirm stock
        self.product_variant.refresh_from_db()
        self.product_variant1.refresh_from_db()
        assert self.product_variant.current_stock == 9
        assert self.product_variant1.current_stock == 10

        # change option
        data = {
            "product": self.product.id,
            "user": self.student_user.id,
            "option": self.product_variant1.id
        }
        url = reverse('studioadmin:edit_purchase', args=(self.product.id, purchase.id,))
        self.client.post(url, data)
        # One purchase
        assert ProductPurchase.objects.count() == 1

        purchase = ProductPurchase.objects.first()
        assert purchase.product == self.product
        assert purchase.size == self.product_variant1.size

        # relevant stock updated
        self.product_variant.refresh_from_db()
        self.product_variant1.refresh_from_db()
        assert self.product_variant.current_stock == 10
        assert self.product_variant1.current_stock == 9


class AjaxViewsTests(TestUsersMixin, StaffLoginMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.product = baker.make(Product, name="test product", category__name="A")
        self.product1 = baker.make(Product, name="test product1", category__name="B")
        self.product_variant = baker.make(ProductVariant, product=self.product, size='xs', cost=10)
        self.product_variant1 = baker.make(ProductVariant, product=self.product, size='sm', cost=10)
        self.product_variant.update_stock(10)
        self.product_variant1.update_stock(10)
        self.purchase = baker.make(ProductPurchase, user=self.student_user, product=self.product, size='xs', cost=10)
        self._login()

    def test_toggle_product_active(self):
        url = reverse('studioadmin:ajax_toggle_product_active')
        assert self.product.active is True
        assert self.product1.active is True
        self.client.post(url, {"product_id": self.product.id})
        self.product.refresh_from_db()
        self.product1.refresh_from_db()
        assert self.product.active is False
        assert self.product1.active is True
        self.client.post(url, {"product_id": self.product.id})
        self.product.refresh_from_db()
        self.product1.refresh_from_db()
        assert self.product.active is True
        assert self.product1.active is True

    def test_toggle_purchase_paid(self):
        url = reverse('studioadmin:ajax_toggle_purchase_paid')
        assert self.purchase.paid is False
        assert self.purchase.date_paid is None
        self.client.post(url, {"purchase_id": self.purchase.id})
        self.purchase.refresh_from_db()
        assert self.purchase.paid is True
        assert self.purchase.date_paid is not None
        self.client.post(url, {"purchase_id": self.purchase.id})
        self.purchase.refresh_from_db()
        assert self.purchase.paid is False
        assert self.purchase.date_paid is None

    def test_toggle_purchase_received(self):
        url = reverse('studioadmin:ajax_toggle_purchase_received')
        assert self.purchase.received is False
        assert self.purchase.date_received is None
        self.client.post(url, {"purchase_id": self.purchase.id})
        self.purchase.refresh_from_db()
        assert self.purchase.received is True
        assert self.purchase.date_received is not None
        self.client.post(url, {"purchase_id": self.purchase.id})
        self.purchase.refresh_from_db()
        assert self.purchase.received is False
        assert self.purchase.date_received is None
