from django.conf import settings
from django.contrib import messages

from django.shortcuts import get_object_or_404, HttpResponseRedirect, render
from django.http import HttpResponseBadRequest, HttpResponse, HttpResponseNotFound
from django.template.loader import get_template
from django.urls import reverse

from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView

from braces.views import LoginRequiredMixin

from activitylog.models import ActivityLog
from ..email_helpers import send_waiting_list_email, send_user_and_studio_emails
from ..models import Booking, Event, WaitingListUser
from ..utils import booked_within_allowed_time, has_available_block, get_active_user_block
from .views_utils import DataPolicyAgreementRequiredMixin, DisclaimerRequiredMixin


class BookingDeleteView(
    DataPolicyAgreementRequiredMixin, DisclaimerRequiredMixin, LoginRequiredMixin,
    DeleteView
):
    model = Booking
    template_name = 'booking/cancel_booking.html'
    success_message = 'Booking cancelled for {}.'

    def dispatch(self, request, *args, **kwargs):
        booking = get_object_or_404(Booking, pk=self.kwargs['pk'])
        if booking.status == 'CANCELLED':
            # redirect if already cancelled
            return HttpResponseRedirect(reverse('booking:already_cancelled', args=[booking.id]))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["booked_within_allowed_time"] = booked_within_allowed_time(context["booking"])
        return context

    def delete(self, request, *args, **kwargs):
        booking = self.get_object()
        event = booking.event
        event_was_full = not event.course and event.spaces_left == 0

        if not event.course and not (
            event.can_cancel and not booked_within_allowed_time(booking)
        ):
            # course event or no cancellation allowed/too late - set to no-show
            # Note: this should always be the case, since we only come here from the
            # ajax view if cancellation isn't allowed, but we check just in case
            booking.no_show = True
        else:
            booking.status = "CANCELLED"
            booking.block = None
        booking.save()

        # send email to user
        host = f"http://{self.request.META.get('HTTP_HOST')}"
        ctx = {
            'host': host,
            'booking': booking,
            'event': event,
            'requested_action': "cancelled",
            'date': event.start.strftime('%A %d %B'),
            'time': event.start.strftime('%I:%M %p'),
          }
        subjects = {"user": f"Booking for {event} cancelled"}
        send_user_and_studio_emails(ctx, self.request.user, False, subjects, "booking_created_or_updated")

        messages.success(self.request, self.success_message.format(booking.event))
        ActivityLog.objects.create(
            log=f'Booking id {booking.id} for event {event} was cancelled by user {self.request.user.username}'
        )

        # if applicable, email users on waiting list
        if event_was_full:
            waiting_list_users = WaitingListUser.objects.filter(event=event)
            send_waiting_list_email(event, waiting_list_users, host)

        next = self.request.GET.get("next")
        url = self.get_success_url(next, event)
        return HttpResponseRedirect(url)

    def get_success_url(self, next, event):
        if next:
            return reverse('booking:{}'.format(next))
        return reverse('booking:events', args=(event.event_type.track.slug,))


class BookingCreateView(
    DataPolicyAgreementRequiredMixin, DisclaimerRequiredMixin, LoginRequiredMixin,
    CreateView
):
    model = Booking
    template_name = 'booking/create_booking.html'
    success_message = 'Booked for {}.'
    fields = ("event",)

    def dispatch(self, request, *args, **kwargs):
        self.event = get_object_or_404(Event, slug=kwargs['event_slug'])

        # redirect if event cancelled
        if self.event.cancelled:
            return HttpResponseRedirect(reverse('booking:permission_denied'))

        # redirect if part of course
        if self.event.course:
            return HttpResponseRedirect(reverse('booking:course_events', args=(self.event.course.slug,)))

        # redirect if already booked
        already_booked = self.request.user.bookings.filter(event=self.event, status="OPEN", no_show=False).exists()
        if already_booked:
            return HttpResponseRedirect(reverse('booking:duplicate_booking', args=[self.event.slug]))

        # redirect if fully booked
        if self.event.full:
            return HttpResponseRedirect(reverse('booking:fully_booked', args=[self.event.slug]))

        # redirect if user doesn't have block
        if not has_available_block(self.request.user, self.event):
            # url = reverse('booking:block_create', args=(self.event.event_type,)
            return HttpResponseRedirect(url)

        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {"event": self.event.pk}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['event'] = self.event
        return context

    def form_valid(self, form):
        booking = form.save(commit=False)
        try:
            booking = Booking.objects.get(user=self.request.user, event=self.event)
            action = "reopened"
        except Booking.DoesNotExist:
            action = "created"
        booking.status = "OPEN"
        booking.no_show = False
        booking.user = self.request.user
        booking.block = get_active_user_block(self.request.user, booking.event)
        booking.save()
        ActivityLog.objects.create(
            log=f'Booking {booking.id} {action} for "{booking.event}" by user {booking.user.username}'
        )

        # email context
        ctx = {
          'host': 'http://{}'.format(self.request.META.get('HTTP_HOST')),
          'booking': booking,
          'requested_action': action,
          'event': booking.event,
          'date': booking.event.start.strftime('%A %d %B'),
          'time': booking.event.start.strftime('%H:%M'),
        }

        subjects = {
            "user": f"Booking for {booking.event} {action}",
            "studio": f"{self.request.user.first_name} {self.request.user.last_name} has just booked for {booking.event}"
        }

        # send emails
        send_user_and_studio_emails(
            ctx, self.request.user, booking.event.event_type.email_studio_when_booked, subjects, "booking_created_or_updated"
        )

        messages.success(self.request, self.success_message.format(self.event))

        try:
            waiting_list_user = WaitingListUser.objects.get(
                user=booking.user, event=booking.event
            )
            waiting_list_user.delete()
            ActivityLog.objects.create(log=f'User {booking.user.username} removed from waiting list for {self.event}')
        except WaitingListUser.DoesNotExist:
            pass

        return HttpResponseRedirect(reverse('booking:events', args=(booking.event.event_type.track.slug,)))


def already_cancelled(request, pk):
    booking = get_object_or_404(Booking, pk=pk)
    context = {'booking': booking}
    return render(request, 'booking/already_cancelled.html', context)