from datetime import datetime

from django.core.exceptions import ValidationError
from django.utils import timezone

import pytest

from model_bakery import baker

from merchandise.models import Product, ProductVariant, ProductStock, ProductPurchase, ProductCategory


@pytest.mark.django_db
def test_product_category_str(category):
    assert str(category) == "Clothing"


@pytest.mark.django_db
def test_product_category_active(category, product):
    assert ProductCategory.objects.active().count() == 1
    product.active = False
    product.save()
    assert ProductCategory.objects.active().exists() is False


@pytest.mark.django_db
def test_product_str(product):
    assert str(product) == "Clothing - Hoodie"


@pytest.mark.django_db
def test_product_variant_str(product_variants):
    assert str(product_variants[0]) == "Clothing - Hoodie - size s"


@pytest.mark.django_db
def test_product_min_and_max_cost(product, product_variants):
    assert product.min_cost() == 10
    assert product.max_cost() == 10
    baker.make(ProductVariant, product=product, cost=5, size='xs')
    assert product.min_cost() == 5
    assert product.max_cost() == 10

    ProductVariant.objects.all().delete()
    assert product.min_cost() == product.max_cost() == None


@pytest.mark.django_db
def test_product_variant_current_stock(product_variants):
    variant = product_variants[0]
    assert variant.current_stock == 10
    variant.update_stock(5)
    assert variant.current_stock == 5

    new_variant = baker.make(ProductVariant, product=variant.product, size='xl', cost=5)
    assert ProductStock.objects.filter(product_variant=new_variant).exists() is False
    assert new_variant.current_stock == 0
    assert ProductStock.objects.filter(product_variant=new_variant).exists() is True

    assert variant.out_of_stock is False
    assert new_variant.out_of_stock is True


@pytest.mark.django_db
def test_product_stock_str(product_variants):
    variant = product_variants[0]
    stock = variant.stock
    assert str(stock) == "Clothing - Hoodie - size s - in stock 10"


@pytest.mark.django_db
def test_product_purchase_str(product_variants, user):
    variant = product_variants[0]
    purchase = baker.make(ProductPurchase, user=user, product=variant.product, size=variant.size, cost=variant.cost)
    assert str(purchase) == f"Clothing - Hoodie - s - {user.username} - not paid"

    purchase.paid = True
    purchase.save()
    assert str(purchase) == f"Clothing - Hoodie - s - {user.username} - paid"

    purchase.size = ""
    purchase.save()
    assert str(purchase) == f"Clothing - Hoodie - {user.username} - paid"


@pytest.mark.django_db
def test_new_product_purchase_must_match_current_variant(product_variants, user):
    variant = product_variants[0]

    with pytest.raises(ProductVariant.DoesNotExist):
        baker.make(ProductPurchase, user=user, product=variant.product, size="unk", cost=10)

    purchase = baker.make(ProductPurchase, user=user, product=variant.product, size=variant.size, cost=variant.cost)

    # After initial creation, we can update the size/cost to a non-matching variant
    purchase.size = "unk"
    purchase.cost = 7
    purchase.save()


@pytest.mark.django_db
def test_product_purchase_check_stock(product_variants, user):
    variant = product_variants[0]
    variant1 = product_variants[1]
    purchase = baker.make(ProductPurchase, user=user, product=variant.product, size=variant.size, cost=variant.cost)
    assert variant.current_stock == 9
    variant.update_stock(0)
    assert variant.current_stock == 0

    # we can update the purchase's cost
    purchase.cost = 100
    purchase.save()

    # we can't update the purchase's size to a different size that's out of stock
    variant1.update_stock(0)
    assert variant1.current_stock == 0
    purchase.size = variant1.size
    purchase.cost = variant1.cost

    with pytest.raises(ValidationError):
        purchase.save()

    # a new purchase for this variant fails the stock check
    with pytest.raises(ValidationError):
        baker.make(ProductPurchase, user=user, product=variant.product, size=variant.size, cost=variant.cost)


@pytest.mark.django_db
@pytest.mark.freeze_time("2021-08-01")
def test_product_purchase_set_date_created_at_on_save(user, product, product_variants):
    purchase = baker.make(ProductPurchase, user=user, product=product, size='s', cost=10)
    assert purchase.created_at == datetime(2021, 8, 1, 0, 0, tzinfo=timezone.utc)


@pytest.mark.django_db
@pytest.mark.freeze_time("2021-08-01")
def test_product_purchase_set_date_paid_on_save(user, product, product_variants):
    purchase = baker.make(ProductPurchase, user=user, product=product, size='s', cost=10)
    assert purchase.paid is False
    assert purchase.date_paid is None
    purchase.paid = True
    purchase.save()
    assert purchase.date_paid == datetime(2021, 8, 1, 0, 0, tzinfo=timezone.utc)


@pytest.mark.django_db
@pytest.mark.freeze_time("2021-08-01")
def test_product_purchase_set_date_received_on_save(user, product, product_variants):
    purchase = baker.make(ProductPurchase, user=user, product=product, size='s', cost=10)
    assert purchase.received is False
    assert purchase.date_received is None
    purchase.received = True
    purchase.save()
    assert purchase.date_received == datetime(2021, 8, 1, 0, 0, tzinfo=timezone.utc)


@pytest.mark.django_db
def test_product_purchase_update_stock(user, product, product_variants):
    for variant in product_variants:
        assert variant.current_stock == 10

    variant1, variant2 = product_variants[0], product_variants[1]

    # making a purchase depletes stock
    purchase = baker.make(
        ProductPurchase, user=user, product=product, size=variant1.size, cost=variant1.cost
    )
    variant1.refresh_from_db()
    assert variant1.current_stock == 9
    baker.make(
        ProductPurchase, user=user, product=product, size=variant1.size,
        cost=variant1.cost
    )
    variant1.refresh_from_db()
    assert variant1.current_stock == 8

    # changing size/costs to another matching variant updates stock for both
    purchase.size = variant2.size
    purchase.cost = variant2.cost
    purchase.save()
    variant1.refresh_from_db()
    variant2.refresh_from_db()
    assert variant1.current_stock == 9
    assert variant2.current_stock == 9

    # deleting purchases updates stock
    purchase.delete()
    variant1.refresh_from_db()
    variant2.refresh_from_db()
    assert variant1.current_stock == 9
    assert variant2.current_stock == 10
