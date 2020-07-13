import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.http import require_http_methods
from django.urls import reverse
from django.shortcuts import get_object_or_404, render, HttpResponse

from accounts.models import has_active_disclaimer
from activitylog.models import ActivityLog

from ..models import Booking, Block, Course, Event, WaitingListUser, DropInBlockConfig, CourseBlockConfig
from ..utils import calculate_user_cart_total, has_available_block, get_active_user_block, get_user_booking_info
from ..email_helpers import send_waiting_list_email, send_user_and_studio_emails
from .views_utils import get_unpaid_user_managed_blocks


logger = logging.getLogger(__name__)


REQUESTED_ACTIONS = {
    ("CANCELLED", True): "reopened",
    ("CANCELLED", False): "reopened",
    ("OPEN", True): "reopened",
    ("OPEN", False): "cancelled",
}

@login_required
@require_http_methods(['POST'])
def ajax_toggle_booking(request, event_id):
    user_id = request.POST["user_id"]
    ref = request.POST.get("ref", "events")

    if user_id == request.user.id:
        user = request.user
    else:
        user = get_object_or_404(User, id=user_id)

    if not has_active_disclaimer(user):
        url = reverse('booking:disclaimer_required', args=(user_id,))
        return JsonResponse({"redirect": True, "url": url})

    event = Event.objects.get(id=event_id)
    event_was_full = not event.course and event.spaces_left == 0

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

        if event.course and requested_action == "opened":
            # First time booking for a course event - redirect to book course
            # rebookings can be done from events page
            url = reverse('booking:course_events', args=(event.course.slug,))
            return JsonResponse({"redirect": True, "url": url})

        if not has_available_block(user, event) and not event.course:
            url = reverse("booking:dropin_block_purchase", args=(event.slug,))
            return JsonResponse({"redirect": True, "url": url})

        # OPENING/REOPENING
        # make sure the event isn't full or cancelled
        if not event.course and (event.spaces_left <= 0 or event.cancelled):
            logger.error('Attempt to book %s class', 'cancelled' if event.cancelled else 'full')
            return HttpResponseBadRequest(
                "Sorry, this event {}".format("has been cancelled" if event.cancelled else "is now full")
            )

        # Update/create the booking
        if existing_booking is None:
            booking = Booking.objects.create(user=user, event=event)
        else:
            booking = existing_booking
        booking.status = 'OPEN'
        booking.no_show = False
        booking.block = get_active_user_block(user, event)
        booking.save()

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
        if event.course:
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
        "user": f"Booking for {event} {requested_action}",
        "studio": f"{user.first_name} {user.last_name} has just booked for {event}"
    }

    # send emails
    send_user_and_studio_emails(
        ctx, request.user, event.event_type.email_studio_when_booked, subjects, "booking_created_or_updated"
    )

    alert_message = {}
    alert_message['message_type'] = 'info' if requested_action == "cancelled" else 'success'
    alert_message['message'] = f"Booking has been {requested_action}"

    if not has_available_block(user, booking.event) and ref != "course":
        # We no longer have available blocks, redirect to the same page again to refresh buttons
        # Ignore if we came from the course page
        messages.success(request, f"{event}: {alert_message['message']}")
        if ref == "bookings":
            url = reverse("booking:bookings")
        else:
            url = reverse("booking:events", args=(event.event_type.track.slug,))
        return JsonResponse({"redirect": True, "url": url})

    context = {
        "event": event,
        "alert_message": alert_message,
        "user_info": get_user_booking_info(user, event),
    }
    html = render(request, f"booking/includes/events_button.txt", context)
    block_info_html = render(request, f"booking/includes/block_info.html", context)
    event_availability_html = render(request, f"booking/includes/event_availability_badge.html", {"event": event})
    return JsonResponse(
        {
            "html": html.content.decode("utf-8"),
            "block_info_html": block_info_html.content.decode("utf-8"),
            "event_availability_html": event_availability_html.content.decode("utf-8"),
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

    user_id = request.POST["user_id"]
    if user_id == request.user.id:
        user = request.user
    else:
        user = get_object_or_404(User, id=user_id)

    if not has_active_disclaimer(user):
        # DISCLAIMER FOR BOOKING USER, NOT NEC REQUEST.USER
        url = reverse('booking:disclaimer_required', args=(user_id,))
        return JsonResponse({"redirect": True, "url": url})

    course = Course.objects.get(id=course_id)

    if not has_available_block(user, course.events.first()):
        url = reverse('booking:course_block_purchase', args=(course.slug,))
        return JsonResponse({"redirect": True, "url": url})

    if course.full or course.cancelled:
        logger.error('Attempt to book %s course', 'cancelled' if course.cancelled else 'full')
        return HttpResponseBadRequest(
            "Sorry, this course {}".format("has been cancelled" if course.cancelled else "is now full")
        )

    course_block = get_active_user_block(user, course.events.first())
    # Book all events
    for event in course.events.all():
        booking, _ = Booking.objects.get_or_create(user=user, event=event)
        # Make sure block is assigned but don't change booking statuses if already created
        booking.block = course_block
        booking.save()

        ActivityLog.objects.create(
            log=f'Course {course.name} (course.course_type) for {user.first_name} {user.last_name} booked by user {request.user.username}'
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
        ctx, request.user, course.course_type.event_type.email_studio_when_booked, subjects, "course_booked"
    )

    messages.success(request, "Course booking created")
    url = reverse('booking:course_events', args=(course.slug,))
    return JsonResponse({"redirect": True, "url": url})


@login_required
@require_http_methods(['POST'])
def ajax_block_delete(request, block_id):
    block = get_object_or_404(Block, pk=block_id)
    block.delete()
    unpaid_blocks = Block.objects.filter(paid=False, user__in=request.user.managed_users)
    total = calculate_user_cart_total(unpaid_blocks)
    payment_button_html = render(
        request, f"booking/includes/payment_button.txt", {"total_cost": total}
    )
    return JsonResponse(
        {
            "cart_total": total,
            "cart_item_menu_count": unpaid_blocks.count(),
            "payment_button_html": payment_button_html.content.decode("utf-8")
        })


@login_required
@require_http_methods(['POST'])
def ajax_dropin_block_purchase(request, block_config_id):
    user_id = request.POST["user_id"]
    user = get_object_or_404(User, pk=user_id)
    block_config = get_object_or_404(DropInBlockConfig, pk=block_config_id)
    block, new = Block.objects.get_or_create(user=user, dropin_block_config=block_config, paid=False)
    return process_block_purchase(request, block, new, block_config)


@login_required
@require_http_methods(['POST'])
def ajax_course_block_purchase(request, block_config_id):
    user_id = request.POST["user_id"]
    user = get_object_or_404(User, pk=user_id)
    course_config = get_object_or_404(CourseBlockConfig, pk=block_config_id)
    block, new = Block.objects.get_or_create(user=user, course_block_config=course_config, paid=False)
    return process_block_purchase(request, block, new, course_config)


def process_block_purchase(request, block, new, block_config):
    block_user = block.user
    block_user_name = f"{block_user.first_name} {block_user.last_name}"
    if not new:
        block.delete()
        alert_message = {
            "message_type": "info",
            "message": f"Block removed from cart for {block_user_name}"
        }
    else:
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
            "cart_item_menu_count": get_unpaid_user_managed_blocks(request.user).count(),
        }
    )
