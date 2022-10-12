from datetime import datetime
from datetime import timezone as dt_timezone

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.http import require_http_methods
from django.urls import reverse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils import timezone

from accounts.models import has_active_disclaimer
from activitylog.models import ActivityLog
from booking.views.button_utils import booking_list_button
from booking.views.event_views import button_options_events_list
from merchandise.models import ProductPurchase

from common.utils import full_name, start_of_day_in_utc
from ..models import Booking, Block, Course, Event, WaitingListUser, BlockConfig, Subscription, \
    SubscriptionConfig, GiftVoucher, add_to_cart_course_block_config, add_to_cart_drop_in_block_config, valid_course_block_configs, valid_dropin_block_configs
from ..utils import (
    calculate_user_cart_total, get_user_course_booking_info, has_available_block, has_available_subscription,
    get_active_user_course_block,
    get_user_booking_info, get_available_user_subscription, has_available_course_block,
)
from ..email_helpers import send_waiting_list_email, send_user_and_studio_emails
from .views_utils import total_unpaid_item_count, get_unpaid_user_managed_subscriptions, \
    get_unpaid_user_managed_blocks, get_unpaid_user_gift_vouchers, \
    get_unpaid_user_merchandise, get_unpaid_gift_vouchers_from_session


logger = logging.getLogger(__name__)


REQUESTED_ACTIONS = {
    ("CANCELLED", True): "reopened",
    ("CANCELLED", False): "reopened",
    ("OPEN", True): "reopened",
    ("OPEN", False): "cancelled",
}


def other_same_day_unbooked_events(booking):
    open_booked_event_ids = set(booking.user.bookings.filter(
        event__start__date=booking.event.start.date(), status="OPEN", no_show=False
    ).values_list("event_id", flat=True))
    open_booked_event_ids.add(booking.event.id)
    return Event.objects.filter(
        event_type=booking.event.event_type, start__date=booking.event.start.date(), cancelled=False
    ).filter(start__gte=timezone.now()).exclude(id__in=open_booked_event_ids)


def has_subscription_availability_changed(booking, action, subscription_use_pre_change):
    # we only check this if there's a valid subscription, so subscription_use_pre_change is never None
    subscription_availability_changed = False
    event = booking.event
    usage_limits = booking.subscription.usage_limits(event.event_type)
    if usage_limits:
        allowed_number, allowed_unit = usage_limits
        # we've booked/rebooked and used a subscription and the usage is now at max
        # OR
        # we've cancelled and the usage was previuosly at max
        # check if the subscription use was at max prior to booking
        subscription_use = booking.subscription.usage_for_event_type_and_date(event.event_type, event.start)
        check_usage = False

        if action in ["opened", "reopened"] and subscription_use == allowed_number:
            check_usage = subscription_use_pre_change < allowed_number
        elif action == "cancelled":
            check_usage = subscription_use_pre_change == allowed_number
        if check_usage:
            # We only check the actual uses for same-day limits, for others (weekly/monthly) it's likely there will be
            # other bookable events, so just assume we need to reload
            if allowed_unit == "day":
                other_events = other_same_day_unbooked_events(booking)
                subscription_availability_changed = other_events.exists()
            else:
                subscription_availability_changed = True
    return subscription_availability_changed


