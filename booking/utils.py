from django.contrib.auth.models import User


def get_view_as_user(request):
    # use the user set on the session if there is one
    user_id_from_session = request.session.get("user_id")
    if not user_id_from_session:
        if not request.user.is_student and \
                request.user.is_manager and \
                request.user.managed_users:
            # not a student, is a manager, and has at least one managed account
            view_as_user = request.user.managed_users[0]
        else:
            # anything else
            view_as_user = request.user
    else:
        view_as_user = User.objects.get(id=user_id_from_session)
    request.session["user_id"] = view_as_user.id
    return view_as_user


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


def calculate_user_cart_total(unpaid_blocks=None):
    def _cost(unpaid_block):
        if unpaid_block.voucher:
            return unpaid_block.cost_with_voucher
        else:
            return unpaid_block.block_config.cost
    return sum(_cost(block) for block in unpaid_blocks)