import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.http import HttpResponseBadRequest, JsonResponse
from django.template.loader import get_template
from django.views.decorators.http import require_http_methods
from django.urls import reverse
from django.shortcuts import get_object_or_404, render, HttpResponse

from accounts.models import has_active_disclaimer
from activitylog.models import ActivityLog

from ..models import Booking, Block, Course, Event, WaitingListUser
from ..utils import calculate_user_cart_total, has_available_block, get_active_user_block
from ..email_helpers import send_waiting_list_email, send_user_and_studio_emails


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
    if user_id == request.user.id:
        user = request.user
    else:
        user = get_object_or_404(User, id=user_id)

    if not has_active_disclaimer(user):
        # TODO
        # url = reverse('booking:disclaimer_required', args=(user_id,))
        url = reverse('booking:disclaimer_required')
        return JsonResponse({"redirect": True, "url": url})

    event = Event.objects.get(id=event_id)
    event_was_full = not event.course and event.spaces_left == 0

    if not has_available_block(user, event):
        if event.course:
            url = reverse('booking:course_events', args=(event.course.slug,))
        else:
            url = reverse('booking:dropin_block_purchase', args=(event.slug,))
        return JsonResponse({"redirect": True, "url": url})

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
            logger.error('Attempt to book %s class', 'cancelled' if event.cancelled else 'full')
            return HttpResponseBadRequest(
                "Sorry, this event {}".format("has been cancelled" if event.cancelled else "is now full")
            )

        if event.course and requested_action == "opened":
            # First time booking for a course event - redirect to book course
            # rebookings can be done from events page
            url = reverse('booking:course_events', args=(event.course.slug,))
            return JsonResponse({"redirect": True, "url": url})

        # Update/create the booking
        if existing_booking is None:
            booking = Booking.objects.create(user=user, event=event)
        else:
            booking = existing_booking
        booking.status = 'OPEN'
        booking.no_show = False
        booking.block = get_active_user_block(user, event)
        booking.save()
        ActivityLog.objects.create(
            log=f'Booking {booking.id} {requested_action} for "{event}" (user {user.first_name} {user.last_name}) made by user {request.user.username}'
        )

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
        else:
            booking.block = None
            booking.status = "CANCELLED"
        booking.save()

        if event_was_full:
            waiting_list_users = WaitingListUser.objects.filter(event=event)
            send_waiting_list_email(event, waiting_list_users, host)

    # email context
    ctx = {
          'host': host,
          'booking': booking,
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
    context = {
        "event": event,
        "alert_message": alert_message,
        "just_booked": requested_action in ["opened", "reopened"],
        "just_cancelled": requested_action == "cancelled"
    }
    html = render(request, f"booking/includes/events_button.txt", context)
    block_info_html = render(request, f"booking/includes/block_info.html", {"event": event})
    event_availability_html = render(request, f"booking/includes/event_availability_badge.html", {"event": event})
    return JsonResponse(
        {
            "html": html.content.decode("utf-8"),
            "block_info_html": block_info_html.content.decode("utf-8"),
            "event_availability_html": event_availability_html.content.decode("utf-8"),
            "just_cancelled": requested_action == "cancelled",
        }
    )


def placeholder(request):
    return HttpResponse("Placeholder")


@login_required
@require_http_methods(['POST'])
def ajax_toggle_waiting_list(request, event_id):
    user_id = request.POST["user_id"]
    event = Event.objects.get(id=event_id)

    # toggle current status
    try:
        waitinglistuser = WaitingListUser.objects.get(user_id=user_id, event=event)
        waitinglistuser.delete()
    except WaitingListUser.DoesNotExist:
        WaitingListUser.objects.create(user_id=user_id, event=event)

    return render(
        request,
        "booking/includes/waiting_list_button.html",
        {'event': event}
    )


@login_required
@require_http_methods(['POST'])
def ajax_course_booking(request, course_id):

    user_id = request.POST["user_id"]
    if user_id == request.user.id:
        user = request.user
    else:
        user = get_object_or_404(id=user_id)

    if not has_active_disclaimer(user):
        # TODO DISCLAIMER FOR BOOKING USER, NOT NEC REQUEST.USER
        url = reverse('booking:disclaimer_required')
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
    }
    subjects = {
        "user": f"You have booked for a course: {course.name}",
        "studio": f'{user.first_name} {user.last_name} has just booked for course: {course}'
    }
    # send emails
    send_user_and_studio_emails(
        ctx, request.user, course.course_type.event_type.email_studio_when_booked, subjects, "course_booked"
    )

    alert_message = {}
    alert_message['message_type'] = 'success'
    alert_message['message'] = "Course booking created"
    url = reverse('booking:course_events', args=(course.slug,))
    return JsonResponse({"redirect": True, "url": url})


@login_required
@require_http_methods(['POST'])
def ajax_block_delete(request, block_id):
    block = get_object_or_404(Block, pk=block_id)
    block.delete()
    unpaid_blocks = Block.objects.filter(paid=False, user__in=request.user.managed_users)
    total = calculate_user_cart_total(unpaid_blocks)
    return JsonResponse({"cart_total": total, "cart_item_menu_count": unpaid_blocks.count()})