@login_required
@require_http_methods(['POST'])
def ajax_toggle_booking(request, event_id):
    """
    This view should only be used for booking, rebooking or cancelling, where the
    user has an available payment method
    We keep all the logic around checking for cancelled/full events etc in case
    events are updated concurrently.
    """
    user_id = request.POST["user_id"]
    ref = request.POST.get("ref", "events")

    if str(user_id) == str(request.user.id):
        user = request.user
    else:
        user = get_object_or_404(User, id=user_id)

    if not has_active_disclaimer(user):
        url = reverse('booking:disclaimer_required', args=(user_id,))
        return JsonResponse({"redirect": True, "url": url})

    event = Event.objects.get(id=event_id)
    event_was_full = not event.course and event.spaces_left == 0
    block_availability_changed = False
    subscription_availability_changed = False
    subscription_use_pre_change = None
    available_subscription = get_available_user_subscription(user, event)
    if available_subscription:
        subscription_use_pre_change = available_subscription.usage_for_event_type_and_date(event.event_type, event.start)

    try:
        existing_booking = Booking.objects.get(user=user, event=event)
    except Booking.DoesNotExist:
        existing_booking = None

    if existing_booking is None:
        requested_action = "opened"
    else:
        requested_action = REQUESTED_ACTIONS[(existing_booking.status, existing_booking.no_show)]

    host = f'http://{request.META.get("HTTP_HOST")}'

    if requested_action in ["opened", "reopened"]:
        # OPENING/REOPENING
        # make sure the event isn't full or cancelled
        if event.spaces_left <= 0 or event.cancelled:
            # redirect if:
            # - non-course event
            # - course event and user has no booking
            # - course event and user has fully cancelled booking
            # (course events with no-show bookings can rebook)
            redirect400 = True
            if event.course and existing_booking and existing_booking.no_show:
                # Course no-shows are allowed to rebook, only fully cancelled ones count
                # in the booking count
                redirect400 = False

            if redirect400:
                logger.error('Attempt to book %s class',
                             'cancelled' if event.cancelled else 'full')
                return HttpResponseBadRequest(
                    "Sorry, this event {}".format(
                        "has been cancelled" if event.cancelled else "is now full")
                )

        # has available course block/subscription
        if event.course and ref == "events" and has_available_course_block(user, event.course):
            if requested_action == "opened" or existing_booking and existing_booking.status == "CANCELLED":
                # First time booking for a course event, or reopening a fully cancelled course booking - redirect to book course
                # rebookings for no-shows can be done from events page
                url = reverse('booking:course_events', args=(event.course.slug,))
                return JsonResponse({"redirect": True, "url": url})

        # get drop-in and subscription payment methods only; course bookings are done from
        # the course page (apart from no_show course bookings)
        has_payment_method = has_available_block(user, event, dropin_only=True) or has_available_subscription(user, event)
        no_show_course_booking = event.course and existing_booking and existing_booking.no_show
        if not no_show_course_booking and not has_payment_method:
            # rebooking, no block on booking (i.e. was fully cancelled) and no block available
            if event.course:
                url = reverse("booking:course_purchase_options", args=(event.course.slug,))
            else:
                url = reverse("booking:event_purchase_options", args=(event.slug,))
            return JsonResponse({"redirect": True, "url": url})

        # Update/create the booking
        if existing_booking is None:
            booking = Booking.objects.create(user=user, event=event)
        else:
            booking = existing_booking

        existing_no_show_with_block = booking.block is not None and booking.no_show
        booking.status = 'OPEN'
        booking.no_show = False
        if not existing_no_show_with_block:
            # if this was already a no-show, with a block assigned, we just keep that block
            # Otherwise, assign next block; if it's new course event bookking, use a drop in block
            # if both course/dropin are available
            # full course bookings are only done from the course page
            booking.assign_next_available_subscription_or_block(dropin_only=True)
        booking.save()
        if booking.block and booking.block.full:
            block_availability_changed = True
        if booking.subscription:
            subscription_availability_changed = has_subscription_availability_changed(booking, requested_action, subscription_use_pre_change)

        try:
            waiting_list_user = WaitingListUser.objects.get(user=booking.user, event=booking.event)
            waiting_list_user.delete()
            ActivityLog.objects.create(
                log=f'User {user.username} removed from waiting list for {event}'
            )
        except WaitingListUser.DoesNotExist:
            pass

    else:
        booking = existing_booking
        block_pre_cancel = booking.block
        block_pre_cancel_was_full = block_pre_cancel.full if block_pre_cancel else False

        if event.course and booking.block and booking.block.block_config.course:
            # only course events booked with course blocks get set to no-show
            booking.no_show = True
        elif not event.event_type.allow_booking_cancellation:
            booking.no_show = True
        else:
            if event.can_cancel:
                booking.block = None
                booking.status = "CANCELLED"
            else:
                booking.no_show = True
        booking.save()
        if block_pre_cancel_was_full:
            if not block_pre_cancel.full:
                block_availability_changed = True
        elif booking.subscription:
            subscription_availability_changed = has_subscription_availability_changed(booking, requested_action, subscription_use_pre_change)

        if event_was_full:
            waiting_list_users = WaitingListUser.objects.filter(event=event)
            send_waiting_list_email(event, waiting_list_users, host)

    ActivityLog.objects.create(
            log=f'Booking {booking.id} {requested_action} for "{event}" (user {user.first_name} {user.last_name}) by user {request.user.username}'
        )

    # email context
    ctx = {
          'host': host,
          'booking': booking,
          'manager_user': request.user,
          'requested_action': requested_action,
          'event': event,
          'date': event.start.strftime('%A %d %B'),
          'time': event.start.strftime('%H:%M'),
    }

    subjects = {
        "user": f"Booking for {event} {requested_action if requested_action == 'cancelled' else ''}",
        "studio": f"{user.first_name} {user.last_name} has just booked for {event}"
    }

    # send emails
    send_user_and_studio_emails(
        ctx, request.user, event.event_type.email_studio_when_booked, subjects, "booking_created_or_updated"
    )

    alert_message = {}
    alert_message['message_type'] = 'info' if requested_action == "cancelled" else 'success'
    alert_message['message'] = f"Booking has been {requested_action}"

    if ref != "course":
        page = request.POST.get("page", 1)
        if block_availability_changed or subscription_availability_changed:
            # subscription or block have changed, redirect to the same page again to refresh buttons
            # Ignore if we came from the course page
            messages.success(request, f"{event}: {alert_message['message']}")
            if ref == "bookings":
                url = reverse("booking:bookings")
            else:
                url = reverse("booking:events", args=(event.event_type.track.slug,))
            return JsonResponse({"redirect": True, "url": url + f"?page={page}"})

    user_info = get_user_booking_info(user, event)
    if ref == "course":
        button_info = button_options_events_list(user, event, course=True)
    elif ref == "events":
        button_info = button_options_events_list(user, event)
    elif ref == "bookings":
        button_info = booking_list_button(booking)
    context = {
        "booking": booking,
        "event": event,
        "alert_message": alert_message,
        "button_info": button_info
    }
    if ref == "bookings":
        html = render_to_string(f"booking/includes/bookings_button.txt", context, request)
    else:
        html = render_to_string(f"booking/includes/events_button.txt", context, request)
    block_info_html = render_to_string(f"booking/includes/block_info.html", context, request)
    event_availability_html = render_to_string(f"booking/includes/event_availability_badge.html", {"event": event}, request)
    event_info_xs_html = render_to_string(
        'booking/includes/event_info_xs.html', 
        {"event": event, "user_info": user_info, "button_info": button_info}, 
        request
    )
    
    return JsonResponse(
        {
            "html": html,
            "button_text": button_info["text"],
            "hide_payment_button": "payment_options" not in button_info.get("buttons", []),
            "block_info_html": block_info_html,
            "event_availability_html": event_availability_html,
            "event_info_xs_html": event_info_xs_html,
            "just_cancelled": requested_action == "cancelled",
        }
    )


