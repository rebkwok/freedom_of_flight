from model_bakery import baker

from merchandise.models import ProductCategory, ProductPurchase, ProductVariant


def make_purchase(
        category_name="Clothing", product_name="Hoodie", quantity=None, stock=5,
        **purchase_kwargs
):
    size = purchase_kwargs.get("size", "S")
    cost = purchase_kwargs.get("cost", 5)
    purchase_kwargs = {"size": size, "cost": cost, **purchase_kwargs}

    _quantity = quantity or 1
    if ProductVariant.objects.filter(
            product__name=product_name, product__category__name=category_name,
            size=size, cost=cost
    ).exists():
        var = ProductVariant.objects.filter(
            product__name=product_name, product__category__name=category_name,
            size=size, cost=cost
        ).first()
    else:
        cat, _ = ProductCategory.objects.get_or_create(name=category_name)
        var = baker.make(
            ProductVariant,
            product__name=product_name,
            product__category=cat,
            size=size,
            cost=cost
        )
    var.update_stock(stock)
    purchase_kwargs.update({"product": var.product})

    purchases = baker.make(
        ProductPurchase, **purchase_kwargs, _quantity=_quantity
    )

    if quantity is None:
        return purchases[0]
    else:
        return purchases
