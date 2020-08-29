from datetime import datetime, timedelta
import logging

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404, HttpResponseRedirect
from django.urls import reverse

from delorean import Delorean, stops, WEEKLY
from dateutil.rrule import MINUTELY

from activitylog.models import ActivityLog
from booking.models import Event
from common.utils import full_name
from timetable.models import TimetableSession

from ..forms import CloneEventWeeklyForm, CloneEventDailyIntervalsForm, CloneSingleEventForm, CloneTimetableSessionForm
from .utils import staff_required


logger = logging.getLogger(__name__)


@login_required
@staff_required
def clone_event(request, event_slug):
    event = get_object_or_404(Event, slug=event_slug)
    delorean_time_in_uk = Delorean(event.start)
    delorean_time_in_uk.shift("Europe/London")
    weekly_form = CloneEventWeeklyForm(
        event=event,
        initial={
            "recurring_weekly_weekdays": [event.start.weekday()],
            "recurring_weekly_time": delorean_time_in_uk.datetime.time(),
        }
    )
    daily_form = CloneEventDailyIntervalsForm()
    single_form = CloneSingleEventForm(
        initial={"recurring_once_datetime": event.start + timedelta(days=7)}
    )
    if request.method == "POST":
        # Determine which form was submitted
        if "Clone weekly recurring" in request.POST["submit"]:
            weekly_form = CloneEventWeeklyForm(request.POST, event=event)
            form_valid = weekly_form.is_valid()
            validated_form = weekly_form
        elif request.POST["submit"] == "Clone at recurring intervals":
            daily_form = CloneEventDailyIntervalsForm(request.POST)
            form_valid = daily_form.is_valid()
            validated_form = daily_form
        elif request.POST["submit"] == "Clone once":
            single_form = CloneSingleEventForm(request.POST)
            form_valid = single_form.is_valid()
            validated_form = single_form
        else:
            form_valid = False
            validated_form = None

        # check the submitted form is valid and create the requested events
        # redirect to events page with the correct track_id query param
        if form_valid:
            if isinstance(validated_form, CloneEventWeeklyForm):
                weekdays = validated_form.cleaned_data["recurring_weekly_weekdays"]
                start = validated_form.cleaned_data["recurring_weekly_start"]
                end = validated_form.cleaned_data["recurring_weekly_end"]
                time = validated_form.cleaned_data["recurring_weekly_time"]
                clone_event_weekly(request, event, weekdays, start, end, time)
            elif isinstance(validated_form, CloneEventDailyIntervalsForm):
                target_date = validated_form.cleaned_data["recurring_daily_date"]
                start_time = validated_form.cleaned_data["recurring_daily_starttime"]
                end_time = validated_form.cleaned_data["recurring_daily_endtime"]
                interval = validated_form.cleaned_data["recurring_daily_interval"]
                clone_event_daily(request, event, target_date, start_time, end_time, interval)
            elif isinstance(validated_form, CloneSingleEventForm):
                clone_single_event(request, event, validated_form.cleaned_data["recurring_once_datetime"])
            return HttpResponseRedirect(reverse("studioadmin:events") + f"?track={event.event_type.track_id}")

    return TemplateResponse(
        request, "studioadmin/clone_event.html",
        {"event": event, "weekly_form": weekly_form, "daily_form": daily_form, "single_form": single_form})


def base_clone(event):
    # copy the event
    cloned_event = event
    cloned_event.id = None
    # set defaults for cloned event
    cloned_event.slug = None
    cloned_event.cancelled = False
    cloned_event.show_on_site = False
    cloned_event.course = None
    return cloned_event


def clone_event_weekly(request, event, weekdays, start, end, time):
    # turn the start and end dates into datetimes
    start_datetime = datetime.combine(start, time)
    end_datetime = datetime.combine(end, datetime.max.time())

    next_weekday_methods = {
        "0": "next_monday",
        "1": "next_tuesday",
        "2": "next_wednesday",
        "3": "next_thursday",
        "4": "next_friday",
        "5": "next_saturday",
        "6": "next_sunday",

    }
    all_datetimes_to_upload = []
    for weekday in weekdays:
        if int(weekday) != start_datetime.weekday():
            weekday_start = getattr(Delorean(start_datetime, timezone="UTC"), next_weekday_methods[weekday])()
            weekday_start = weekday_start.naive  # dates for stops need to be naive
        else:
            weekday_start = start_datetime
        # The literal entered time from the form is naive, and is assumed to be in UK time
        # Create the delorean stops in Europe/London and then convert to UTC for saving in the db
        weekly_stops = stops(start=weekday_start, stop=end_datetime, freq=WEEKLY, timezone="Europe/London")
        weekly_stops_in_utc = [stop.shift("UTC") for stop in weekly_stops]
        all_datetimes_to_upload.extend(weekly_stops_in_utc)

    cloned_events = []
    existing_dates = []

    for datetime_to_upload in all_datetimes_to_upload:
        if Event.objects.filter(name=event.name, start=datetime_to_upload.datetime, event_type=event.event_type):
            existing_dates.append(datetime_to_upload)
        else:
            cloned_event = base_clone(event)
            cloned_event.start = datetime_to_upload.datetime
            cloned_event.save()
            cloned_events.append(cloned_event)

    if cloned_events:
        # Shift the dates back to UK time for string formatting
        messages.success(
            request,
            f"{event.event_type.label.title()} was cloned to the following dates: "
            f"{', '.join([Delorean(cloned.start).shift('Europe/London').format_datetime('d MMM y, HH:mm') for cloned in cloned_events])}"
        )
        ActivityLog.objects.create(
            log=f"Event id {event.id} cloned to {', '.join([str(cloned.id) for cloned in cloned_events])} "
                f"by admin user {full_name(request.user)}"
        )
    else:
        messages.warning(request, "Nothing to clone")

    if existing_dates:
        # Shift the dates back to UK time for string formatting
        messages.error(
            request,
            f"{event.event_type.pluralized_label.title()} with this name already exist for the following dates/times and "
            f"were not cloned: "
            f"{', '.join([existing_date.shift('Europe/London').format_datetime('d MMM y, HH:mm') for existing_date in existing_dates])}"
        )


