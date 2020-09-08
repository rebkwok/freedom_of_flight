from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, HttpResponseRedirect, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.views.generic import ListView, DetailView


from ..forms import AvailableUsersForm, EventNameFilterForm
from ..models import Course, Event, Track
from ..utils import get_view_as_user, has_available_course_block, get_user_booking_info
from .views_utils import DataPolicyAgreementRequiredMixin


def home(request):
    track = Track.get_default()
    if track is None:
        return HttpResponse("No tracks created yet.")
    return HttpResponseRedirect(reverse("booking:events", args=(track.slug,)))


class EventListView(DataPolicyAgreementRequiredMixin, ListView):

    model = Event
    context_object_name = 'events_by_date'
    template_name = 'booking/events.html'

    def post(self, request, *args, **kwargs):
        view_as_user = request.POST.get("view_as_user")
        self.request.session["user_id"] = int(view_as_user)
        return HttpResponseRedirect(reverse("booking:events", args=(self.kwargs["track"],)))

    def get_queryset(self):
        track = get_object_or_404(Track, slug=self.kwargs["track"])
        cutoff_time = timezone.now() - timedelta(minutes=10)
        events = Event.objects.select_related("event_type").filter(
            event_type__track=track, start__gt=cutoff_time, show_on_site=True, cancelled=False
        ).order_by('start__date', 'start__time')
        event_name = self.request.GET.get("event_name")
        if event_name:
            events = events.filter(name__iexact=event_name)
        return events

    def get_title(self):
        return Track.objects.get(slug=self.kwargs["track"]).name

    def get_context_data(self, **kwargs):
        # Call the base implementation first to get a context
        context = super().get_context_data(**kwargs)
        all_events = self.get_queryset()

        page = self.request.GET.get('page', 1)
        all_paginator = Paginator(all_events, 20)
        page_events = all_paginator.get_page(page)
        event_ids_by_date = page_events.object_list.values('start__date').annotate(count=Count('id')).values('start__date', 'id')
        events_by_date = {}
        for event_info in event_ids_by_date:
            events_by_date.setdefault(event_info["start__date"], []).append(all_events.get(id=event_info["id"]))

        context["page_events"] = page_events
        context["events_by_date"] = events_by_date
        context['title'] = self.get_title()

        if "track" in self.kwargs:
            track = Track.objects.get(slug=self.kwargs["track"])
            context['track'] = track
            context["courses_available"] = any(
                [course for course in Course.objects.filter(event_type__track=track, cancelled=False, show_on_site=True)
                 if course.last_event_date and course.last_event_date.date() >= timezone.now().date()]
            )
            event_name = self.request.GET.get("event_name")
            if event_name:
                context["name_filter_form"] = EventNameFilterForm(track=track, initial={"event_name": event_name})
            else:
                context["name_filter_form"] = EventNameFilterForm(track=track)

        if self.request.user.is_authenticated:
            # Add in the booked_events
            # All user bookings for events in this list view (may be cancelled)
            view_as_user = get_view_as_user(self.request)
            user_booking_info = {
                event.id: get_user_booking_info(view_as_user, event) for event in page_events.object_list
            }
            context["user_booking_info"] = user_booking_info
            context["available_users_form"] = AvailableUsersForm(request=self.request, view_as_user=view_as_user)
        return context


class EventDetailView(DataPolicyAgreementRequiredMixin, DetailView):

    model = Event
    context_object_name = 'event'
    template_name = 'booking/event.html'

    def get_object(self):
        return get_object_or_404(Event, slug=self.kwargs['slug'])

    def get_context_data(self, **kwargs):
        # Call the base implementation first to get a context
        context = super().get_context_data()
        if self.request.user.is_authenticated:
            view_as_user = get_view_as_user(self.request)
            booking = view_as_user.bookings.filter(event=self.object, user=view_as_user)
            if booking:
                context["booking"] = booking[0]
        return context


class CourseEventsListView(EventListView):

    def get_title(self):
        return Course.objects.get(slug=self.kwargs["course_slug"]).name

    def post(self, request, *args, **kwargs):
        view_as_user = request.POST.get("view_as_user")
        self.request.session["user_id"] = view_as_user
        return HttpResponseRedirect(reverse("booking:course_events", args=(self.kwargs["course_slug"],)))

    def get_queryset(self):
        course_slug =self.kwargs["course_slug"]
        return Event.objects.filter(course__slug=course_slug).order_by('start__date', 'start__time')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        course = Course.objects.get(slug=self.kwargs["course_slug"])
        context["course"] = course
        if self.request.user.is_authenticated:
            view_as_user = get_view_as_user(self.request)
            context["already_booked"] = view_as_user.bookings.filter(event__course=course, status="OPEN").exists()
            context["has_available_course_block"] = has_available_course_block(view_as_user, course)
        return context
