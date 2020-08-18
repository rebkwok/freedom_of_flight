import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, HttpResponseRedirect
from django.views.generic import ListView, DetailView
from django.urls import reverse

from braces.views import LoginRequiredMixin

from booking.models import Block, BlockConfig, Course, Event
from ..forms import AvailableUsersForm
from .views_utils import data_privacy_required, DataPolicyAgreementRequiredMixin
from ..utils import get_view_as_user


logger = logging.getLogger(__name__)


def active_user_blocks(user):
    return [block for block in user.blocks.all() if block.active_block]


def active_user_managed_blocks(core_user, order_by_fields=("purchase_date",)):
    return [block for block in Block.objects.filter(user__in=core_user.managed_users).order_by(*order_by_fields) if block.active_block]


def expired_user_managed_blocks(core_user, order_by_fields=("-expiry_date",)):
    return [block for block in Block.objects.filter(user__in=core_user.managed_users).order_by(*order_by_fields) if
            block.active_block]


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
        return view_as_user.blocks.filter(paid=True).order_by("expiry_date", "-purchase_date")

    def get_context_data(self, **kwargs):
        # Call the base implementation first to get a context
        context = super().get_context_data(**kwargs)
        context["available_users_form"] = AvailableUsersForm(request=self.request, view_as_user=get_view_as_user(self.request))
        return context


class BlockDetailView(DataPolicyAgreementRequiredMixin, LoginRequiredMixin, DetailView):

    model = Block
    template_name = 'booking/block_detail.html'
    context_object_name = "credit_block"


@data_privacy_required
@login_required
def dropin_block_purchase_view(request, event_slug):
    event = get_object_or_404(Event, slug=event_slug)
    dropin_block_configs = list(BlockConfig.objects.filter(active=True, course=False))
    dropin_block_configs.sort(key=lambda x: x.event_type == event.event_type, reverse=True)
    target_configs = [config for config in dropin_block_configs if config.event_type == event.event_type]
    course_block_configs = list(BlockConfig.objects.filter(active=True, course=True))

    available_blocks = {}
    if dropin_block_configs:
        available_blocks.update({"Drop-in Credit Blocks": dropin_block_configs})
    if course_block_configs:
        available_blocks.update({"Course Credit Blocks": course_block_configs})

    context = {
        "available_blocks": available_blocks,
        "user_active_blocks": active_user_managed_blocks(request.user, order_by_fields=("expiry_date", "purchase_date")),
        "related_item": event,
        "target_configs": target_configs
    }

    return render(request, "booking/block_purchase.html", context)


@data_privacy_required
@login_required
def course_block_purchase_view(request, course_slug):
    course = get_object_or_404(Course, slug=course_slug)
    dropin_block_configs = list(BlockConfig.objects.filter(active=True, course=False))
    course_block_configs = list(BlockConfig.objects.filter(active=True, course=True))
    course_block_configs.sort(key=lambda x: x.event_type == course.event_type and x.size == course.number_of_events, reverse=True)
    target_configs = [
        config for config in course_block_configs if config.event_type == course.event_type and
        config.size == course.number_of_events
    ]

    available_blocks = {}
    if course_block_configs:
        available_blocks.update({"Course Credit Blocks": course_block_configs})
    if dropin_block_configs:
        available_blocks.update({"Drop-in Credit Blocks": dropin_block_configs})

    context = {
        "available_blocks": available_blocks,
        "user_active_blocks": active_user_managed_blocks(request.user, order_by_fields=("expiry_date", "purchase_date")),
        "related_item": course,
        "target_configs": target_configs
    }

    return render(request, "booking/block_purchase.html", context)


@data_privacy_required
@login_required
def block_purchase_view(request):
    dropin_block_configs = BlockConfig.objects.filter(active=True, course=False)
    course_block_configs = BlockConfig.objects.filter(active=True, course=True)
    available_blocks = {}
    if dropin_block_configs:
        available_blocks.update({"Drop-in Credit Blocks": dropin_block_configs})
    if course_block_configs:
        available_blocks.update({"Course Credit Blocks": course_block_configs})
    context = {
        "available_blocks": available_blocks,
        "user_active_blocks": active_user_managed_blocks(request.user, order_by_fields=("purchase_date",)),
    }
    return render(request, "booking/block_purchase.html", context)
