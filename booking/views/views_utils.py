from django.urls import reverse
from django.shortcuts import HttpResponseRedirect

from accounts.models import DataPrivacyPolicy, has_active_disclaimer, has_active_data_privacy_agreement
from booking.models import Block


class DisclaimerRequiredMixin:

    def dispatch(self, request, *args, **kwargs):
        # check if the user has an active disclaimer
        if request.user.is_authenticated and not has_active_disclaimer(request.user):
            return HttpResponseRedirect(reverse('booking:disclaimer_required'))
        return super().dispatch(request, *args, **kwargs)


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


def get_unpaid_user_managed_blocks(user):
    return Block.objects.filter(user__in=user.managed_users, paid=False).order_by('user_id')