import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.urls import reverse
from django.http import JsonResponse
from django.shortcuts import HttpResponseRedirect, render, get_object_or_404
from django.views.generic import ListView, CreateView, DeleteView
from django.core.mail import send_mail
from django.template.loader import get_template
from django.views.decorators.http import require_http_methods

from braces.views import LoginRequiredMixin

from booking.models import (
    Block, DropInBlockConfig, Course, CourseType, Event, EventType, CourseBlockConfig
)
from .views_utils import (
    data_privacy_required, DataPolicyAgreementRequiredMixin,
    get_unpaid_user_managed_blocks
)


from activitylog.models import ActivityLog

logger = logging.getLogger(__name__)


def active_user_blocks(user):
    return [block for block in user.blocks.all() if block.active_block]


def active_user_managed_blocks(core_user, order_by_fields=("purchase_date",)):
    return [block for block in Block.objects.filter(user__in=core_user.managed_users).order_by(*order_by_fields) if block.active_block]


class BlockListView(DataPolicyAgreementRequiredMixin, LoginRequiredMixin, ListView):

    model = Block
    template_name = 'booking/blocks.html'

    def get_queryset(self):
        return active_user_managed_blocks(self.request.user, order_by_fields=("purchase_date",))

    def get_context_data(self, **kwargs):
        # Call the base implementation first to get a context
        context = super().get_context_data(**kwargs)
        all_active_blocks = self.get_queryset()
        active_blocks_by_config = {}
        for block in all_active_blocks:
            active_blocks_by_config.setdefault(block.block_config, []).append(block)
        context["active_blocks_by_config"] = active_blocks_by_config
        return context

@data_privacy_required
@login_required
def dropin_block_purchase_view(request, event_slug):
    event = get_object_or_404(Event, slug=event_slug)
    dropin_block_configs = list(DropInBlockConfig.objects.filter(active=True))
    dropin_block_configs.sort(key=lambda x: x.event_type==event.event_type, reverse=True)
    target_configs = [config for config in dropin_block_configs if config.event_type == event.event_type]
    course_block_configs = CourseBlockConfig.objects.filter(active=True)

    context = {
        "available_blocks": {
            "Drop-in Blocks": dropin_block_configs,
            "Course Blocks": course_block_configs
        },
        "user_active_blocks": active_user_managed_blocks(request.user, order_by_fields=("expiry_date", "purchase_date")),
        "related_item": event,
        "target_configs": target_configs
    }

    return render(request, "booking/block_purchase.html", context)


@data_privacy_required
@login_required
def course_block_purchase_view(request, course_slug):
    course = get_object_or_404(Course, slug=course_slug)
    course_block_configs = list(CourseBlockConfig.objects.filter(active=True))
    course_block_configs.sort(key=lambda x: x.course_type==course.course_type, reverse=True)
    dropin_block_configs = DropInBlockConfig.objects.filter(active=True)
    target_configs = [config for config in course_block_configs if config.course_type == course.course_type]

    context = {
        "available_blocks": {
            "Course Blocks": course_block_configs,
            "Drop-in Blocks": dropin_block_configs,
        },
        "user_active_blocks": active_user_managed_blocks(request.user, order_by_fields=("expiry_date", "purchase_date")),
        "related_item": course,
        "target_configs": target_configs
    }

    return render(request, "booking/block_purchase.html", context)


@data_privacy_required
@login_required
def block_purchase_view(request):
    dropin_block_configs = DropInBlockConfig.objects.filter(active=True)
    course_block_configs = CourseBlockConfig.objects.filter(active=True)
    context = {
        "available_blocks": {
            "Drop-in Blocks": dropin_block_configs,
            "Course Blocks": course_block_configs
        },
        "user_active_blocks": active_user_managed_blocks(request.user, order_by_fields=("purchase_date",)),
    }
    return render(request, "booking/block_purchase.html", context)
