from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Count
from django.utils import timezone
from django.shortcuts import get_object_or_404, HttpResponseRedirect
from django.views.generic import ListView
from django.urls import reverse

from braces.views import LoginRequiredMixin

from ..forms import AvailableUsersForm
from ..models import Booking, Event, WaitingListUser
from ..utils import get_view_as_user
from .views_utils import DataPolicyAgreementRequiredMixin


class BookingListView(DataPolicyAgreementRequiredMixin, LoginRequiredMixin, ListView):

    model = Event
    context_object_name = 'bookings'
    template_name = 'booking/bookings.html'

    def post(self, request, *args, **kwargs):
        view_as_user = request.POST.get("view_as_user")
        self.request.session["user_id"] = view_as_user
        return HttpResponseRedirect(reverse("booking:bookings"))

    def get_queryset(self):
        cutoff_time = timezone.now() - timedelta(minutes=10)
        view_as_user = get_view_as_user(self.request)
        return Booking.objects.filter(user=view_as_user, event__start__gt=cutoff_time).order_by('event__start__date', 'event__start__time')

    def get_context_data(self, **kwargs):
        # Call the base implementation first to get a context
        context = super().get_context_data(**kwargs)
        all_bookings = self.get_queryset()

        page = self.request.GET.get('page', 1)
        all_paginator = Paginator(all_bookings, 20)
        page_bookings = all_paginator.get_page(page)
        booking_ids_by_date = page_bookings.object_list.values('event__start__date').annotate(count=Count('id')).values('event__start__date', 'id')
        bookings_by_date = {}
        for booking_info in booking_ids_by_date:
            bookings_by_date.setdefault(booking_info["event__start__date"], []).append(all_bookings.get(id=booking_info["id"]))
        context["page_bookings"] = page_bookings
        context["bookings_by_date"] = bookings_by_date
        context["available_users_form"] = AvailableUsersForm(request=self.request, view_as_user=get_view_as_user(self.request))

        return context