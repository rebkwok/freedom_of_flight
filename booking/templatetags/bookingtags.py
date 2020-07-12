from django import template

from ..models import WaitingListUser
from ..utils import has_available_block as has_available_block_util
from ..utils import has_available_course_block as has_available_course_block_util
from ..utils import get_active_user_block, get_block_status

register = template.Library()

@register.filter
def has_available_block(user, event):
    return has_available_block_util(user, event)


@register.filter
def has_available_course_block(user, course):
    return has_available_course_block_util(user, course)


@register.filter
def block_used(user, event):
    block = get_active_user_block(user, event)
    if event.course:
        # Don't show the used/total for course blocks
        if user.bookings.filter(event=event, status="OPEN", no_show=False).exists():
            return f"Block used"
        return f"Block available"

    if user.bookings.filter(event=event, status="OPEN", no_show=False).exists():
        return f"Block used"
    return f"Block available"


def get_block_info(block):
    used, total = get_block_status(block)
    base_text = f"<span class='helptext'>{block.user.first_name} {block.user.last_name}: {block.block_config.identifier} ({total - used}/{total} remaining)"
    if block.expiry_date:
        return f"{base_text}; expires {block.expiry_date.strftime('%d %b %y')}</span>"
    elif block.block_config.duration:
        return f"{base_text}; not started</span>"
    else:
        return f"{base_text}; never expires</span>"

@register.filter
def block_info(user, event):
    block = get_active_user_block(user, event)
    if event.course:
        # Don't show the used/total for course blocks
        return f"<span class='helptext'>{block.block_config.identifier} </span>"
    return get_block_info(block)


@register.filter
def user_block_info(block):
    if block.course_block_config:
        # Don't show the used/total for course blocks
        return f"<span class='helptext'>{block.user.first_name} {block.user.last_name}: {block.block_config.identifier}</span>"
    return get_block_info(block)

@register.filter
def has_unpaid_block(user, block_config):
    return any(block for block in user.blocks.filter(paid=False) if block.block_config == block_config)


@register.inclusion_tag('booking/includes/active_blocks_for_block_config.html')
def active_block_info(user_active_blocks, block_config):
    available_active_blocks = [block for block in user_active_blocks if block.block_config == block_config]
    block_info_texts = [user_block_info(block) for block in available_active_blocks]
    return {"block_info_texts": block_info_texts}


@register.filter
def on_waiting_list(user, event):
    return WaitingListUser.objects.filter(user=user, event=event).exists()


@register.filter
def block_expiry_text(block):
    if block.expiry_date:
        return f"Expires {block.expiry_date.strftime('%d %b %y')}"
    elif block.block_config.duration:
        # Don't show the used/total for course blocks
        return "Not started yet"
    else:
        return "Never expires"


@register.filter
def can_book_or_cancel(user, event):
    if event.cancelled:
        return False
    elif event.has_space:
        return True
    elif user.bookings.filter(event=event, status="OPEN", no_show=False):
        # user has open booking
        return True
    elif event.course and user.bookings.filter(event=event):
        # user has cancelled or no-show booking, but it's a course event
        return True
    else:
        return False


@register.filter
def has_open_or_cancelled_booking(user, event):
    return user.bookings.filter(event=event).exists()


@register.filter
def has_course_booking(user, event):
    return user.bookings.filter(event=event).exists()