@login_required
@require_http_methods(['POST'])
def ajax_toggle_waiting_list(request, event_id):
    user_id = request.POST["user_id"]
    event = Event.objects.get(id=event_id)

    # toggle current status
    try:
        waitinglistuser = WaitingListUser.objects.get(user_id=user_id, event=event)
        waitinglistuser.delete()
        on_waiting_list = False
    except WaitingListUser.DoesNotExist:
        WaitingListUser.objects.create(user_id=user_id, event=event)
        on_waiting_list = True

    return render(
        request,
        "booking/includes/waiting_list_button.html",
        {'event': event, "user_info": {"on_waiting_list": on_waiting_list}}
    )


@login_required
@require_http_methods(['POST'])
def ajax_course_booking(request, course_id):
    ref = request.POST.get("ref", "course")
    user_id = request.POST["user_id"]
    if str(user_id) == str(request.user.id):
        user = request.user
    else:
        user = get_object_or_404(User, id=user_id)

    if not has_active_disclaimer(user):
        # DISCLAIMER FOR BOOKING USER, NOT NEC REQUEST.USER
        url = reverse('booking:disclaimer_required', args=(user_id,))
        return JsonResponse({"redirect": True, "url": url})

    course = Course.objects.get(id=course_id)

    if not has_available_course_block(user, course):
        url = reverse('booking:course_purchase_options', args=(course.slug,))
        return JsonResponse({"redirect": True, "url": url})

    if course.full or course.cancelled:
        logger.error('Attempt to book %s course', 'cancelled' if course.cancelled else 'full')
        return HttpResponseBadRequest(
            "Sorry, this course {}".format("has been cancelled" if course.cancelled else "is now full")
        )

    course_block = get_active_user_course_block(user, course)
    # Book all events
    for event in course.events_left:
        booking, _ = Booking.objects.get_or_create(user=user, event=event)
        # Make sure block is assigned and update booking statuses if already created
        old_block = booking.block
        # switch block first so we don't delete bookings when we delete the block
        booking.block = course_block
        booking.status = "OPEN"
        booking.no_show = False
        booking.save()
        if old_block and not old_block.paid and old_block.block_config.size == 1:
            # delete any associated unpaid single blocks - these are drop-ins added 
            # to shopping basket; we're replacing them with a course block
            old_block.delete()

    ActivityLog.objects.create(
        log=f'Course {course} (start {course.start.strftime("%d-%m-%Y")} for {user.first_name} {user.last_name} '
            f'booked by user {request.user.username}'
    )

    # email context
    ctx = {
        'host': f'http://{request.META.get("HTTP_HOST")}',
        'course': course,
        'course_user': user,
        'manager_user': request.user
    }
    subjects = {
        "user": f"Course booked: {course.name}",
        "studio": f'{user.first_name} {user.last_name} has just booked for course: {course}'
    }
    # send emails
    send_user_and_studio_emails(
        ctx, request.user, course.event_type.email_studio_when_booked, subjects, "course_booked"
    )

    messages.success(request, f"Course {course.name} booked")

    page = request.POST.get("page", 1)
    if ref == "course_list":
        url = reverse('booking:courses', args=(course.event_type.track.slug,)) + f"?page={page}"
    elif ref == "events":
        url = reverse('booking:events', args=(course.event_type.track.slug,)) + f"?page={page}"
    else:
        url = reverse('booking:course_events', args=(course.slug,))
    return JsonResponse({"redirect": True, "url": url})


