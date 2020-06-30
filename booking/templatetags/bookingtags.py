from django import template

from ..models import Block

register = template.Library()

@register.filter
def has_available_block(user, event):
    if event.course:
        return any(
            True for block in
            Block.objects.select_related("user", "course_block_config").filter(
                user=user, course_block_config__course_type=event.course.course_type
            )
            if block.active_block()
        )
    else:
        return any(
            True for block in
            Block.objects.select_related("user", "dropin_block_config").filter(
                user=user, dropin_block_config__event_type=event.event_type
            )
            if block.active_block()
        )
