from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, HttpResponseRedirect, render
from django.http import HttpResponseBadRequest, HttpResponse, HttpResponseNotFound
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView


from ..models import Booking, Event, Track, WaitingListUser


def home(request):
    track = Track.get_default()
    return HttpResponseRedirect(reverse("booking:events", args=(track.slug,)))


class EventListView(ListView):

    model = Event
    context_object_name = 'events_by_date'
    template_name = 'booking/events.html'

    def get_queryset(self):
        track = get_object_or_404(Track, slug=self.kwargs["track"])
        cutoff_time = timezone.now() - timedelta(minutes=10)
        return Event.objects.filter(event_type__track=track, start__gt=cutoff_time, show_on_site=True).order_by('start__date', 'start__time')

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
        context['track'] = Track.objects.get(slug=self.kwargs["track"]).name
        if self.request.user.is_authenticated:
            # Add in the booked_events
            # All user bookings for events in this list view (may be cancelled)
            user_bookings = {booking.event.id: booking for booking in self.request.user.bookings.filter(event__id__in=all_events)}
            # Event ids for the open bookings the use has
            booked_event_ids = [
                event_id for event_id, booking in user_bookings.items() if booking.status == "OPEN" and booking.no_show == False
            ]
            waiting_list_event_ids = self.request.user.waitinglists.filter(event__in=all_events).values_list('event__id', flat=True)
            context['user_bookings'] = user_bookings
            context['booked_event_ids'] = booked_event_ids
            context['waiting_list_event_ids'] = waiting_list_event_ids
        return context


class EventDetailView(DetailView):

    model = Event
    context_object_name = 'event'
    template_name = 'booking/event.html'

    def get_object(self):
        return get_object_or_404(Event, slug=self.kwargs['slug'], show_on_site=True)

    def get_context_data(self, **kwargs):
        # Call the base implementation first to get a context
        context = super().get_context_data()
        if self.request.user.is_authenticated:
            booking = Booking.objects.filter(event=self.object, user=self.request.user)
            if booking:
                context["booking"] = booking
            waiting_list = WaitingListUser.objects.filter(event=self.object, user=self.request.user).exists()
            context["on_waiting_list"] = waiting_list
            context["show_video_link"] = self.object.show_video_link

        return context
