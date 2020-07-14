from django.shortcuts import render
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from django.views.generic import ListView
from django.utils import timezone

from booking.models import Event, Track, DropInBlockConfig, CourseBlockConfig

from braces.views import LoginRequiredMixin


class EventAdminListView(LoginRequiredMixin, ListView):

    model = Event
    template_name = "studioadmin/events.html"

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(start__gte=timezone.now().date()).order_by("start")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_events = self.get_queryset()

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
                track_events.append(track_obj)
        context['track_events'] = track_events
        return context


class RegisterListView(EventAdminListView):
    template_name = "studioadmin/registers.html"


def ajax_toggle_event_visible(request, event_id):
    event = Event.objects.get(id=event_id)
    event.show_on_site = not event.show_on_site
    event.save()

    return render(request, "studioadmin/includes/ajax_toggle_event_visible_btn.html", {"event": event})


# @login_required
# @is_instructor_or_staff
def register_view(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    # status_choice = request.GET.get('status_choice', 'OPEN')
    # if status_choice == 'ALL':
    #     bookings = event.bookings.all().order_by('date_booked')
    # else:
    #     bookings = event.bookings.filter(status=status_choice).order_by('date_booked')
    #
    # status_filter = StatusFilter(initial={'status_choice': status_choice})
    bookings = event.bookings.all().order_by('date_booked')
    template = 'studioadmin/register.html'

    if event.course:
        available_block_config = CourseBlockConfig.objects.filter(course_type=event.course.course_type).exists()
    else:
        available_block_config = DropInBlockConfig.objects.filter(event_type=event.event_type).exists()

    return TemplateResponse(
        request, template, {
            'event': event, 'bookings': bookings, 'status_filter': status_filter,
            'can_add_more': event.spaces_left > 0,
            # 'status_choice': status_choice,
            'available_block_type': available_block_type,
        }
    )