from model_bakery import baker

from merchandise.models import ProductPurchase, ProductVariant


def make_purchase(size="S", cost=5, quantity=None, **kwargs):
    _quantity = quantity or 1
    if ProductVariant.objects.filter(size=size, cost=cost).exists():
        var = ProductVariant.objects.filter(size=size, cost=cost).first()
    else:
        var = baker.make(
            ProductVariant,
            product__name="Hoodie",
            product__category__name="Clothing",
            size=size,
            cost=cost
        )
        var.update_stock(5)

    kwargs.update({
        "product": var.product,
        "size": var.size,
        "cost": var.cost
    })
    purchases = baker.make(
        ProductPurchase, **kwargs, _quantity=_quantity
    )

    if quantity is None:
        return purchases[0]
    else:
        return purchases
