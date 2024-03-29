from decimal import Decimal
from django.contrib.auth.models import User


from booking.models import get_active_user_block, get_active_user_course_block, \
    get_available_user_subscription, has_available_subscription, has_available_block, \
    has_available_course_block


from common.utils import full_name
from studioadmin.views.user_views import users_with_unused_blocks


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


def get_block_status(block):
    blocks_used = block.bookings.count()
    total_blocks = block.block_config.size
    return blocks_used, total_blocks


def calculate_user_cart_total(
        unpaid_blocks=None,
        unpaid_subscriptions=None,
        unpaid_gift_vouchers=None,
        unpaid_merchandise=None,
        total_voucher=None
):
    block_cost = 0
    subscription_cost = 0
    gift_voucher_cost = 0
    merchandise_cost = 0

    def _block_cost(unpaid_block):
        if unpaid_block.voucher:
            return unpaid_block.cost_with_voucher
        else:
            return unpaid_block.block_config.cost

    if unpaid_blocks:
        block_cost = sum(_block_cost(block) for block in unpaid_blocks)
    if unpaid_subscriptions:
        subscription_cost = sum(subscription.cost_as_of_today() for subscription in unpaid_subscriptions)
    if unpaid_gift_vouchers:
        gift_voucher_cost = sum(gift_voucher.gift_voucher_config.cost for gift_voucher in unpaid_gift_vouchers)
    if unpaid_merchandise:
        merchandise_cost = sum(product_purchase.cost for product_purchase in unpaid_merchandise)

    cart_total = block_cost + subscription_cost + gift_voucher_cost + merchandise_cost
    if total_voucher:
        if total_voucher.discount:
            percentage_to_pay = Decimal((100 - total_voucher.discount) / 100)
            return (cart_total * percentage_to_pay).quantize(Decimal('.01'))
        else:

            if total_voucher.discount_amount > cart_total:
                cart_total = 0
            else:
                cart_total -= Decimal(total_voucher.discount_amount)
    return cart_total


def user_booking_status(user_booking):
    if user_booking:
        if user_booking.status == "CANCELLED":
            return "cancelled"
        elif user_booking.no_show:
            return "no_show"
        else:
            return "open"


def can_book(user_booking, event, booking_restricted=None):
    status = user_booking_status(user_booking)
    if status == "open":
        # already open
        return False
    else:
        # all other statuses (incl None) depend on the event status
        return event.is_bookable(booking_restricted)


def can_cancel(user_booking):
    status = user_booking_status(user_booking)
    if status == "open":
        # already open, can always cancel
        return True
    return False


def can_rebook(user_booking, event):
    status = user_booking_status(user_booking)
    # only no-show course bookings are show as rebook
    # no-shows on courses are cancellations from full course bookings; they keep their
    # course places, so continue to count towards the spaces
    return status == "no_show" and event.course


def _can_action_waiting_list(user, event, user_booking, action):
    # ignore waiting list for course events that don't allow drop-in
    # if event.course and not event.course.allow_drop_in:
    #     return False
    on_waiting_list = user.waitinglists.filter(event=event).exists()
    status = user_booking_status(user_booking)

    if event.full and status != "open":
        return on_waiting_list if action == "leave" else not on_waiting_list
    return False


def can_join_waiting_list(user, event, user_booking):
    return _can_action_waiting_list(user, event, user_booking, "join")


def can_leave_waiting_list(user, event, user_booking):
    return _can_action_waiting_list(user, event, user_booking, "leave")


def user_can_book_or_cancel(event=None, user_booking=None, booking_restricted=None):
    booking_restricted = booking_restricted or event.booking_restricted_pre_start()
    return any(
        [
            can_book(user_booking, event, booking_restricted),
            can_rebook(user_booking, event),
            can_cancel(user_booking)
        ]
    ) and not booking_restricted


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
    if event.course and not event.course.allow_drop_in:
        # for course events that don't allow drop in
        # always show if cacnelling an open bookings - credit never given
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

    if not event.event_type.allow_booking_cancellation:
        # events that never allow full cancellation
        return True
    # check cancellation period against current time
    return not event.can_cancel


def get_user_booking_info(user, event):
    # display options for non-course event
    """
    Book - class not full, currently cancelled booking, has available block
    Rebook - class not full, currently cancelled booking, has available block
    Cancel - currently open booking
    Payment options- class not full, no available block
    Join waiting list - class full, not on waiting list
    Leave waiting list - class full, on waiting list
    """
    if event.course and not event.course.allow_drop_in:
        # Events for a full course booking (i.e. one booked with a course block) are never
        # fully cancelled, only set to no-show.  If they are fully cancelled, it's because
        # an admin has updated it, for the whole course, so we don't show rebook buttons.
        # The exception is when a course allows drop-in; then we can allow users with
        # fully cancelled bookings to rebook single classes.
        user_booking = user.bookings.filter(event=event, status="OPEN").first()
    else:
        user_booking = user.bookings.filter(event=event).first()

    return {
        "show_warning": show_warning(event, user_booking),
        "on_waiting_list": can_leave_waiting_list(user, event, user_booking)
    }


def user_course_booking_type(user, course, bookings=None):
    # check this against PAID bookings only
    # if there are no paid bookings, check for bookings with no block - these are single
    # bookings added by admins, so are considered dropin
    if bookings is None:
        bookings = user.bookings.filter(event__course=course, status="OPEN", block__paid=True)
    if bookings:
        booking = bookings.first()
        if booking.block and booking.block.block_config.course:
            return "course"
        else:
            return "dropin"
    else:
        # no paid bookings, check for bookings without block, we consider these dropin also
        if user.bookings.filter(event__course=course, status="OPEN", block__isnull=True).exists():
            return "dropin"



def get_user_course_booking_info(user, course):
    bookings = user.bookings.filter(event__course=course, status="OPEN")
    # booking type for PAID bookings only
    booking_type = user_course_booking_type(user, course)
    has_booked = booking_type == "course"
    # open booked events includes unpaid, in-basket
    open_booked_events = bookings.filter(no_show=False).values_list("event_id", flat=True)
    booked_events = bookings.values_list("event_id", flat=True)
    in_basket_event_ids = [booking.event.id for booking in bookings if booking.is_in_basket()]
    items_in_basket = bool(in_basket_event_ids)

    info = {
        "has_booked_course": has_booked,
        "has_booked_dropin": booking_type == "dropin",
        "has_booked_all": booked_events.count() == course.uncancelled_events.count(),
        "items_in_basket": items_in_basket,
        "in_basket_event_ids": in_basket_event_ids,
        "booked_event_ids": open_booked_events,
    }
    if has_booked:
        iter_used_blocks = (
            booking.block for booking in user.bookings.filter(event__course=course) if booking.block is not None
        )
        info.update({"used_block": next(iter_used_blocks, None)})
    return info
