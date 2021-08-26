from django.contrib.auth.models import User

import pytest

from model_bakery import baker

from merchandise.models import Product, ProductVariant, ProductStock, ProductPurchase, ProductCategory


@pytest.fixture
def user():
    yield User.objects.create_user(
        username='student@test.com', email='student@test.com', password='test',
        first_name="Student", last_name="User"
    )


@pytest.fixture
def category():
    yield baker.make(ProductCategory, name="Clothing")


@pytest.fixture
def product(category):
    yield baker.make(Product, name="Hoodie", category=category)


@pytest.fixture
def product_variants(product):
    variants = [
        baker.make(ProductVariant, product=product, size=size, cost=10)
        for size in ['s', 'm', 'l']
    ]
    for variant in variants:
        baker.make(ProductStock, product_variant=variant, quantity=10)
    yield variants
