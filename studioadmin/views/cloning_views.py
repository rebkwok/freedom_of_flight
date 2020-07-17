from datetime import datetime, timedelta
import logging
import pytz

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404, HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone

from activitylog.models import ActivityLog
from booking.models import Event
from common.utils import full_name

from ..forms import CloneEventWeeklyForm, CloneEventDailyIntervalsForm, CloneSingleEventForm
from .utils import staff_required


logger = logging.getLogger(__name__)


@login_required
@staff_required
def clone_event(request, event_slug):
    event = get_object_or_404(Event, slug=event_slug)
    weekly_form = CloneEventWeeklyForm(
        event=event,
        initial={
            "recurring_weekly_weekdays": event.start.weekday(),
            "recurring_weekly_time": event.start.time(),
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


def get_next_start(start, weekday, selected_time):
    start_weekday = start.weekday()
    # Get the beginning of the start week
    start_week_monday = 0 - start_weekday
    # Get the days until the weekday we want
    days_until_target_weekday = start_week_monday + weekday
    # If it's negative, it's already passed this week, so we need next week
    if days_until_target_weekday < 0:
        days_until_target_weekday += 7
    next_start = datetime.combine(start, selected_time) + timedelta(days_until_target_weekday)
    next_start = next_start.replace(tzinfo=timezone.utc)
    return next_start


def clone_event_weekly(request, event, weekdays, start, end, time):
    # turn the start and end dates into datetimes
    start_date = datetime.combine(start, datetime.min.time())
    end_date = datetime.combine(end, datetime.max.time())
    # Turn both dates into UK timezone aware
    end_date = end_date.replace(tzinfo=timezone.utc)
    start_date = start_date.replace(tzinfo=timezone.utc)
    cloned_events = []
    existing_dates = []
    for weekday in weekdays:
        weekday = int(weekday)
        event_start = get_next_start(start_date, weekday, time)
        while event_start <= end_date:
            if Event.objects.filter(name=event.name, start=event_start, event_type=event.event_type):
                existing_dates.append(event_start)
            else:
                cloned_event = base_clone(event)
                cloned_event.start = event_start
                cloned_event.save()
                cloned_events.append(cloned_event)
            event_start = get_next_start(event_start + timedelta(7), weekday, time)
    if cloned_events:
        messages.success(
            request,
            f"{event.event_type.label.title()} was cloned to the following dates: "
            f"{', '.join([cloned.start.strftime('%d-%b-%Y, %H:%M') for cloned in cloned_events])}"
        )
    else:
        messages.warning(request, "Nothing to clone")

    if existing_dates:
        messages.error(
            request,
            f"An {event.event_type.label.title()} with this name and start already exists for the following dates and "
            f"was not cloned: {', '.join([existing_date.strftime('%d-%b-%Y, %H:%M') for existing_date in existing_dates])}"
        )


def clone_event_daily(request, event, target_date, start_time, end_time, interval):
    # turn the start dates into datetime and make it tz aware
    start_datetime = datetime.combine(target_date, start_time)
    start_datetime = start_datetime.replace(tzinfo=timezone.utc)
    end_datetime = datetime.combine(target_date, end_time)
    end_datetime = end_datetime.replace(tzinfo=timezone.utc)
    interval = int(interval)
    cloned_times = []
    existing_times = []

    event_start = start_datetime
    while event_start <= end_datetime:
        if Event.objects.filter(name=event.name, start=event_start, event_type=event.event_type):
            existing_times.append(event_start)
        else:
            cloned_event = base_clone(event)
            cloned_event.start = event_start
            cloned_event.save()
            cloned_times.append(event_start)
        event_start = event_start + timedelta(minutes=interval)

    import ipdb; ipdb.set_trace()
    if cloned_times:
        messages.success(
            request,
            f"{event.event_type.label.title()} was cloned to the following times on {target_date.strftime('%d-%b-%Y')}: "
            f"{', '.join([cloned_time.strftime('%H:%M') for cloned_time in cloned_times])}"
        )
    else:
        messages.warning(request, "Nothing to clone")

    if existing_times:
        messages.error(
            request,
            f"Events with this name and start already exist for the following dates and "
            f"were not cloned: {', '.join([existing_time.strftime('%d-%b-%Y, %H:%M') for existing_time in existing_times])}"
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
            f"{cloned_event.event_type.label.title()} cloned to {cloned_event.start.strftime('%d-%b-%Y, %H:%M')}"
        )
        ActivityLog.objects.create(
            log=f"Event id {event.id} cloned to {cloned_event.id} by admin user {full_name(request.user)}"
        )
