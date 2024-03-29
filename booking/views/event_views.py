from datetime import timedelta

from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Count
from django.shortcuts import get_object_or_404, HttpResponseRedirect, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.views.generic import ListView, DetailView

from ..forms import AvailableUsersForm, EventNameFilterForm
from ..models import Course, Event, Track, get_active_user_course_block
from ..utils import get_view_as_user, get_user_booking_info
from .button_utils import (
    button_options_events_list, 
    button_options_book_course_button
)
from .views_utils import DataPolicyAgreementRequiredMixin, CleanUpBlocksMixin


def home(request):
    track = Track.get_default()
    if track is None:
        return HttpResponse("No tracks created yet.")
    return HttpResponseRedirect(reverse("booking:events", args=(track.slug,)))


class EventListView(CleanUpBlocksMixin, DataPolicyAgreementRequiredMixin, ListView):

    model = Event
    context_object_name = 'events_by_date'
    template_name = 'booking/events.html'
    _ref_obj = None

    def get_ref_obj(self):
        return get_object_or_404(Track, slug=self.kwargs["track"])

    @property
    def ref_obj(self):
        if self._ref_obj is None:
            self._ref_obj = self.get_ref_obj()
        return self._ref_obj

    def _redirect_url(self):
        return reverse("booking:events", args=(self.kwargs["track"],))

    def post(self, request, *args, **kwargs):
        view_as_user = request.POST.get("view_as_user")
        self.request.session["user_id"] = int(view_as_user)
        return HttpResponseRedirect(self._redirect_url())

    def get_queryset(self):
        cutoff_time = timezone.now() - timedelta(minutes=10)
        events = Event.objects.select_related("event_type").filter(
            event_type__track=self.ref_obj, start__gt=cutoff_time, show_on_site=True, cancelled=False
        ).order_by('start__date', 'start__time', "id")
        event_name = self.request.GET.get("event_name")
        if event_name:
            events = events.filter(name__iexact=event_name)
        return events

    def get_title(self):
        return self.ref_obj.name

    def _get_button_info(self, user, events):
        return {
            event.id: button_options_events_list(user, event) for event in events
        }

    def _extra_context(self, **kwargs):
        all_events = kwargs["all_events"]
        extra_ctx = {
            "track": self.ref_obj,
            "courses_available": all_events.filter(course__show_on_site=True, start__gte=timezone.now()).exists()
        }
        event_name = self.request.GET.get("event_name")
        if event_name:
            extra_ctx["name_filter_form"] = EventNameFilterForm(track=self.ref_obj, initial={
                "event_name": event_name})
        else:
            extra_ctx["name_filter_form"] = EventNameFilterForm(track=self.ref_obj)
        return extra_ctx

    def get_context_data(self, **kwargs):
        # Call the base implementation first to get a context
        context = super().get_context_data(**kwargs)
        all_events = self.get_queryset()

        all_paginator = Paginator(all_events, 10)
        page = self.request.GET.get('page', 1)
        try:
            page = all_paginator.validate_number(page)
        except PageNotAnInteger:
            page = 1
        except EmptyPage:
            page = int(page)
            page = 1 if page < 1 else all_paginator.num_pages
        page_events = all_paginator.get_page(page)
        context["page_obj"] = page_events
        context["page_range"] = all_paginator.get_elided_page_range(number=page, on_each_side=2)
        context['title'] = self.get_title()
        context.update(self._extra_context(all_events=all_events))
        if self.request.user.is_authenticated:
            # Add in the booked_events
            # All user bookings for events in this list view (may be cancelled)
            view_as_user = get_view_as_user(self.request)
            user_booking_info = {
                event.id: get_user_booking_info(view_as_user, event) for event in page_events.object_list
            }
            context["user_booking_info"] = user_booking_info
            context["available_users_form"] = AvailableUsersForm(request=self.request, view_as_user=view_as_user)
            context["button_options"] = self._get_button_info(view_as_user, page_events.object_list)
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
            open_booking = view_as_user.bookings.filter(event=self.object, user=view_as_user, status="OPEN", no_show=False).first()
            context["open_booking"] = open_booking
        return context


class CourseEventsListView(EventListView):

    def get_ref_obj(self):
        return get_object_or_404(Course, slug=self.kwargs["course_slug"])

    def get_title(self):
        return self.ref_obj.name

    def _redirect_url(self):
        return reverse("booking:course_events", args=(self.kwargs["course_slug"],))

    def get_queryset(self):
        course_slug = self.kwargs["course_slug"]
        return Event.objects.filter(course__slug=course_slug).order_by('start__date', 'start__time')

    def _get_button_info(self, user, events):
        return {
            event.id: button_options_events_list(user, event, course=True) for event in events
        }

    def _extra_context(self, **kwargs):
        return {}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        course = self.ref_obj
        context["course"] = course
        if self.request.user.is_authenticated:
            view_as_user = get_view_as_user(self.request)
            context["available_course_block"] = get_active_user_course_block(view_as_user, course)
            context["book_course_button_options"] = button_options_book_course_button(view_as_user, course)
        return context
