from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404, render, HttpResponseRedirect
from django.views.generic import ListView
from django.utils import timezone
from django.urls import reverse

from braces.views import LoginRequiredMixin

from activitylog.models import ActivityLog
from booking.email_helpers import send_bcc_emails
from booking.models import Booking, Event, Track


from .utils import is_instructor_or_staff, staff_required, StaffUserMixin, InstructorOrStaffUserMixin


class BaseEventAdminListView(ListView):

    model = Event

    def get_queryset(self):
        queryset = super().get_queryset()
        start_of_today = timezone.now().replace(hour=0, minute=0, microsecond=0)
        return queryset.filter(start__gte=start_of_today).order_by("start")

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


class EventAdminListView(LoginRequiredMixin, StaffUserMixin, BaseEventAdminListView):
    template_name = "studioadmin/events.html"


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

    open_bookings = Booking.objects.filter(event=event, status='OPEN', no_show=False)
    no_shows = Booking.objects.filter(event=event, status='OPEN', no_show=True)

    # Course event: cancel all bookings, no-show or open, since a course block is for the whole
    # course, not a single event. We assume another event will be added to the course to compensate.
    if event_is_part_of_course:
        bookings_to_cancel = list(open_bookings) + list(no_shows)
    else:
        bookings_to_cancel = list(open_bookings)

    if request.method == 'POST':
        if 'confirm' in request.POST:
            additional_message = request.POST["additional_message"]
            event.cancelled = True
            if event_is_part_of_course:
                event.course = None
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
                booking.user.childuserprofile.parent_user_profile.user.email if hasattr(booking.user, "childuserprofile")
                else booking.user.email for booking in bookings_to_cancel
            ]
            send_bcc_emails(
                ctx,
                user_emails,
                subject=f'{settings.ACCOUNT_EMAIL_SUBJECT_PREFIX} {event} has been cancelled',
                template_without_ext="studioadmin/email/event_cancelled"
            )

            if bookings_to_cancel:
                message = 'Bookings cancelled and notification emails sent to students'
            else:
                message = 'No open bookings'
            course_message = " and removed from course" if event_is_part_of_course else ""
            messages.success(request, f'Event cancelled{course_message}; {message}')
            ActivityLog.objects.create(log=f"Event {event} cancelled by admin user {request.user}; {message}")

        return HttpResponseRedirect(reverse('studioadmin:events'))

    context = {
        'event': event,
        'event_is_part_of_course': event_is_part_of_course,
        'bookings_to_cancel': bookings_to_cancel,
        'no_shows': no_shows,
    }
    return TemplateResponse(request, 'studioadmin/cancel_event.html', context)
