from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, QuerySet
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.shortcuts import render, HttpResponseRedirect
from django.views.generic import ListView
from django.urls import reverse

from braces.views import LoginRequiredMixin

from activitylog.models import ActivityLog
from booking.models import Event, Track, EventType
from common.utils import full_name
from timetable.models import TimetableSession

from ..forms.forms import TimetableSessionCreateUpdateForm, UploadTimetableForm
from .utils import staff_required, StaffUserMixin, utc_adjusted_datetime
from .event_views import EventCreateView, EventUpdateView


class TimetableSessionListView(LoginRequiredMixin, StaffUserMixin, ListView):

    model = TimetableSession
    template_name = "studioadmin/timetable.html"
    custom_paginate_by = 20

    def get_queryset(self):
        return super().get_queryset().order_by("day", "time")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_sessions = self.get_queryset()

        track_id = self.request.GET.get('track')
        requested_track = None
        if track_id:
            try:
                track_id = int(track_id)
                requested_track = Track.objects.get(id=track_id)
            except (ValueError, Track.DoesNotExist):
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

        day_names = dict(TimetableSession.DAY_CHOICES)
        for i, track in enumerate(tracks):
            track_queryset = all_sessions.filter(event_type__track=track)
            if track_queryset:
                # Don't add the track tab if there are no sessions to display
                track_paginator = Paginator(track_queryset, self.custom_paginate_by)
                page = 1
                if "tab" in self.request.GET and tab == i:
                    try:
                        page = int(self.request.GET.get('page', 1))
                    except ValueError:
                        pass
                page_obj = track_paginator.get_page(page)
                if not isinstance(page_obj.object_list, QuerySet):
                    paginated_ids = [session.id for session in page_obj.object_list]
                    paginated_sessions = track_queryset.filter(id__in=paginated_ids)
                else:  # pragma: no cover
                    paginated_sessions = page_obj.object_list
                session_ids_by_day = paginated_sessions.values('day').annotate(count=Count('id')).values('day', 'id')
                sessions_by_day = {}
                for session_item in session_ids_by_day:
                    sessions_by_day.setdefault(
                        day_names[session_item["day"]], []
                    ).append(track_queryset.get(id=session_item["id"]))
                track_obj = {
                    'index': i,
                    'page_obj': page_obj,
                    'sessions_by_day': sessions_by_day,
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


def get_context(request):
    tab = request.GET.get('tab', 0)
    try:
        tab = int(tab)
    except ValueError:  # value error if tab is not an integer, default to 0
        tab = 0
    context = {'tab': str(tab)}
    tracks = Track.objects.all()
    track_sessions = []
    track_index = 0
    # Don't use enumerate for the track index, because we want to be able to tell the index from the
    # number of tracks.  If we don't include a track because it has no sessions, we don't want the index
    # counter to increment
    for track in tracks:
        if TimetableSession.objects.filter(event_type__track=track).exists():
            form = UploadTimetableForm(track=track, track_index=track_index)
            track_obj = {
                'index': track_index,
                'form': form,
                'track': track.name
            }
            track_sessions.append(track_obj)
            track_index += 1
    context["track_sessions"] = track_sessions
    return context


@login_required
@staff_required
def upload_timetable_view(request):
    context = get_context(request)
    if request.method == "POST":
        track_index = int(request.POST.get("track_index"))
        track = Track.objects.get(id=int(request.POST.get("track")))
        form = UploadTimetableForm(request.POST, track=track, track_index=track_index)
        if form.is_valid():
            uploaded, existing = upload_timetable(
                request, track, form.cleaned_data["start_date"], form.cleaned_data["end_date"],
                form.cleaned_data[f"sessions_{track_index}"], form.cleaned_data["show_on_site"]
            )
            if uploaded:
                messages.success(
                    request, f"Timetable uploaded: {len(uploaded)} new events created")
            if existing:
                messages.info(
                    request, f"Timetable upload omitted {len(existing)} events which would have duplicated existing"
                             f"events with the same name, date and event type"
                )
            return HttpResponseRedirect(reverse("studioadmin:events") + f"?track={track.id}")
        else:
            for track_session in context["track_sessions"]:
                if track_session["track"] == track.name:
                    track_session["form"] = UploadTimetableForm(
                        request.POST, track=track, track_index=track_session["index"]
                    )
                    # make sure the tab is set to the one we're on if we're returning errors
                    context["tab"] = track_session["index"]

    return TemplateResponse(request, "studioadmin/upload_timetable.html", context)


def upload_timetable(request, track, start_date, end_date, session_ids, show_on_site):
    created_events = []
    existing_events = []

    uploading_date = start_date
    while uploading_date <= end_date:
        sessions_to_create = TimetableSession.objects.filter(day=uploading_date.weekday(), id__in=session_ids)
        for session in sessions_to_create:
            # If the session start date is in DST, we need to adjust the literal session time, otherwise it'll be created
            # as that literal time in UTC, which will be 1 hour earlier than we want
            naive_event_start = datetime.combine(uploading_date, session.time)
            event_start = utc_adjusted_datetime(naive_event_start)
            uploaded_event, created = Event.objects.get_or_create(
                name=session.name,
                event_type=session.event_type,
                start=event_start,
                defaults={
                    "description": session.description,
                    "max_participants": session.max_participants,
                    "show_on_site": show_on_site,
                    "duration": session.duration,
                }
            )
            if created:
                created_events.append(uploaded_event)
            else:
                existing_events.append(uploaded_event)
        uploading_date = uploading_date + timedelta(days=1)

    if created_events:
        ActivityLog.objects.create(
            log=f"Timetable uploaded for {start_date.strftime('%d-%B-%y')} to {end_date.strftime('%d-%B-%y')}"
                f"for track {track.name} by admin user {full_name(request.user)}"
        )

    return created_events, existing_events
