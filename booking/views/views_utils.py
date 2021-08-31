import os
from datetime import timedelta

from django.urls import reverse
from django.shortcuts import HttpResponseRedirect
from django.utils import timezone

from accounts.models import DataPrivacyPolicy, has_active_disclaimer, has_active_data_privacy_agreement
from activitylog.models import ActivityLog
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


def _managed_user_plus_self(user):
    return {user, *user.managed_users}


def get_unpaid_user_managed_blocks(user):

    return Block.objects.filter(user__in=_managed_user_plus_self(user), paid=False).order_by('user_id')


def get_unpaid_user_managed_subscriptions(user):
    return Subscription.objects.filter(user__in=_managed_user_plus_self(user), paid=False).order_by('user_id')


def get_unpaid_user_gift_vouchers(user):
    voucher_ids = [
        gift_voucher.id for gift_voucher in GiftVoucher.objects.filter(paid=False)
        if gift_voucher.purchaser_email == user.email
    ]
    return GiftVoucher.objects.filter(id__in=voucher_ids)


def get_unpaid_user_merchandise(user):
    timeout = os.environ.get("MERCHANDISE_CART_TIMEOUT_SECONDS", 15)
    unpaid_purchases = ProductPurchase.objects.filter(user=user, paid=False)
    unpaid_purchases_within_time = unpaid_purchases.filter(
        created_at__gte=timezone.now() - timedelta(seconds=60 * timeout)
    )
    old_unpaid_purchases = unpaid_purchases.exclude(id__in=unpaid_purchases_within_time.values_list("id", flat=True))

    if old_unpaid_purchases.exists():
        ActivityLog.objects.create(
            log=f"{old_unpaid_purchases.count()} product cart items "
                f"(ids {','.join(str(purchase.id) for purchase in old_unpaid_purchases.all())} "
                f"for user {user} expired and were deleted"
        )
        old_unpaid_purchases.delete()

    # remove any without valid variants, in case a cost has been updated since
    deleted = False
    for unpaid_purchase in unpaid_purchases_within_time:
        variant = ProductVariant.objects.filter(
            size=unpaid_purchase.size, cost=unpaid_purchase.cost, product=unpaid_purchase.product
        )
        if not variant.exists():
            unpaid_purchase.delete()
            deleted = True
    if deleted:
        unpaid_purchases_within_time = unpaid_purchases.filter(
            created_at__gte=timezone.now() - timedelta(seconds=60 * 30)
        )

    return unpaid_purchases_within_time


def get_unpaid_user_managed_items(user):
    return {
        "blocks": get_unpaid_user_managed_blocks(user),
        "subscription": get_unpaid_user_managed_subscriptions(user),
        "gift_vouchers": get_unpaid_user_gift_vouchers(user),
        "merchandise": get_unpaid_user_merchandise(user)
    }


def total_unpaid_item_count(user):
    return sum([queryset.count() for queryset in get_unpaid_user_managed_items(user).values()])