ITEM_TYPE_MODEL_MAPPING = {
    "block": Block,
    "subscription": Subscription,
    "gift_voucher": GiftVoucher,
    "product_purchase": ProductPurchase,
}


@require_http_methods(['POST'])
def ajax_cart_item_delete(request):
    item_type = request.POST.get("item_type")
    item_id = request.POST.get("item_id")
    item = get_object_or_404(ITEM_TYPE_MODEL_MAPPING[item_type], pk=item_id)
    refresh = False
    if request.user.is_authenticated:
        if isinstance(item, Block):
            if item.voucher is not None and item.voucher.item_count > 1:
                refresh = True
            # delete any bookings attached to this block
            item.bookings.all().delete()
        item.delete()
        if refresh:
            url = reverse('booking:shopping_basket')
            return JsonResponse({"redirect": True, "url": url})
        unpaid_blocks = get_unpaid_user_managed_blocks(request.user)
        unpaid_subscriptions = get_unpaid_user_managed_subscriptions(request.user)
        unpaid_gift_vouchers = get_unpaid_user_gift_vouchers(request.user)
        unpaid_merchandise = get_unpaid_user_merchandise(request.user)
        total = calculate_user_cart_total(unpaid_blocks, unpaid_subscriptions, unpaid_gift_vouchers, unpaid_merchandise)
        unpaid_item_count = total_unpaid_item_count(request.user)
    else:
        assert item_type == "gift_voucher"
        gift_vouchers_on_session = request.session.get("purchases", {}).get("gift_vouchers", [])
        if int(item_id) in gift_vouchers_on_session:
            gift_vouchers_on_session.remove(int(item_id))
            request.session["purchases"]["gift_vouchers"] = gift_vouchers_on_session
            item.delete()
        unpaid_gift_vouchers = get_unpaid_gift_vouchers_from_session(request)
        unpaid_item_count = unpaid_gift_vouchers.count()
        total = calculate_user_cart_total(unpaid_gift_vouchers=unpaid_gift_vouchers)

    payment_button_html = render(
        request, f"booking/includes/payment_button.txt", {"total_cost": total}
    )
    return JsonResponse(
        {
            "cart_total": total,
            "cart_item_menu_count": unpaid_item_count,
            "payment_button_html": payment_button_html.content.decode("utf-8")
        })


