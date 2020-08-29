from datetime import datetime

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, QuerySet
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404, render, HttpResponseRedirect
from django.views.generic import ListView, CreateView, UpdateView
from django.utils import timezone
from django.urls import reverse

from braces.views import LoginRequiredMixin

from activitylog.models import ActivityLog
from booking.email_helpers import send_bcc_emails
from booking.models import Booking, Event, Track, EventType

from ..forms import EventCreateUpdateForm
from .utils import is_instructor_or_staff, staff_required, StaffUserMixin, InstructorOrStaffUserMixin


class TrackEventPaginationMixin:
    def paginate_by_date_for_track(self, track_queryset, page):
        track_paginator = Paginator(track_queryset, self.custom_paginate_by)
        page_obj = track_paginator.get_page(page)
        if not isinstance(page_obj.object_list, QuerySet):
            paginated_ids = [event.id for event in page_obj.object_list]
            paginated_events = track_queryset.filter(id__in=paginated_ids)
        else:  # pragma: no cover
            paginated_events = page_obj.object_list
        event_ids_by_date = paginated_events.values('start__date').annotate(count=Count('id')).values('start__date', 'id')
        events_by_date = {}
        for event_info in event_ids_by_date:
            events_by_date.setdefault(event_info["start__date"], []).append(paginated_events.get(id=event_info["id"]))
        return page_obj, events_by_date


class BaseEventAdminListView(TrackEventPaginationMixin, ListView):
    model = Event
    custom_paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset()
        start_of_today = datetime.combine(timezone.now().date(), datetime.min.time(), tzinfo=timezone.utc)
        return queryset.filter(start__gte=start_of_today).order_by("start")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_events = self.get_queryset()
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
        track_events = []

        for i, track in enumerate(tracks):
            track_qs = all_events.filter(event_type__track=track)
            # group by date before pagination
            if track_qs:
                # Don't add the track tab if there are no events to display
                page = 1
                if "tab" in self.request.GET and tab == i:
                    try:
                        page = int(self.request.GET.get('page', 1))
                    except ValueError:
                        pass
                page_obj, events_by_date = self.paginate_by_date_for_track(track_qs, page)
                track_obj = {
                    'index': i,
                    'page_obj': page_obj,
                    'events_by_date': events_by_date,
                    'track': track.name
                }
                track_events.append(track_obj)

                if requested_track and requested_track == track:
                    # we returned here from another view that was on a particular track, we want to set the
                    # tab to that track
                    context["active_tab"] = i

        context['track_events'] = track_events
        return context


class EventAdminListView(LoginRequiredMixin, StaffUserMixin, BaseEventAdminListView):
    template_name = "studioadmin/events.html"


class PastEventAdminListView(EventAdminListView):
    template_name = "studioadmin/events.html"

    def get_queryset(self):
        start_of_today = datetime.combine(timezone.now().date(), datetime.min.time(), tzinfo=timezone.utc)
        return Event.objects.filter(start__lt=start_of_today).order_by("-start")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["past"] = True
        return context


def ajax_toggle_event_visible(request, event_id):
    event = Event.objects.get(id=event_id)
    event.show_on_site = not event.show_on_site
    event.save()

    return render(request, "studioadmin/includes/ajax_toggle_event_visible_btn.html", {"event": event})


@login_required
@staff_required
def cancel_event_view(request, slug):
    event = get_object_or_404(Event, slug=slug)
    event_is_part_of_course = bool(event.course)

    any_bookings = event.bookings.exists()
    open_bookings = event.bookings.filter(status='OPEN', no_show=False)
    no_shows = event.bookings.filter(status='OPEN', no_show=True)

    # Course event: cancel all bookings, no-show or open, since a course block is for the whole
    # course, not a single event. We assume another event will be added to the course to compensate.
    if event_is_part_of_course:
        bookings_to_cancel = list(open_bookings) + list(no_shows)
    else:
        bookings_to_cancel = list(open_bookings)

    if request.method == 'POST':
        if 'confirm' in request.POST:
            if any_bookings:
                additional_message = request.POST["additional_message"]
                event.cancelled = True
                for booking in bookings_to_cancel:
                    booking.block = None
                    booking.status = "CANCELLED"
                    booking.save()
                event.save()

                # send email notification
                ctx = {
                    'host': 'http://{}'.format(request.META.get('HTTP_HOST')),
                    'event': event,
                    'additional_message': additional_message,
                }
                # send emails to manager user if this is a child user booking
                user_emails = [
                    booking.user.manager_user.email if booking.user.manager_user
                    else booking.user.email for booking in bookings_to_cancel
                ]
                send_bcc_emails(
                    ctx,
                    user_emails,
                    subject=f'{settings.ACCOUNT_EMAIL_SUBJECT_PREFIX} {event} has been cancelled',
                    template_without_ext="studioadmin/email/event_cancelled"
                )

                if bookings_to_cancel:
                    message = 'bookings cancelled and notification emails sent to students'
                else:
                    message = 'no open bookings'
                messages.success(request, f'Event cancelled; {message}')
                ActivityLog.objects.create(log=f"Event {event} cancelled by admin user {request.user}; {message}")
            else:
                # no bookings, cancelled or otherwise, we can just delete the event
                event.delete()
                messages.success(request, f'Event deleted')
                ActivityLog.objects.create(log=f"Event {event} deleted by admin user {request.user}")

        return HttpResponseRedirect(reverse('studioadmin:events') + f"?track={event.event_type.track_id}")

    context = {
        'event': event,
        'event_is_part_of_course': event_is_part_of_course,
        'any_bookings': any_bookings,
        'bookings_to_cancel': bookings_to_cancel,
        'no_shows': no_shows,
    }
    return TemplateResponse(request, 'studioadmin/cancel_event.html', context)


@login_required
@staff_required
def event_create_choice_view(request):
    event_types = EventType.objects.all()
    return render(request, "studioadmin/event_create_choose_event_type.html", {"event_types": event_types})


class EventCreateUpdateMixin:
    template_name = "studioadmin/event_create_update.html"
    model = Event
    form_class = EventCreateUpdateForm

    def form_valid(self, form):
        form.save()
        return HttpResponseRedirect(self.get_success_url(form.event_type.track_id))

    def get_success_url(self, track_id):
        return reverse('studioadmin:events') + f"?track={track_id}"


class EventCreateView(LoginRequiredMixin, StaffUserMixin, EventCreateUpdateMixin, CreateView):

    def get_form_kwargs(self, **kwargs):
        form_kwargs = super().get_form_kwargs(**kwargs)
        form_kwargs["event_type"] = EventType.objects.get(id=self.kwargs["event_type_id"])
        return form_kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["creating"] = True
        context["event_type"] = EventType.objects.get(id=self.kwargs["event_type_id"])
        return context


class EventUpdateView(LoginRequiredMixin, StaffUserMixin, EventCreateUpdateMixin, UpdateView):

    def get_form_kwargs(self, **kwargs):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["event_type"] = self.get_object().event_type
        return form_kwargs
