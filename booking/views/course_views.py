from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, HttpResponseRedirect, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.views.generic import ListView, DetailView

from studioadmin.views.utils import get_current_courses

from ..forms import AvailableUsersForm
from ..models import Course, Event, Track
from ..utils import get_view_as_user, get_user_course_booking_info
from .views_utils import DataPolicyAgreementRequiredMixin


class CourseListView(DataPolicyAgreementRequiredMixin, ListView):

    model = Course
    context_object_name = 'courses'
    template_name = 'booking/courses.html'
    paginate_by = 20

    def post(self, request, *args, **kwargs):
        view_as_user = request.POST.get("view_as_user")
        self.request.session["user_id"] = int(view_as_user)
        return HttpResponseRedirect(reverse("booking:courses", args=(self.kwargs["track"],)))

    def get_queryset(self):
        track = get_object_or_404(Track, slug=self.kwargs["track"])
        queryset = super().get_queryset().filter(event_type__track=track, cancelled=False, show_on_site=True)
        return get_current_courses(queryset)

    def get_context_data(self, **kwargs):
        # Call the base implementation first to get a context
        context = super().get_context_data(**kwargs)
        track = Track.objects.get(slug=self.kwargs["track"])
        context['title'] = track.name
        context['track'] = track

        if self.request.user.is_authenticated:
            # Add in the booked_events
            # All user bookings for events in this list view (may be cancelled)
            view_as_user = get_view_as_user(self.request)
            user_course_booking_info = {
                course.id: get_user_course_booking_info(view_as_user, course) for course in self.object_list
            }
            context["user_course_booking_info"] = user_course_booking_info
            context["available_users_form"] = AvailableUsersForm(request=self.request, view_as_user=view_as_user)
        return context
