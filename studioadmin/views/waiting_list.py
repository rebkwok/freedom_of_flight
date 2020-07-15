import logging

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User

from django.contrib import messages
from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.http import require_http_methods
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404, render

from booking.models import Event, WaitingListUser

from studioadmin.views.utils import is_instructor_or_staff
from activitylog.models import ActivityLog


logger = logging.getLogger(__name__)


@login_required
@is_instructor_or_staff
def event_waiting_list_view(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    waiting_list_users = WaitingListUser.objects.filter(event__id=event_id).order_by('user__username')
    if waiting_list_users:
        users_on_waiting_list_ids = waiting_list_users.values_list("user_id", flat=True)
        # cleanup waiting list - remove any users with open bookings
        bookings_for_wl_users = event.bookings.filter(status="OPEN", no_show="False", user_id__in=users_on_waiting_list_ids)
        for booking in bookings_for_wl_users:
            waiting_list_users.get(user_id=booking.user.id).delete()

    template = 'studioadmin/event_waiting_list.html'

    return TemplateResponse(
        request, template, {'waiting_list_users': waiting_list_users, 'event': event,}
    )


@login_required
@is_instructor_or_staff
@require_http_methods(['POST'])
def ajax_remove_from_waiting_list(request):
    wluser_id = request.POST["wluser_id"]
    event_id = request.POST["event_id"]
    # toggle current status
    try:
        waitinglistuser = WaitingListUser.objects.get(id=wluser_id, event_id=event_id)
        event = waitinglistuser.event
        user = waitinglistuser.user
        waitinglistuser.delete()
        ActivityLog.objects.create(
            log=f"{waitinglistuser.user.username} removed from the waiting list for {event} "
                f"by admin user {request.user.username}"
        )
    except WaitingListUser.DoesNotExist:
        return HttpResponseBadRequest(f"User is not on waiting list")

    return JsonResponse(
        {
            'removed': True,
            "alert_msg": f"{user.first_name} {user.last_name} removed from waiting list"
         }
    )