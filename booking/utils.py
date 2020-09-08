from datetime import timedelta
from django.contrib.auth.models import User
from django.utils import timezone

from common.utils import full_name


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
    return any(True for block in user.blocks.all() if block.valid_for_course(course))


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


def get_active_user_course_block(user, course):
    blocks = user.blocks.filter(
        block_config__course=True, block_config__event_type=course.event_type
    ).order_by("expiry_date", "purchase_date")
    valid_blocks = (block for block in blocks if block.valid_for_course(course))
    # already sorted by expiry date, so we can just get the next valid one
    # UNLESS the course has started and allows part booking - then we want to make sure we return a valid part
    # block before a full block
    if course.has_started and course.allow_partial_booking:
        valid_blocks = sorted(list(valid_blocks), key=lambda block: block.block_config.size < course.number_of_events)
        return valid_blocks[0] if valid_blocks else None
    return next(valid_blocks, None)


def get_block_status(block):
    blocks_used = block.bookings.count()
    total_blocks = block.block_config.size
    return blocks_used, total_blocks


def iter_available_subscriptions(user, event):
    for subscription in user.subscriptions.filter(
            paid=True, config__bookable_event_types__has_key=str(event.event_type.id)
            ).order_by("expiry_date", "start_date", "purchase_date"):
        if subscription.valid_for_event(event):
            yield subscription


def has_available_subscription(user, event):
    return any(iter_available_subscriptions(user, event))


def get_available_user_subscription(user, event):
    """
    return the available subscription for this booking with the soonest expiry date
    Expiry dates can be None if the subscriptions hasn't started yet, order by purchase date as well
    """
    return next(iter_available_subscriptions(user, event), None)


def calculate_user_cart_total(unpaid_blocks=None, unpaid_subscriptions=None):
    block_cost = 0
    subscription_cost = 0
    def _block_cost(unpaid_block):
        if unpaid_block.voucher:
            return unpaid_block.cost_with_voucher
        else:
            return unpaid_block.block_config.cost

    if unpaid_blocks:
        block_cost = sum(_block_cost(block) for block in unpaid_blocks)
    if unpaid_subscriptions:
        subscription_cost = sum(subscription.cost_as_of_today() for subscription in unpaid_subscriptions)
    return block_cost + subscription_cost


def booking_restricted_pre_event_start(event):
    return event.event_type.booking_restriction > 0 and (
        event.start - timedelta(minutes=event.event_type.booking_restriction) < timezone.now()
    )


def user_can_book_or_cancel(event=None, user_booking=None, booking_restricted=None):
    if booking_restricted is None:
        booking_restricted = booking_restricted_pre_event_start(event)
    if event is None:
        event = user_booking.event

    if event.cancelled:
        return False
    elif event.has_space and not booking_restricted:
        return True
    elif user_booking and user_booking.status == "OPEN" and not user_booking.no_show:
        # user has open booking, can always cancel, even if within booking retriction period
        return True
    elif event.course and user_booking is not None:
        # user has cancelled or no-show booking, but it's a course event
        return True
    else:
        # user hasn't booked, or has a cancelled or no-show booking - can cancel dependent on booking restrictions
        return not booking_restricted


def user_subscription_info(subscription, event=None, include_user=True):
    if subscription:
        if include_user:
            user_name_text = f"{full_name(subscription.user)}: "
        else:
            user_name_text = ""
        base_text = f"<span class='helptext'>{user_name_text}{subscription.config.name.title()}"
        allowed_use_text = ""
        if event:
            allowed_use = subscription.config.bookable_event_types.get(str(event.event_type.id))
            if allowed_use and allowed_use.get('allowed_number'):
                allowed_use_text = f"; Usage limits: {allowed_use['allowed_number']} per {allowed_use['allowed_unit']}"
        base_text += allowed_use_text
        if subscription.expiry_date:
            return f"{base_text}; expires {subscription.expiry_date.strftime('%d-%b-%y')}</span>"
        return f"{base_text}; not started</span>"


def show_warning(event, user_booking, has_available_payment_method=None):
    """Should we show the warning on booking/rebooking/cancelling?"""
    if event.course:
        # always show for course events with open bookings - credit never given
        if user_booking and user_booking.status == "OPEN" and not user_booking.no_show:
            return True
        return False

    if user_booking:
        if user_booking.subscription and not user_booking.subscription.config.include_no_shows_in_usage:
            # never show for existing bookings (any status) for subscriptions that don't care about no-shows
            return False
        if user_booking.status == "OPEN" and not user_booking.no_show:
            has_available_payment_method = True
        else:
            # cancelled bookings, check if there is an available payment method
            # If we didn't pass it in, find whether a payment method is available
            if has_available_payment_method is None:
                has_available_payment_method = any(
                    [has_available_block(user_booking.user, event),
                     has_available_subscription(user_booking.user, event)]
                )

    if not has_available_payment_method:
        # we'll be showing the payment options button
        return False

    if not event.event_type.allow_booking_cancellation:
        # events that never allow full cancellation
        return True
    # check cancellation period against current time
    return not event.can_cancel


def get_user_booking_info(user, event):
    if event.course:
        # bookings for course events are only counted if they're not fully cancelled.  We don't show rebook buttons
        # for fully cancelled course bookings, only for no-show ones
        user_booking = user.bookings.filter(event=event, status="OPEN").first()
    else:
        user_booking = user.bookings.filter(event=event).first()
    available_subscription = get_available_user_subscription(user, event)
    available_subscription_info = user_subscription_info(available_subscription, event, include_user=False)
    available_block = get_active_user_block(user, event)
    booking_restricted = booking_restricted_pre_event_start(event)

    info = {
        "has_available_block": available_block is not None,
        "has_available_subscription": available_subscription is not None,
        "has_booked": user_booking is not None,
        "on_waiting_list": user.waitinglists.filter(event=event).exists(),
        "booking_restricted_pre_event_start": booking_restricted,
        "can_book_or_cancel": user_can_book_or_cancel(event, user_booking=user_booking, booking_restricted=booking_restricted),
        "available_block": get_active_user_block(user, event),
        "available_subscription": available_subscription,
        "available_subscription_info": available_subscription_info,
        "show_warning": show_warning(
            event, user_booking, available_block is not None or available_subscription is not None
        )
    }
    if event.course:
        info.update({"has_available_course_block": has_available_course_block(user, event.course)})
    if user_booking:
        if available_subscription == user_booking.subscription:
            booking_subscription_info = available_subscription_info
        else:
            booking_subscription_info = user_subscription_info(user_booking.subscription, event, include_user=False)
        info.update({
            "open": user_booking.status == "OPEN" and not user_booking.no_show,
            "cancelled": user_booking.status == "CANCELLED" or user_booking.no_show,
            "used_block": user_booking.block,
            "used_subscription": user_booking.subscription,
            "used_subscription_info": booking_subscription_info,
        })
    return info


def get_user_course_booking_info(user, course):
    has_booked = user.bookings.filter(event__course=course, status="OPEN").exists()
    available_block = get_active_user_course_block(user, course)

    info = {
        "hide_block_info_divider": True,
        "has_available_block": available_block is not None,
        "has_booked": has_booked,
        "open": has_booked,  # for block info
        "available_block": available_block,
    }
    if has_booked:
        iter_used_blocks = (
            booking.block for booking in user.bookings.filter(event__course=course) if booking.block is not None
        )
        info.update({"used_block": next(iter_used_blocks) if any(iter_used_blocks) else None})
    return info
