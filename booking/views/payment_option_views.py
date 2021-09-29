import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.utils import timezone


from common.utils import start_of_day_in_utc
from ..models import Block, BlockConfig, Course, Event, Subscription, SubscriptionConfig
from .views_utils import data_privacy_required


logger = logging.getLogger(__name__)


def active_user_managed_blocks(core_user, order_by_fields=("purchase_date",)):
    return [block for block in Block.objects.filter(user__in=core_user.managed_users).order_by(*order_by_fields) if block.active_block]


def active_user_managed_subscriptions(core_user, order_by_fields=("purchase_date",)):
    return [
        subscription for subscription in Subscription.objects.filter(user__in=core_user.managed_users).order_by(*order_by_fields)
        if subscription.paid and not subscription.has_expired()
    ]


@data_privacy_required
def event_purchase_view(request, event_slug):
    event = get_object_or_404(Event, slug=event_slug)
    context = block_config_context(request, event=event)
    context.update(subscription_config_context(request, event.event_type))
    context["related_item"] = event
    return render(request, "booking/purchase_options.html", context)


@data_privacy_required
def course_purchase_view(request, course_slug):
    course = get_object_or_404(Course, slug=course_slug)
    context = block_config_context(request, course=course)
    context.update(subscription_config_context(request))
    context["related_item"] = course
    return render(request, "booking/purchase_options.html", context)


@data_privacy_required
def purchase_view(request):
    context = {**block_config_context(request), **subscription_config_context(request)}
    return render(request, "booking/purchase_options.html", context)


def block_config_context(request, course=None, event=None):
    context = {}
    dropin_block_configs = None
    course_block_configs = None
    if course is not None:
        course_block_configs = BlockConfig.objects.filter(
            active=True, course=True, event_type=course.event_type, size=course.number_of_events
        )
    elif event is not None:
        dropin_block_configs = BlockConfig.objects.filter(
            active=True, course=False, event_type=event.event_type
        )
    else:
        dropin_block_configs = BlockConfig.objects.filter(active=True, course=False).order_by(
            "event_type__track", "event_type__name"
        )
        course_block_configs = BlockConfig.objects.filter(active=True, course=True).order_by(
            "event_type__track", "event_type__name"
        )

    available_blocks_with_labels = {
        "Drop-in Credit Blocks": dropin_block_configs,
        "Course Credit Blocks": course_block_configs
    }
    course_config_order = ["Course Credit Blocks", "Drop-in Credit Blocks"]
    if course is not None:
        available_blocks = {
            label: available_blocks_with_labels[label] for label in course_config_order if available_blocks_with_labels[label]
        }
    else:
        available_blocks = {
            label: configs for label, configs in available_blocks_with_labels.items() if configs
        }
    if request.user.is_authenticated:
        context.update({"user_active_blocks": active_user_managed_blocks(request.user, order_by_fields=("expiry_date", "purchase_date",))})
    context.update({"available_blocks": available_blocks})
    return context


def allowed_start_dates(subscription_config):
    if subscription_config.start_options == "start_date":
        current = subscription_config.get_subscription_period_start_date()
        next = subscription_config.get_subscription_period_start_date(next=True)
        if next:
            # check we're allowed to purchase it now
            if not subscription_config.advance_purchase_allowed and (next - start_of_day_in_utc(timezone.now())).days > 3:
                next = None
        return {"current": current, "next": next}


def subscription_config_context(request, event_type=None):
    context = {}
    subscription_configs = [
        config for config in SubscriptionConfig.objects.filter(active=True) if config.is_purchaseable()
    ]
    if event_type is not None:
        subscription_configs = [
            subscription_config for subscription_config in subscription_configs if
            event_type.id in subscription_config.bookable_event_types
        ]

    def _start_options_for_users(config):
        if request.user.is_authenticated:
            return {
                managed_user.id: config.get_start_options_for_user(managed_user, ignore_unpaid=True)
                for managed_user in request.user.managed_users
            }
        return {}

    subscription_config_info = [
        {
            "config": config,
            "start_options": allowed_start_dates(config),
            "start_options_for_users": _start_options_for_users(config),
            "current_period_cost": config.calculate_current_period_cost_as_of_today()
        } for config in subscription_configs
    ]

    if request.user.is_authenticated:
        context.update({"user_active_subscriptions": active_user_managed_subscriptions(request.user, order_by_fields=("purchase_date",))})
    context.update({"subscription_configs": subscription_config_info})

    return context
