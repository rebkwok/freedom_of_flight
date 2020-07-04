
def has_available_block(user, event):
    if event.course:
        return any(
            True for block in
            user.blocks.filter(course_block_config__course_type=event.course.course_type)
            if block.valid_for_course(event.course)
        )
    else:
        return any(
            True for block in
            user.blocks.filter(dropin_block_config__event_type=event.event_type)
            if block.valid_for_event(event)
        )

def has_available_course_block(user, course):
    return has_available_block(user, course.events.order_by("start").first())

def get_active_user_block(user, event):
    """
    return the active block for this booking with the soonest expiry date
    Expiry dates can be None if the block hasn't started yet, order by purchase date as well
    """
    if event.course:
        blocks = user.blocks.filter(
            course_block_config__course_type=event.course.course_type
        ).order_by("expiry_date", "purchase_date")
        # already sorted by expiry date, so we can just get the next valid one
        return next((block for block in blocks if block.valid_for_course(event.course)), None)
    else:
        blocks = user.blocks.filter(
            dropin_block_config__event_type=event.event_type
        ).order_by("expiry_date", "purchase_date")
        return next((block for block in blocks if block.valid_for_event(event)), None)


def get_block_status(block):
    blocks_used = block.bookings_made()
    total_blocks = block.block_config.size
    return blocks_used, total_blocks
