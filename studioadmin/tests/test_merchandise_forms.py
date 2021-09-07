# -*- coding: utf-8 -*-
from model_bakery import baker

import pytest

from merchandise.models import ProductPurchase, Product, ProductStock, ProductVariant
from ..forms.merchandise_forms import ProductPurchaseCreateUpdateForm


@pytest.mark.django_db
def test_purchase_create_form_variant_options():
    product = baker.make(Product, active=False)
    for size in ["xs", "sm", "md"]:
        variant = baker.make(ProductVariant, product=product, size=size)
        baker.make(ProductStock, product_variant=variant, quantity=5)

    baker.make(ProductVariant, _quantity=4)
    assert ProductVariant.objects.count() == 7

    # form shows only the variants related to this product
    form = ProductPurchaseCreateUpdateForm(product=product)
    assert form.fields["option"].queryset.count() == 3
    assert form.fields["option"].required is True


@pytest.mark.django_db
def test_purchase_update_form_variant_not_required():
    # variant not required for an update if previous variant has been removed
    product = baker.make(Product, active=False)
    for size in ["xs", "sm", "md"]:
        variant = baker.make(ProductVariant, product=product, size=size, cost=10)
        baker.make(ProductStock, product_variant=variant, quantity=5)

    # purchase with an unknown size
    purchase_unknown = baker.make(ProductPurchase, product=product, size='md', cost=10)
    purchase_known = baker.make(ProductPurchase, product=product, size='sm', cost=10)
    ProductVariant.objects.get(size='md').delete()

    form = ProductPurchaseCreateUpdateForm(product=product, instance=purchase_unknown)
    assert form.fields["option"].queryset.count() == 2
    assert form.fields["option"].required is False

    form1 = ProductPurchaseCreateUpdateForm(product=product, instance=purchase_known)
    assert form1.fields["option"].queryset.count() == 2
    assert form1.fields["option"].required is True
