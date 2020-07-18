from datetime import datetime

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest, JsonResponse, HttpResponse
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404, render, HttpResponseRedirect
from django.views.generic import ListView, CreateView, UpdateView
from django.utils import timezone
from django.urls import reverse

from braces.views import LoginRequiredMixin

from activitylog.models import ActivityLog
from booking.email_helpers import send_bcc_emails
from booking.models import Booking, Event, Track, EventType
from timetable.models import TimetableSession

from ..forms import TimetableSessionCreateUpdateForm
from .utils import is_instructor_or_staff, staff_required, StaffUserMixin, InstructorOrStaffUserMixin
from .event_views import EventCreateView, EventUpdateView


class TimetableSessionListView(ListView):

    model = TimetableSession
    template_name = "studioadmin/timetable.html"

    def get_queryset(self):
        return super().get_queryset().order_by("day", "time")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_sessions = self.get_queryset()

        track_id = self.request.GET.get('track')
        requested_track = None
        if track_id:
            try:
                requested_track = Track.objects.get(id=track_id)
            except Track.DoesNotExist:
                pass

        # paginate each queryset
        tab = self.request.GET.get('tab', 0)
        try:
            tab = int(tab)
        except ValueError:  # value error if tab is not an integer, default to 0
            tab = 0

        context['tab'] = str(tab)

        tracks = Track.objects.all()
        track_sessions = []
        for i, track in enumerate(tracks):
            track_qs = all_sessions.filter(event_type__track=track)
            if track_qs:
                # Don't add the location tab if there are no events to display
                track_paginator = Paginator(track_qs, 20)
                if "tab" in self.request.GET and tab == i:
                    page = self.request.GET.get('page', 1)
                else:
                    page = 1
                queryset = track_paginator.get_page(page)

                track_obj = {
                    'index': i,
                    'queryset': queryset,
                    'track': track.name
                }
                track_sessions.append(track_obj)

                if requested_track and requested_track == track:
                    # we returned here from another view that was on a particular track, we want to set the
                    # tab to that track
                    context["active_tab"] = i

        context['track_sessions'] = track_sessions
        return context


def ajax_timetable_session_delete(request, timetable_session_id):
    timetable_session = TimetableSession.objects.get(id=timetable_session_id)
    name, weekday, time = timetable_session.name, timetable_session.get_day_name(), timetable_session.time
    timetable_session.delete()
    ActivityLog.objects.create(
        log=f"Timetable session {timetable_session_id} for {name} on {weekday} {time.strftime('%H:%M')} deleted"
    )
    return JsonResponse({"deleted": True, "alert_msg": "Timetable session deleted"})


@login_required
@staff_required
def timetable_session_create_choice_view(request):
    event_types = EventType.objects.all()
    return render(request, "studioadmin/timetable_create_choose_event_type.html", {"event_types": event_types})


class TimetableSessionCreateView(EventCreateView):
    template_name = "studioadmin/timetable_session_create_update.html"
    model = TimetableSession
    form_class = TimetableSessionCreateUpdateForm

    def get_success_url(self, track_id):
        return reverse('studioadmin:timetable') + f"?track={track_id}"


class TimetableSessionUpdateView(EventUpdateView):
    template_name = "studioadmin/timetable_session_create_update.html"
    model = TimetableSession
    form_class = TimetableSessionCreateUpdateForm
    context_object_name = "timetable_session"

    def get_success_url(self, track_id):
        return reverse('studioadmin:timetable') + f"?track={track_id}"
