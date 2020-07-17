from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django import forms
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404, render, HttpResponseRedirect
from django.views.generic import ListView, CreateView, UpdateView
from django.utils import timezone
from django.urls import reverse

from braces.views import LoginRequiredMixin

from activitylog.models import ActivityLog
from booking.email_helpers import send_bcc_emails
from booking.models import Booking, Course, Event, Track, EventType, CourseType

from ..forms import CourseCreateForm, CourseUpdateForm
from .utils import is_instructor_or_staff, staff_required, StaffUserMixin, InstructorOrStaffUserMixin


class CourseAdminListView(LoginRequiredMixin, StaffUserMixin, ListView):
    template_name = "studioadmin/courses.html"
    model = Course
    context_object_name = "courses"

    def _include_course(self, course, start_of_today):
        if course.last_event_date is None:
            return True
        else:
            return course.last_event_date >= start_of_today

    def get_queryset(self):
        queryset = super().get_queryset()
        start_of_today = timezone.now().replace(hour=0, minute=0, microsecond=0)
        # Get the courses that have at least one event in the future, or have no events yet
        return [course for course in queryset if self._include_course(course, start_of_today)]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_courses = self.get_queryset()

        track_id = self.request.GET.get('track')
        requested_track = None
        if track_id:
            try:
                requested_track = Track.objects.get(id=track_id)
            except Track.DoesNotExist:
                pass

        # paginate each queryset
        tab = self.request.GET.get('tab', 0)
        try:
            tab = int(tab)
        except ValueError:  # value error if tab is not an integer, default to 0
            tab = 0

        context['tab'] = str(tab)

        tracks = Track.objects.all()
        track_courses = []
        for i, track in enumerate(tracks):
            track_qs = [course for course in all_courses if course.course_type.event_type.track == track]
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
                track_courses.append(track_obj)

                if requested_track and requested_track == track:
                    # we returned here from another view that was on a particular track, we want to set the
                    # tab to that track
                    context["active_tab"] = i

        context['track_courses'] = track_courses
        return context


def ajax_toggle_course_visible(request, course_id):
    course = Course.objects.get(id=course_id)
    course.show_on_site = not course.show_on_site
    course.save()

    return render(request, "studioadmin/includes/ajax_toggle_course_visible_btn.html", {"course": course})


@login_required
@staff_required
def cancel_course_view(request, slug):
    course = get_object_or_404(Course, slug=slug)
    bookings_to_cancel = Booking.objects.filter(event__in=course.events.all())
    bookings_to_cancel_users = bookings_to_cancel.distinct("user")
    if request.method == 'POST':
        if 'confirm' in request.POST:
            additional_message = request.POST["additional_message"]
            course.cancelled = True
            for event in course.events.all():
                event.cancelled = True
                event.save()
            for booking in bookings_to_cancel:
                booking.block = None
                booking.status = "CANCELLED"
                booking.save()
            course.save()

            # send email notification
            ctx = {
                'host': 'http://{}'.format(request.META.get('HTTP_HOST')),
                'course': course,
                'additional_message': additional_message,
            }
            # send emails to manager user if this is a child user booking
            user_emails = {
                booking.user.childuserprofile.parent_user_profile.user.email if hasattr(booking.user, "childuserprofile")
                else booking.user.email for booking in bookings_to_cancel
            }
            send_bcc_emails(
                ctx,
                user_emails,
                subject=f'{settings.ACCOUNT_EMAIL_SUBJECT_PREFIX} The course {course.name} has been cancelled',
                template_without_ext="studioadmin/email/course_cancelled"
            )

            if bookings_to_cancel:
                message = 'bookings cancelled and notification emails sent to students'
            else:
                message = 'no open bookings'
            messages.success(request, f'Course and all associated events cancelled; {message}')
            ActivityLog.objects.create(log=f"Course {course} cancelled by admin user {request.user}; {message}")

        return HttpResponseRedirect(reverse('studioadmin:events') + f"?track={course.course_type.event_type.track_id}")

    context = {
        'course': course,
        'bookings_to_cancel_users': bookings_to_cancel_users,
    }
    return TemplateResponse(request, 'studioadmin/cancel_course.html', context)


@login_required
@staff_required
def course_create_choice_view(request):
    course_types = CourseType.objects.all()
    return render(request, "studioadmin/course_create_choose_course_type.html", {"course_types": course_types})


class CourseCreateUpdateMixin:
    template_name = "studioadmin/course_create_update.html"
    model = Course

    def form_valid(self, form):
        course = form.save()
        event_ids = form.cleaned_data["events"]
        events = Event.objects.filter(id__in=event_ids)
        for event in events:
            event.course = course
            event.cancelled = course.cancelled
            event.save()
        return HttpResponseRedirect(self.get_success_url(course.course_type.event_type.track_id))

    def get_success_url(self, track_id):
        return reverse('studioadmin:courses') + f"?track={track_id}"


class CourseCreateView(LoginRequiredMixin, StaffUserMixin, CourseCreateUpdateMixin, CreateView):

    form_class = CourseCreateForm

    def get_form_kwargs(self, **kwargs):
        form_kwargs = super().get_form_kwargs(**kwargs)
        form_kwargs["course_type"] = CourseType.objects.get(id=self.kwargs["course_type_id"])
        return form_kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["creating"] = True
        context["course_type"] = CourseType.objects.get(id=self.kwargs["course_type_id"])
        return context


class CourseUpdateView(LoginRequiredMixin, StaffUserMixin, CourseCreateUpdateMixin, UpdateView):
    form_class = CourseUpdateForm

    def get_form_kwargs(self, **kwargs):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["course_type"] = self.get_object().course_type
        return form_kwargs
