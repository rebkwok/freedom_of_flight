from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, HttpResponseRedirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from django.views.generic import ListView

from studioadmin.views.utils import get_current_courses

from activitylog.models import ActivityLog

from ..forms import AvailableUsersForm
from ..models import Course, Track
from ..utils import get_view_as_user, get_user_course_booking_info, full_name
from .button_utils import course_list_button_info
from .views_utils import DataPolicyAgreementRequiredMixin, CleanUpBlocksMixin


class CourseListView(CleanUpBlocksMixin, DataPolicyAgreementRequiredMixin, ListView):

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

            context["button_options"] = {
                course.id: course_list_button_info(view_as_user, course, user_course_booking_info[course.id]) 
                for course in self.object_list
            }
            context["user_course_booking_info"] = user_course_booking_info
            context["available_users_form"] = AvailableUsersForm(request=self.request, view_as_user=view_as_user)
        return context


@login_required
@require_http_methods(["POST"])
def unenroll(request):
    course_user = get_object_or_404(User, pk=request.POST["user_id"])
    course = get_object_or_404(Course, pk=request.POST["course_id"])

    course_bookings = course_user.bookings.filter(event__course__id=course.id)
    if not course_bookings:
        messages.error(request, f"{full_name(course_user)} is not booked on this course, cannot unenroll")
    else:
        course_bookings.update(status="CANCELLED", no_show=False, block=None)
        ActivityLog.objects.create(
            log=f"User {full_name(course_user)} unenrolled from course {course} by user {request.user}"
        )
        messages.success(request, f"{full_name(course_user)} unenrolled from {course}")
    return HttpResponseRedirect(reverse("booking:course_events", args=(course.slug,)))