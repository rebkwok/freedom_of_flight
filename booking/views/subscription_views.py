import logging

from django.shortcuts import HttpResponseRedirect
from django.views.generic import ListView, DetailView
from django.urls import reverse

from braces.views import LoginRequiredMixin

from booking.models import Subscription
from ..forms import AvailableUsersForm
from .views_utils import DataPolicyAgreementRequiredMixin
from ..utils import get_view_as_user


logger = logging.getLogger(__name__)


class SubscriptionListView(DataPolicyAgreementRequiredMixin, LoginRequiredMixin, ListView):

    model = Subscription
    template_name = 'booking/subscriptions.html'
    context_object_name = "subscriptions"
    paginate_by = 20

    def set_user_on_session(self, request):
        view_as_user = request.POST.get("view_as_user")
        self.request.session["user_id"] = int(view_as_user)

    def post(self, request, *args, **kwargs):
        self.set_user_on_session(request)
        return HttpResponseRedirect(reverse("booking:subscriptions"))

    def get_queryset(self):
        view_as_user = get_view_as_user(self.request)
        return view_as_user.subscriptions.filter(paid=True).order_by("expiry_date", "-purchase_date")

    def get_context_data(self, **kwargs):
        # Call the base implementation first to get a context
        context = super().get_context_data(**kwargs)
        context["available_users_form"] = AvailableUsersForm(request=self.request, view_as_user=get_view_as_user(self.request))
        queryset = list(self.get_queryset())
        # re-sort so expired are last
        queryset.sort(key=lambda x: x.has_expired())
        context["subscriptions"] = queryset
        return context


class SubscriptionDetailView(DataPolicyAgreementRequiredMixin, LoginRequiredMixin, DetailView):

    model = Subscription
    template_name = 'booking/subscription_detail.html'
    context_object_name = "subscription"


