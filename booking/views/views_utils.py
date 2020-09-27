from django.urls import reverse
from django.shortcuts import HttpResponseRedirect

from accounts.models import DataPrivacyPolicy, has_active_disclaimer, has_active_data_privacy_agreement
from booking.models import Block, Subscription


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


def get_unpaid_user_managed_items(user):
    return {
        "blocks": get_unpaid_user_managed_blocks(user),
        "subscription": get_unpaid_user_managed_subscriptions(user)
    }

def total_unpaid_item_count(user):
    return sum([queryset.count() for queryset in get_unpaid_user_managed_items(user).values()])