@login_required
@require_http_methods(['POST'])
def ajax_block_purchase(request, block_config_id):
    user_id = request.POST["user_id"]
    user = get_object_or_404(User, pk=user_id)
    block_config = get_object_or_404(BlockConfig, pk=block_config_id)
    block = Block.objects.create(user=user, block_config=block_config, paid=False)
    return process_block_purchase(request, block, block_config)


def process_block_purchase(request, block, block_config):
    block_user = block.user
    block_user_name = f"{block_user.first_name} {block_user.last_name}"
    alert_message = {
        "message_type": "success",
        "message": f"Block added to cart for {block_user_name}"
    }
    context = {
        "available_block_config": block_config,
        "available_user": block_user,
        "alert_message": alert_message
    }
    html = render(request, f"booking/includes/blocks_button.txt", context)
    return JsonResponse(
        {
            "html": html.content.decode("utf-8"),
            "cart_item_menu_count": total_unpaid_item_count(request.user),
        }
    )


@login_required
@require_http_methods(['POST'])
def ajax_subscription_purchase(request, subscription_config_id):
    user_id = request.POST["user_id"]
    subscription_start_date = request.POST["subscription_start_date"]

    if subscription_start_date:
        start_date = datetime.strptime(subscription_start_date, "%d-%b-%y").replace(tzinfo=dt_timezone.utc)
        start_date = start_of_day_in_utc(start_date)
    else:
        start_date = None

    user = get_object_or_404(User, pk=user_id)
    subscription_config = get_object_or_404(SubscriptionConfig, pk=subscription_config_id)

    if start_date and subscription_config.start_options == "signup_date" and start_date == start_of_day_in_utc(timezone.now()):
        # for a signup date subscription that's calculated to start today, user could have a previous unpaid one.
        # The start date should be None, but in case it was set at some point, check for an earlier start as well as None
        matching = user.subscriptions.filter(
            Q(paid=False, config=subscription_config) & (Q(start_date__lte=start_date) | Q(start_date__isnull=True))
        )
        if matching.exists():
            subscription = matching.first()
            # make sure the start is set to None, as we expect
            if subscription.start_date is not None:
                subscription.start_date = None
                subscription.save()
            new = False
        else:
            # start_date is today's date, but since this is a signup_date subscription, we create it with
            # None as the start date.  Actual start date will be set when it's paid.
            subscription = Subscription.objects.create(
                user=user, config=subscription_config, start_date=None, paid=False
            )
            new = True
    else:
        subscription, new = Subscription.objects.get_or_create(
            user=user, config=subscription_config, start_date=start_date, paid=False
        )
    return process_subscription_purchase(request, subscription, new, subscription_config)


def process_subscription_purchase(request, subscription, new, subscription_config):
    subscription_user = subscription.user
    subscription_user_name = full_name(subscription_user)
    if not new:
        subscription.delete()
        alert_message = {
            "message_type": "info",
            "message": f"Subscription removed from cart for {subscription_user_name}"
        }
    else:
        alert_message = {
            "message_type": "success",
            "message": f"Subscription added to cart for {subscription_user_name}"
        }
    context = {
        "subscription_start_option": subscription.start_date,
        "subscription_config": {"config": subscription_config},
        "available_user": subscription_user,
        "alert_message": alert_message
    }
    html = render(request, f"booking/includes/subscriptions_button.txt", context)
    return JsonResponse(
        {
            "html": html.content.decode("utf-8"),
            "cart_item_menu_count": total_unpaid_item_count(request.user),
        }
    )


