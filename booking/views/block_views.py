import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.views.generic import ListView

from braces.views import LoginRequiredMixin

from booking.models import (
    Block, BlockConfig, Course, Event
)
from .views_utils import (
    data_privacy_required, DataPolicyAgreementRequiredMixin,
)


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

    def get_queryset(self):
        return Block.objects.filter(user__in=self.request.user.managed_users).order_by("expiry_date", "-purchase_date")

    def get_context_data(self, **kwargs):
        # Call the base implementation first to get a context
        context = super().get_context_data(**kwargs)
        all_active_blocks = [
            block for block in self.get_queryset() if block.active_block
        ]
        all_expired_blocks = [
            block for block in self.get_queryset() if block.paid and not block.active_block
        ]
        active_blocks_by_config = {}
        for block in all_active_blocks:
            active_blocks_by_config.setdefault(block.block_config, []).append(block)
        expired_blocks_by_config = {}
        for block in all_expired_blocks:
            expired_blocks_by_config.setdefault(block.block_config, []).append(block)
        context["active_blocks_by_config"] = active_blocks_by_config
        context["expired_blocks_by_config"] = expired_blocks_by_config
        return context

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
