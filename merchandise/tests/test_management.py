from datetime import timedelta
import pytest

from django.core import management
from django.utils import timezone

from ..models import ProductPurchase
from .utils import make_purchase


@pytest.mark.django_db
def test_cleanup_expired_purchases():
    purchase = make_purchase(created_at=timezone.now())
    paid_purchase = make_purchase(created_at=timezone.now(), paid=True)
    expired_purchase = make_purchase(
        created_at=timezone.now() - timedelta(60*30),
        time_checked=timezone.now() - timedelta(60*30)
    )
    expired_purchase_recent_check = make_purchase(created_at=timezone.now() - timedelta(60*30))
    expired_purchase_recent_check.mark_checked()
    assert ProductPurchase.objects.count() == 4
    management.call_command('cleanup_expired_product_purchases')
    # only the expired purchase is deleted.  The one with a recent check is left, even though
    # its expiry is earlier
    assert ProductPurchase.objects.count() == 3
    for purchase_item in [purchase, paid_purchase, expired_purchase_recent_check]:
        assert purchase_item.id in ProductPurchase.objects.values_list("id", flat=True)