@login_required
@require_http_methods(['POST'])
def ajax_add_booking_to_basket(request):
    """
    Add a booking to basket
    - find the matching single class block_config that's valid for this event
    - create a block for the user (unpaid)
    - create a booking for the user/event and assign the block
    check:
    although unpaid, the new booking counts in the event's full/spaces etc
    clean up unpaid bookings/blocks every 15 mins
    clean up on visiting shopping basket (fetching unpaid blocks) and schedule
    add a stripe checkout flag when user proceeds to checkout (similar to merch)
    shopping cart/checkout - display blocks with attached booking as booking (hide block info)
    booking buttons need to also show "payment pending" instead of "booked" where bookings are
    made but blocks not yet paid
    ADMIN - if admin user adds a booking, either need to force it to be paid, or flag so it
    doesn't get deleted
    """
    user_id = request.POST["user_id"]
    if str(user_id) == str(request.user.id):
        user = request.user
    else:
        user = get_object_or_404(User, id=user_id)
    event = get_object_or_404(Event, pk=request.POST["event_id"])
    # we could get here from the events list or course events list 
    ref = request.POST["ref"]
    
    ######################################
    # check event isn't full or cancelled, return error
    # check user isn't already (open) booked, return error
    # get booking if one already exists (could have been previously cancelled)
    if not has_active_disclaimer(request.user):
        url = reverse('booking:disclaimer_required', args=(request.user.id,))
        return JsonResponse({"redirect": True, "url": url})
    
    try:
        existing_booking = Booking.objects.get(user=user, event=event)
    except Booking.DoesNotExist:
        existing_booking = None

    if existing_booking:
        # redirect if user already has open booking, or if they have a no-show course booking
        if existing_booking.status == "OPEN" and existing_booking.no_show is False:
            if existing_booking.block:
                return HttpResponseBadRequest("Already added to cart")
            logger.error('Attempt to add to cart with existing open booking for event %s, user %s', event.id, user.username)
            return HttpResponseBadRequest("Open booking already exists")
        if event.course and existing_booking.block and existing_booking.no_show:
            logger.error('Attempt to add to cart with existing no-show course booking for event %s, user %s', event.id, user.username)
            return HttpResponseBadRequest("Booking can be reopened")

    if event.spaces_left <= 0 or event.cancelled:
        # redirect if full or cancelled:
        logger.error('Attempt to add to cart for %s event', 'cancelled' if event.cancelled else 'full')
        return HttpResponseBadRequest(
            "Sorry, this event {}".format(
                "has been cancelled" if event.cancelled else "is now full")
        )

    ######################################
    # create booking
    booking, _ = Booking.objects.update_or_create(
        user=user, event=event, defaults={"status": "OPEN", "no_show": False}
    )
    # create block
    single_block_config = add_to_cart_drop_in_block_config(event)
    block = Block.objects.create(block_config=single_block_config, user=user, paid=False)
    # assign unpaid block to booking
    booking.block = block
    booking.save()

    #######################################
    alert_message = {
        "message_type": "success",
        "message": f"Booking for {event} added to cart for {full_name(user)}"
    }
    context = {
        "alert_message": alert_message
    }
    # js needs to set "add to cart" button to empty
    # update booking button (depending on value of ref)
    # use button_info to update text fields
    if ref == "events":
        user_info = get_user_booking_info(user, event)
        button_info = button_options_events_list(user, event)
        context["button_info"] = button_info
        button_html = render(request, f"booking/includes/events_button.txt", context)
    elif ref == "course":
        context["booked"] = True
        user_info = get_user_course_booking_info(user, event.course)
        button_info = button_options_events_list(user, event, course=True)
        context["button_info"] = button_info
        button_html = render(request, f"booking/includes/course_events_button.txt", context)

    event_availability_html = render_to_string(f"booking/includes/event_availability_badge.html", {"event": event}, request)
    event_info_xs_html = render_to_string(
        'booking/includes/event_info_xs.html', 
        {"event": event, "user_info": user_info, "button_info": button_info}, 
        request
    )

    return JsonResponse(
        {   
            "button_info": button_info,
            "button_html": button_html.content.decode("utf-8"),
            "cart_item_menu_count": total_unpaid_item_count(request.user),
            "event_availability_html": event_availability_html,
            "event_info_xs_html": event_info_xs_html
        }
    )