def clone_event_daily(request, event, target_date, start_time, end_time, interval):
    # turn the start and end dates into datetimes
    start_datetime = datetime.combine(target_date, start_time)
    end_datetime = datetime.combine(target_date, end_time)

    # The literal entered time from the form is naive, and is assumed to be in UK time
    # Create the delorean stops in Europe/London and then convert to UTC for saving in the db
    time_stops = stops(
        start=start_datetime, stop=end_datetime, freq=MINUTELY, interval=interval, timezone="Europe/London"
    )
    datetimes_to_upload = [stop.shift("UTC") for stop in time_stops]
    cloned_times = []
    existing_times = []

    for datetime_to_upload in datetimes_to_upload:
        if Event.objects.filter(name=event.name, start=datetime_to_upload.datetime, event_type=event.event_type):
            existing_times.append(datetime_to_upload)
        else:
            cloned_event = base_clone(event)
            cloned_event.start = datetime_to_upload.datetime
            cloned_event.save()
            cloned_times.append(datetime_to_upload)

    if cloned_times:
        # Shift the times back to UK time for string formatting messages to user
        messages.success(
            request,
            f"{event.event_type.label.title()} was cloned to the following times on {target_date.strftime('%-d %b %Y')}: "
            f"{', '.join([cloned_time.shift('Europe/London').format_datetime('HH:mm') for cloned_time in cloned_times])}"
        )
        ActivityLog.objects.create(
            log=f"Event id {event.id} cloned to {', '.join([cloned_time.format_datetime('HH:mm') for cloned_time in cloned_times])} (UTC)"
                f"on {target_date.strftime('%-d %b %Y')} by admin user {full_name(request.user)}"
        )
    else:  # pragma: no cover
        # This is here as a catchall, but we should never get here. The start of the range is always a valid cloning
        # time, so either there's an existing event that we report on, or we clone
        messages.warning(request, "Nothing to clone")

    if existing_times:
        # Shift the times back to UK time for string formatting messages to user
        messages.error(
            request,
            f"{event.event_type.pluralized_label.title()} with this name already exist on {target_date.strftime('%-d %b %Y')} at these times and "
            f"were not cloned: {', '.join([existing_time.shift('Europe/London').format_datetime('HH:mm') for existing_time in existing_times])}"
        )


def clone_single_event(request, event, start_datetime):
    if Event.objects.filter(name=event.name, start=start_datetime, event_type=event.event_type):
        messages.error(
            request,
            f"{event.event_type.label.title()} not cloned; a duplicate with this name and start "
            f"already exists."
        )
    else:
        cloned_event = base_clone(event)
        # set the start date
        cloned_event.start = start_datetime
        cloned_event.save()
        messages.success(
            request,
            f"{cloned_event.event_type.label.title()} cloned to {cloned_event.start.strftime('%e %b %Y, %H:%M')}"
        )
        ActivityLog.objects.create(
            log=f"Event id {event.id} cloned to {cloned_event.id} by admin user {full_name(request.user)}"
        )


@login_required
@staff_required
def clone_timetable_session_view(request, session_id):
    timetable_session = get_object_or_404(TimetableSession, pk=session_id)
    form = CloneTimetableSessionForm(
        initial={
            "name": timetable_session.name,
        }
    )
    if request.method == "POST":
        # Determine which form was submitted
        form = CloneTimetableSessionForm(request.POST)

        # check the submitted form is valid and create the requested events
        # redirect to timetable page with the correct track_id query param
        if form.is_valid():
            days = form.cleaned_data["days"]
            time = form.cleaned_data["time"]
            name = form.cleaned_data["name"]
            clone_timetable_session(request, timetable_session, days, time, name)
            return HttpResponseRedirect(reverse("studioadmin:timetable") + f"?track={timetable_session.event_type.track_id}")

    return TemplateResponse(
        request, "studioadmin/clone_timetable_session.html", {"timetable_session": timetable_session, "form": form}
    )


def clone_timetable_session(request, timetable_session, days, time, name):
    existing = []
    cloned = []
    name = name or timetable_session.name
    for day in days:
        if TimetableSession.objects.filter(
                name=name, day=day, time=time, event_type=timetable_session.event_type
        ):
            existing.append(dict(TimetableSession.DAY_CHOICES)[day])

        else:
            cloned_session = timetable_session
            cloned_session.id = None
            # set the day, time and name
            cloned_session.day = day
            cloned_session.time = time
            cloned_session.name = name
            cloned_session.save()
            cloned.append(cloned_session)

    if cloned:
        messages.success(
            request,
            f"{timetable_session.event_type.label.title()} was cloned to {cloned_session.name} on "
            f"{', '.join([cloned_session.get_day_name() for cloned_session in cloned])}, {time.strftime('%H:%M')}"
        )
        ActivityLog.objects.create(
            log=f"Timetable session '{timetable_session.name}' cloned by admin user {full_name(request.user)}"
        )
    if existing:
        messages.error(
            request,
            f"Session with name {timetable_session.name} at {timetable_session.time.strftime('%H:%M')} already exists "
            f"for the requested day(s) ({', '.join(existing)})."
        )

