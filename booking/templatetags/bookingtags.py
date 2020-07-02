from django import template

from ..utils import has_available_block as has_available_block_util
from ..utils import get_active_user_block, get_block_status

register = template.Library()

@register.filter
def has_available_block(user, event):
    return has_available_block_util(user, event)


@register.filter
def has_available_course_block(user, course):
    return has_available_block_util(user, course.events.first())


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
        if user.bookings.filter(event=event, status="OPEN", no_show=False).exists():
            return f"{block.block_config.identifier}"
        return f"{block.block_config.identifier}"

    used, total = get_block_status(block)
    expiry_text = ""
    if block.expiry_date:
        expiry_text = f"; expires {block.expiry_date.strftime('%d %b %y')}"

    if user.bookings.filter(event=event, status="OPEN", no_show=False).exists():
        return f"{block.block_config.identifier} ({total - used}/{total} remaining){expiry_text}"
    return f"{block.block_config.identifier} ({total - used}/{total} remaining){expiry_text}"