@login_required
@require_http_methods(['POST'])
def ajax_add_course_booking_to_basket(request):
    """
    Add a course to basket
    - find the matching course block_config that's valid for this course
    - create a course block for the user (unpaid)
    - create bookings for the user/course and assign the block
    check:
    although unpaid, the new booking counts in the course's full/spaces etc
    clean up unpaid course bookings/blocks every 15 mins
    clean up on visiting shopping basket (fetching unpaid blocks) and schedule
    add a stripe checkout flag when user proceeds to checkout (similar to merch)
    shopping cart/checkout - display blocks with attached course booking as course (hide block info)
    """
    user_id = request.POST["user_id"]
    if str(user_id) == str(request.user.id):
        user = request.user
    else:
        user = get_object_or_404(User, id=user_id)
    course = get_object_or_404(Course, pk=request.POST["course_id"])
    # we could get here from the events list or course events list 
    ref = request.POST["ref"]

    # check user isn't already booked, return error
    existing_course_block_bookings = user.bookings.filter(
        block__block_config__course=True, event__course=course
    )

    if existing_course_block_bookings.exists() and (
        existing_course_block_bookings.count() == course.uncancelled_events.count()
    ):
        if existing_course_block_bookings.first().block.paid:
            # user has bookings with paid course block for full course
            logger.error('Attempt to add to basket with existing course booking for course %s, user %s', course.id, user.username)
            return HttpResponseBadRequest("Course booking already exists")
        else:
            logger.error('Already added course %s to basket', course.id)
            return HttpResponseBadRequest("Already added to cart")

    # check course isn't full or cancelled, return error
    if not has_active_disclaimer(user):
        url = reverse('booking:disclaimer_required', args=(user_id,))
        return JsonResponse({"redirect": True, "url": url})
    if course.full or course.cancelled:
        logger.error('Attempt to add %s course to cart', 'cancelled' if course.cancelled else 'full')
        return HttpResponseBadRequest(
            "Course {}".format("has been cancelled" if course.cancelled else "is now full")
        )

    # create UNPAID block
    block_config = add_to_cart_course_block_config(course=course)
    course_block = Block.objects.create(block_config=block_config, user=user, paid=False)

    # Create/get bookings for all events
    for event in course.events_left:
        booking, _ = Booking.objects.get_or_create(user=user, event=event)
        # Make sure block is assigned and update booking statuses if already created
        existing_block = booking.block
        # switch block first so we don't delete bookings when we delete the block
        booking.block = course_block
        booking.status = "OPEN"
        booking.no_show = False
        booking.save()

        if existing_block and not existing_block.paid and existing_block.block_config.size == 1:
            # delete any associated unpaid single blocks - these are drop-ins added 
            # to shopping basket; we're replacing them with a course block
            existing_block.delete()
    
    #######################################
    messages.success(request, f"Booking for {course} added to cart for {full_name(user)}")
    # we need to update info about all course events, so we redirect to refresh the page
    if ref == "course":  # events list for a course
        redirect_url = reverse("booking:course_events", args=(course.slug,))
    elif ref == "course_list":  # courses list
        redirect_url = reverse("booking:courses", args=(course.event_type.track.slug,))
    else: # events list (all)
        redirect_url = reverse("booking:events", args=(course.event_type.track.slug,))

    return JsonResponse({"redirect": True, "url": redirect_url})
