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
        return any(True for block in user.blocks.all() if block.valid_for_course(event.course))
    else:
        return any(True for block in user.blocks.all() if block.valid_for_event(event))


def has_available_course_block(user, course):
    return has_available_block(user, course.events.order_by("start").first())


def get_active_user_block(user, event):
    """
    return the active block for this booking with the soonest expiry date
    Expiry dates can be None if the block hasn't started yet, order by purchase date as well
    """
    if event.course:
        blocks = user.blocks.filter(
            block_config__course=True, block_config__event_type=event.course.event_type
        ).order_by("expiry_date", "purchase_date")
        # already sorted by expiry date, so we can just get the next valid one
        return next((block for block in blocks if block.valid_for_course(event.course)), None)
    else:
        blocks = user.blocks.filter(
            block_config__course=False, block_config__event_type=event.event_type
        ).order_by("expiry_date", "purchase_date")
        return next((block for block in blocks if block.valid_for_event(event)), None)


def get_block_status(block):
    blocks_used = block.bookings.count()
    total_blocks = block.block_config.size
    return blocks_used, total_blocks


def calculate_user_cart_total(unpaid_blocks=None):
    def _cost(unpaid_block):
        if unpaid_block.voucher:
            return unpaid_block.cost_with_voucher
        else:
            return unpaid_block.block_config.cost
    return sum(_cost(block) for block in unpaid_blocks)


def user_can_book_or_cancel(user, event):
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

def get_user_booking_info(user, event):
    user_bookings = user.bookings.filter(event=event)
    info = {
        "has_available_block": has_available_block(user, event),
        "has_booked": user_bookings.exists(),
        "on_waiting_list": user.waitinglists.filter(event=event).exists(),
        "can_book_or_cancel": user_can_book_or_cancel(user, event),
        "available_block": get_active_user_block(user, event)
    }
    if event.course:
        info.update({"has_available_course_block": has_available_course_block(user, event.course)})
    if user_bookings.exists():
        user_booking = user_bookings.first()
        info.update({
            "open": user_booking.status == "OPEN" and not user_booking.no_show,
            "cancelled": user_booking.status == "CANCELLED" or   user_booking.no_show,
            "used_block": user_booking.block,
        })
    return info
