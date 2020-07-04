import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from django.http import JsonResponse
from django.shortcuts import HttpResponseRedirect, render, get_object_or_404
from django.views.generic import ListView, CreateView, DeleteView
from django.core.mail import send_mail
from django.template.loader import get_template
from django.views.decorators.http import require_http_methods


from booking.models import (
    Block, DropInBlockConfig, Course, CourseType, Event, EventType, CourseBlockConfig
)
from .views_utils import data_privacy_required, disclaimer_required


from activitylog.models import ActivityLog

logger = logging.getLogger(__name__)


def active_user_blocks(user):
    return [block for block in user.blocks.all() if block.active_block]


@disclaimer_required
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
        "user_active_blocks": active_user_blocks(request.user),
        "related_item": event,
        "target_configs": target_configs
    }

    return render(request, "booking/block_purchase.html", context)


@disclaimer_required
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
        "user_active_blocks": active_user_blocks(request.user),
        "related_item": course,
        "target_configs": target_configs
    }

    return render(request, "booking/block_purchase.html", context)


@disclaimer_required
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
        "user_active_blocks": active_user_blocks(request.user),
    }
    return render(request, "booking/block_purchase.html", context)


@login_required
@require_http_methods(['POST'])
def ajax_dropin_block_purchase(request, block_config_id):
    block_config = get_object_or_404(DropInBlockConfig, pk=block_config_id)
    block, new = Block.objects.get_or_create(user=request.user, dropin_block_config=block_config, paid=False)
    return process_block_purchase(request, block, new, block_config)


@login_required
@require_http_methods(['POST'])
def ajax_course_block_purchase(request, block_config_id):
    course_config = get_object_or_404(CourseBlockConfig, pk=block_config_id)
    block, new = Block.objects.get_or_create(user=request.user, course_block_config=course_config, paid=False)
    return process_block_purchase(request, block, new, course_config)


def process_block_purchase(request, block, new, block_config):
    if not new:
        block.delete()
        alert_message = {
            "message_type": "info",
            "message": f"Block removed from cart"
        }
    else:
        alert_message = {
            "message_type": "success",
            "message": f"Block added to cart"
        }
    context = {
        "available_block_config": block_config,
        "alert_message": alert_message
    }
    html =  render(request, f"booking/includes/blocks_button.txt", context)
    return JsonResponse(
        {
            "html": html.content.decode("utf-8"),
            "cart_item_menu_count": request.user.blocks.filter(paid=False).count(),
        }
    )