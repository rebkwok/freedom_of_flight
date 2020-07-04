from django import template

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

@register.filter
def block_info(user, event):
    block = get_active_user_block(user, event)
    if event.course:
        # Don't show the used/total for course blocks
        return f"{block.block_config.identifier}"

    used, total = get_block_status(block)
    if block.expiry_date:
        return f"<span class='helptext'>{block.block_config.identifier} ({total - used}/{total} remaining)" \
                f"</br>Expires {block.expiry_date.strftime('%d %b %y')}</span>"
    return f"<span class='helptext'>{block.block_config.identifier} ({total - used}/{total} remaining)</span>"


@register.filter
def user_block_info(block):
    if block.course_block_config:
        # Don't show the used/total for course blocks
        return f"{block.block_config.identifier}"
    used, total = get_block_status(block)
    if block.expiry_date:
        return f"<span class='helptext'>{block.block_config.identifier} ({total - used}/{total} remaining)" \
               f"</br>Expires {block.expiry_date.strftime('%d %b %y')}</span>"
    return f"<span class='helptext'>{block.block_config.identifier} ({total - used}/{total} remaining)</br>Not started</span>"


@register.filter
def has_unpaid_block(user, block_config):
    return any(block for block in user.blocks.filter(paid=False) if block.block_config == block_config)