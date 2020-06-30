import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.http import HttpResponseBadRequest, JsonResponse
from django.template.loader import get_template
from django.views.decorators.http import require_http_methods
from django.urls import reverse
from django.shortcuts import HttpResponseRedirect, render, HttpResponse
from django.utils import timezone

from accounts.models import has_active_disclaimer
from activitylog.models import ActivityLog

from ..models import Booking, Event, WaitingListUser
from ..utils import has_available_block, get_active_user_block


logger = logging.getLogger(__name__)


REQUESTED_ACTIONS_FROM_CURRENT_STATUS_AND_NO_SHOW = {
    ("CANCELLED", True): "reopen",
    ("CANCELLED", False): "reopen",
    ("OPEN", True): "reopen",
    ("OPEN", False): "cancel",
}

@login_required
@require_http_methods(['POST'])
def ajax_toggle_booking(request, event_id):
    if not has_active_disclaimer(request.user):
        # TODO
        # url = reverse('booking:disclaimer_required')
        # return JsonResponse({"redirect": True, "url": url})
        pass

    event = Event.objects.get(id=event_id)
    ref = request.GET.get('ref')

    if not has_available_block(request.user, event):
        # TODO
        # url = reverse('booking:block_create')
        url = reverse('booking:placeholder')
        return JsonResponse({"redirect": True, "url": url})

    try:
        existing_booking = Booking.objects.get(user=request.user, event=event)
    except Booking.DoesNotExist:
        existing_booking = None

    if existing_booking is None:
        requested_action = "open"
    else:
        requested_action = REQUESTED_ACTIONS_FROM_CURRENT_STATUS_AND_NO_SHOW[(existing_booking.status, existing_booking.no_show)]

    context = {
        "event": event,
        "ref": ref
    }

    if requested_action in ["open", "reopen"]:
        # OPENING/REOPENING
        # make sure the event isn't full or cancelled
        if event.spaces_left <= 0 or event.cancelled:
            logger.error('Attempt to book %s class', 'cancelled' if event.cancelled else 'full')
            return HttpResponseBadRequest(
                "Sorry, this event {}".format("has been cancelled" if event.cancelled else "is now full")
            )

        if event.course:
            # Booking an event in a course - redirect to book all events
            # TODO
            # url = reverse('booking:book_course'), args=(event.course,)
            url = reverse('booking:placeholder')
            return JsonResponse({"redirect": True, "url": url})

        # Update/create the booking
        if existing_booking is None:
            booking = Booking.objects.create(user=request.user, event=event)
        else:
            booking = existing_booking
        booking.status = 'OPEN'
        booking.no_show = False
        booking.block = get_active_user_block(request.user, event)
        booking.save()
        ActivityLog.objects.create(
            log=f'Booking {booking.id} {requested_action}ed for "{event}" by user {request.user.username}'
        )

        try:
            waiting_list_user = WaitingListUser.objects.get(user=booking.user, event=booking.event)
            waiting_list_user.delete()
            ActivityLog.objects.create(
                log=f'User {request.user.username} removed from waiting list for {event}'
            )
        except WaitingListUser.DoesNotExist:
            pass

    else:
        if not (event.allow_booking_cancellation or event.can_cancel):
            # TODO
            # url = reverse('booking:cancel_booking'), args=(existing_booking.id,)
            url = reverse('booking:placeholder')
            return JsonResponse({"redirect": True, "url": url})

        # CANCELLING
        booking = existing_booking
        if event.course:
            booking.no_show = True
        else:
            booking.block = None
            booking.status = "CANCELLED"
        booking.save()

    # email context
    host = 'http://{}'.format(request.META.get('HTTP_HOST'))
    ctx = {
          'host': host,
          'booking': booking,
          'requested_action': requested_action,
          'event': event,
          'date': event.start.strftime('%A %d %B'),
          'time': event.start.strftime('%H:%M'),
    }

    # send email to user
    send_mail(
        f'{settings.ACCOUNT_EMAIL_SUBJECT_PREFIX} Booking for {event} {requested_action}ed',
        get_template('booking/email/booking_created_or_updated.txt').render(ctx),
        settings.DEFAULT_FROM_EMAIL,
        [request.user.email],
        html_message=get_template('booking/email/booking_created_or_updated.html').render(ctx),
        fail_silently=False
    )

    # send email to studio if flagged for the event - only for open/reopen bookings
    if event.email_studio_when_booked:
        send_mail(
            f'{settings.ACCOUNT_EMAIL_SUBJECT_PREFIX} {request.user.first_name} {request.user.last_name} has just booked for {event}',
            get_template('booking/email/to_studio_booking_created_or_updated.txt').render(ctx),
            settings.DEFAULT_FROM_EMAIL,
            [settings.DEFAULT_STUDIO_EMAIL],
            fail_silently=False
        )

    alert_message = {}
    alert_message['message_type'] = 'warning' if requested_action == "cancel" else 'success'

    alert_message['message'] = f"Booking has been {requested_action}ed"
    context["alert_message"] = alert_message
    context["event"] = event

    all_events = Event.objects.filter(start__gt=timezone.now(), show_on_site=True)
    booked_event_ids = [
        booking.event.id for booking in request.user.bookings.filter(event__id__in=all_events, status="OPEN", no_show=False)
    ]

    context["booked_event_ids"] = booked_event_ids
    html = render(request, f"booking/includes/events_button.txt", context)
    return JsonResponse({"html": html.content.decode("utf-8")})


def placeholder(request):
    return HttpResponse("Placeholder")

# TODO
# @login_required
# def toggle_waiting_list(request, event_id):
#     user = request.user
#     event = Event.objects.get(id=event_id)
#
#     # toggle current status
#     try:
#         waitinglistuser = WaitingListUser.objects.get(user=user, event=event)
#         waitinglistuser.delete()
#         on_waiting_list = False
#     except WaitingListUser.DoesNotExist:
#         WaitingListUser.objects.create(user=user, event=event)
#         on_waiting_list = True
#
#     return render(
#         request,
#         "booking/includes/waiting_list_button.html",
#         {'event': event, 'on_waiting_list': on_waiting_list}
#     )


