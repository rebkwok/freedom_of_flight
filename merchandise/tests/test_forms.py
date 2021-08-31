from model_bakery import baker

import pytest

from ..forms import ProductPurchaseForm
from ..models import ProductVariant

@pytest.mark.django_db
def test_purchase_form_variant_options(product, product_variants):
    baker.make(ProductVariant)
    assert ProductVariant.objects.count() == 4
    form = ProductPurchaseForm(product=product)
    assert list(form.fields["option"].queryset) == list(ProductVariant.objects.filter(product=product))
    assert form.fields["option"].queryset.count() == 3


@pytest.mark.django_db
def test_purchase_form_stock_validation(product, product_variants):
    variant = product_variants[0]
    out_of_stock_variant = product_variants[1]
    out_of_stock_variant.update_stock(0)

    form = ProductPurchaseForm({"option": variant.id}, product=product)
    assert form.is_valid()

    form = ProductPurchaseForm({"option": out_of_stock_variant.id}, product=product)
    assert form.is_valid() is False
    assert form.errors == {"option": ["out of stock"]}
