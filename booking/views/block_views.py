import logging

from django.shortcuts import HttpResponseRedirect
from django.views.generic import ListView, DetailView
from django.urls import reverse

from braces.views import LoginRequiredMixin

from ..models import Block
from ..forms import AvailableUsersForm
from .views_utils import DataPolicyAgreementRequiredMixin
from ..utils import get_view_as_user


logger = logging.getLogger(__name__)


class BlockListView(DataPolicyAgreementRequiredMixin, LoginRequiredMixin, ListView):

    model = Block
    template_name = 'booking/blocks.html'
    context_object_name = "blocks"
    paginate_by = 20

    def set_user_on_session(self, request):
        view_as_user = request.POST.get("view_as_user")
        self.request.session["user_id"] = int(view_as_user)

    def post(self, request, *args, **kwargs):
        self.set_user_on_session(request)
        return HttpResponseRedirect(reverse("booking:blocks"))

    def get_queryset(self):
        view_as_user = get_view_as_user(self.request)
        user_blocks = view_as_user.blocks.filter(paid=True).order_by("-purchase_date", "expiry_date")
        if not self.request.GET.get("include-expired"):
            user_blocks = [
                block for block in user_blocks if block.active_block
            ]
        return user_blocks

    def get_context_data(self, **kwargs):
        # Call the base implementation first to get a context
        context = super().get_context_data(**kwargs)
        context["available_users_form"] = AvailableUsersForm(request=self.request, view_as_user=get_view_as_user(self.request))
        if self.request.GET.get("include-expired"):
            context["show_all"] = True
        return context


class BlockDetailView(DataPolicyAgreementRequiredMixin, LoginRequiredMixin, DetailView):

    model = Block
    template_name = 'booking/block_detail.html'
    context_object_name = "credit_block"
