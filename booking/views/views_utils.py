from datetime import timedelta

from django.db.models import Count
from django.urls import reverse
from django.shortcuts import HttpResponseRedirect
from django.utils import timezone

from accounts.models import DataPrivacyPolicy, has_active_data_privacy_agreement
from booking.models import Block, Subscription, GiftVoucher
from merchandise.models import ProductPurchase, ProductVariant


class DataPolicyAgreementRequiredMixin:

    def dispatch(self, request, *args, **kwargs):
        # check if the user has an active disclaimer
        if DataPrivacyPolicy.current_version() > 0 and request.user.is_authenticated \
                and not has_active_data_privacy_agreement(request.user):
            return HttpResponseRedirect(
                reverse('accounts:data_privacy_review') + '?next=' + request.path
            )
        return super().dispatch(request, *args, **kwargs)


def data_privacy_required(view_func):
    def wrap(request, *args, **kwargs):
        if (
            DataPrivacyPolicy.current_version() > 0
            and request.user.is_authenticated
            and not has_active_data_privacy_agreement(request.user)
        ):
            return HttpResponseRedirect(
                reverse('accounts:data_privacy_review') + '?next=' + request.path
            )
        return view_func(request, *args, **kwargs)
    return wrap


def redirect_to_voucher_cart(view_func):
    def wrap(request, *args, **kwargs):
        if not request.user.is_authenticated and request.session.get("purchases", {}).get("gift_vouchers"):
            return HttpResponseRedirect(reverse('booking:guest_shopping_basket'))
        return view_func(request, *args, **kwargs)
    return wrap


def _managed_user_plus_self(user):
    return {user, *user.managed_users}


def get_unpaid_user_managed_blocks(user):
    # order by bookings count then user id
    # this puts all direct purchases (single blocks with associated bookings) first
    return Block.objects.filter(
        user__in=_managed_user_plus_self(user), paid=False
    ).annotate(count=Count('bookings__id')).order_by("-count", 'user_id', "id")


def get_unpaid_user_managed_subscriptions(user):
    return Subscription.objects.filter(user__in=_managed_user_plus_self(user), paid=False).order_by('user_id')


def get_unpaid_user_gift_vouchers(user):
    voucher_ids = [
        gift_voucher.id for gift_voucher in GiftVoucher.objects.filter(paid=False)
        if gift_voucher.purchaser_email == user.email
    ]
    return GiftVoucher.objects.filter(id__in=voucher_ids)


def get_unpaid_user_merchandise(user):
    ProductPurchase.cleanup_expired_purchases(user=user)
    unpaid_purchases = ProductPurchase.objects.filter(user=user, paid=False)

    # remove any without valid variants, in case a cost has been updated since
    deleted = False
    for unpaid_purchase in unpaid_purchases:
        variant = ProductVariant.objects.filter(
            size=unpaid_purchase.size, cost=unpaid_purchase.cost, product=unpaid_purchase.product
        )
        if not variant.exists():
            unpaid_purchase.delete()
            deleted = True
    if deleted:
        unpaid_purchases = unpaid_purchases.filter(
            created_at__gte=timezone.now() - timedelta(seconds=60 * 30)
        )

    return unpaid_purchases


def get_unpaid_user_managed_items(user):
    return {
        "blocks": get_unpaid_user_managed_blocks(user),
        "subscription": get_unpaid_user_managed_subscriptions(user),
        "gift_vouchers": get_unpaid_user_gift_vouchers(user),
        "merchandise": get_unpaid_user_merchandise(user)
    }


def total_unpaid_item_count(user):
    return sum([queryset.count() for queryset in get_unpaid_user_managed_items(user).values()])


def get_unpaid_gift_vouchers_from_session(request):
    gift_voucher_ids = request.session.get("purchases", {}).get("gift_vouchers", [])
    gift_vouchers = GiftVoucher.objects.filter(id__in=gift_voucher_ids, paid=False)
    if gift_vouchers.count() != len(gift_voucher_ids):
        request.session.get("purchases", {})["gift_vouchers"] = list(
            gift_vouchers.values_list("id", flat=True))
    return gift_vouchers
