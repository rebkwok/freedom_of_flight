from django import template
from django.db.models import Q, Count
from django.utils import timezone
from common.utils import full_name, start_of_day_in_utc
from ..models import EventType, WaitingListUser

from ..utils import (
    get_block_status, user_subscription_info,
    show_warning
)

register = template.Library()


def get_block_info(block):
    used, total = get_block_status(block)
    base_text = f"<span class='helptext'>{full_name(block.user)}: {block.block_config.name} ({total - used}/{total} remaining)"
    if block.expiry_date:
        return f"{base_text}; expires {block.expiry_date.strftime('%d-%b-%y')}</span>"
    elif block.block_config.duration:
        return f"{base_text}; not started</span>"
    else:
        return f"{base_text}; never expires</span>"


def user_block_info(block):
    if block.block_config.course:
        # Don't show the used/total for course blocks
        return f"<span class='helptext'>{full_name(block.user)}: {block.block_config.name}</span>"
    return get_block_info(block)


@register.filter
def unpaid_block_count(user, block_config):
    # unpaid block count for blocks with no associated bookings
    return user.blocks.filter(block_config=block_config, paid=False).annotate(count=Count("bookings__id")).exclude(count__gt=0).count()


@register.simple_tag
def has_unpaid_subscription(user, subscription_config, start_date):
    if subscription_config.start_options == "signup_date" and start_date == start_of_day_in_utc(timezone.now()):
        return user.subscriptions.filter(
            Q(paid=False, config=subscription_config) & (Q(start_date__lte=start_date) | Q(start_date__isnull=True))
        ).exists()
    return user.subscriptions.filter(paid=False, start_date=start_date, config=subscription_config).exists()


@register.inclusion_tag('booking/includes/active_blocks_for_block_config.html')
def active_block_info(user_active_blocks, block_config):
    available_active_blocks = [block for block in user_active_blocks if block.block_config == block_config]
    block_info_texts = [user_block_info(block) for block in available_active_blocks]
    return {"block_info_texts": block_info_texts}


@register.inclusion_tag('booking/includes/active_subscriptions_for_subscription_config.html')
def active_subscription_info(user_active_subscriptions, subscription_config):
    available_active_subscriptions = [subscription for subscription in user_active_subscriptions if subscription.config == subscription_config]
    subscription_info_texts = [user_subscription_info(subscription) for subscription in available_active_subscriptions]
    return {"subscription_info_texts": subscription_info_texts}


@register.filter
def on_waiting_list(user, event):
    if user.is_authenticated:
        return WaitingListUser.objects.filter(user=user, event=event).exists()


@register.filter
def block_expiry_text(block):
    if block.expiry_date:
        return f"{block.expiry_date.strftime('%d-%b-%y')}"
    elif block.block_config.duration:
        # Don't show the used/total for course blocks
        return f"not started yet (expires {block.block_config.duration} weeks after date of first booking)"
    else:
        return "never"


@register.filter
def subscription_expiry_text(subscription):
    if subscription.expiry_date:
        return f"Expires {subscription.expiry_date.strftime('%d-%b-%y')}"
    else:
        return "Not started yet"


@register.filter
def subscription_start_text(subscription):
    if subscription.start_date:
        return f"Starts {subscription.start_date.strftime('%d-%b-%y')}"
    elif subscription.config.start_options == "first_booking_date":
        return "Starts on date of first booked class/event"


@register.filter
def show_booking_warning(booking):
    return show_warning(event=booking.event, user_booking=booking)


@register.filter
def lookup_dict(dictionary, key):
    if dictionary:
        return dictionary.get(key)


@register.filter
def format_subscription_config_start_options(subscription_config_dict):
    if subscription_config_dict["config"].start_options == "signup_date":
        return "Starts from date of purchase (or previous subscription expiry)"
    elif subscription_config_dict["config"].start_options == "first_booking_date":
        return "Starts from date of first use"
    else:
        current = subscription_config_dict["start_options"]["current"]
        next = subscription_config_dict["start_options"]["next"]
        if current and next:
            return f"<span class='mt-0 pt-0'>Start options:</span><ul class='mt-0 pt-0'><li>{current.strftime('%d-%b-%y')} (current period)</li><li>{next.strftime('%d-%b-%y')} (next period)</li></ul>"
        elif current:
            return f"Starts on {current.strftime('%d-%b-%y')}"
        elif next:
            return f"Starts on {next.strftime('%d-%b-%y')}"
        else:
            return ""


@register.inclusion_tag('booking/includes/bookable_event_types.html')
def format_bookable_event_types(subscription_config):
    bookable_event_types = subscription_config.bookable_event_types or {}
    formatted_bookable_event_types = {
        EventType.objects.get(id=key): f"{value['allowed_number']} per {value['allowed_unit']}" if value["allowed_number"] else "unlimited"
        for key, value in bookable_event_types.items()
    }
    return {"bookable_event_types": formatted_bookable_event_types}


@register.filter
def can_purchase_block(user, block_config):
    return block_config.available_to_user(user)


@register.filter
def can_purchase_subscription(user, subscription_config):
    return subscription_config.available_to_user(user)


@register.filter
def at_least_one_user_can_purchase(available_users, block_or_subscription):
    return any(user for user in available_users if block_or_subscription.available_to_user(user))


@register.filter
def get_range(value, start=0):
    # start: 0 or 1
    return range(start, value + start)
