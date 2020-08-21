from django.template.loader import render_to_string
from django import template
from django.db.models import Q
from django.utils import timezone
from common.utils import full_name, start_of_day_in_utc
from ..models import EventType, WaitingListUser
from ..utils import has_available_block as has_available_block_util
from ..utils import has_available_course_block as has_available_course_block_util
from ..utils import get_block_status, user_can_book_or_cancel
from ..utils import get_user_booking_info

register = template.Library()

@register.filter
def has_available_block(user, event):
    return has_available_block_util(user, event)


@register.filter
def has_available_course_block(user, course):
    return has_available_course_block_util(user, course)


def get_block_info(block):
    used, total = get_block_status(block)
    base_text = f"<span class='helptext'>{block.user.first_name} {block.user.last_name}: {block.block_config.name} ({total - used}/{total} remaining)"
    if block.expiry_date:
        return f"{base_text}; expires {block.expiry_date.strftime('%d-%b-%y')}</span>"
    elif block.block_config.duration:
        return f"{base_text}; not started</span>"
    else:
        return f"{base_text}; never expires</span>"


@register.filter
def user_block_info(block):
    if block.block_config.course:
        # Don't show the used/total for course blocks
        return f"<span class='helptext'>{block.user.first_name} {block.user.last_name}: {block.block_config.name}</span>"
    return get_block_info(block)


@register.filter
def user_subscription_info(subscription):
    base_text = f"<span class='helptext'>{full_name(subscription.user)}: {subscription.config.name}"
    if subscription.expiry_date:
        return f"{base_text}; expires {subscription.expiry_date.strftime('%d-%b-%y')}</span>"
    return f"{base_text}; not started</span>"


@register.filter
def has_unpaid_block(user, block_config):
    return any(block for block in user.blocks.filter(paid=False) if block.block_config == block_config)


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
    return False


@register.filter
def block_expiry_text(block):
    if block.expiry_date:
        return f"Expires {block.expiry_date.strftime('%d-%b-%y')}"
    elif block.block_config.duration:
        # Don't show the used/total for course blocks
        return "Not started yet"
    else:
        return "Never expires"


@register.filter
def subscription_expiry_text(subscription):
    if subscription.expiry_date:
        return f"Expires {subscription.expiry_date.strftime('%d-%b-%y')}"
    else:
        return "Not started yet"


@register.filter
def can_book_or_cancel(user, event):
    return user_can_book_or_cancel(user, event)


@register.filter
def lookup_dict(dictionary, key):
    if dictionary:
        return dictionary.get(key)

@register.simple_tag
def booking_user_info(booking):
    return get_user_booking_info(booking.user, booking.event)


@register.filter
def subscription_start_options(subscription_user, subscription_config):
    return subscription_config.get_start_options_for_user(subscription_user, ignore_unpaid=True)


@register.filter
def format_subscription_config_start_options(subscription_config_dict):
    if subscription_config_dict["config"].start_options == "signup_date":
        return "Starts from date of purchase"
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
        EventType.objects.get(id=key).name.title(): f"{value['allowed_number']} per {value['allowed_unit']}" if value["allowed_number"] else "unlimited"
        for key, value in bookable_event_types.items()
    }
    return {"bookable_event_types": formatted_bookable_event_types}
