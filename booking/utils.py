
from django.utils import timezone

from .models import Block


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

def get_active_user_block(user, event):
    """
    return the active block for this booking with the soonest expiry date
    """
    if event.course:
        blocks = user.blocks.filter(
            expiry_date__gte=timezone.now(), course_block_config__course_type=event.course.course_type
        ).order_by("expiry_date")
    else:
        blocks = user.blocks.filter(
            expiry_date__gte=timezone.now(), dropin_block_config__event_type=event.event_type
        ).order_by("expiry_date")
    # already sorted by expiry date, so we can just get the next active one
    next_active_block = next((block for block in blocks if block.active_block()), None)
    # use the block with the soonest expiry date
    return next_active_block


def get_block_status(booking, request):
    blocks_used = booking.block.bookings_made()
    total_blocks = booking.block.block_type.size
    ActivityLog.objects.create(
        log='Block used for booking id {} (for {}). Block id {}, '
        'by user {}'.format(
            booking.id, booking.event, booking.block.id,
            request.user.username
        )
    )

    return blocks_used, total_blocks