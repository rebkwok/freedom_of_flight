from django import template

from ..models import Block

register = template.Library()

@register.filter
def has_available_block(user, event):
    if event.course:
        return any(
            True for block in
            Block.objects.select_related("user", "block_type").filter(user=user, block_type__course_type=event.course.course_type)
            if block.active_block()
        )
    else:
        return any(
            True for block in
            Block.objects.select_related("user", "block_type").filter(user=user, block_type__course_type__isnull=True, block_type__event_type=event.event_type)
            if block.active_block()
        )
