from datetime import datetime

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.paginator import Paginator
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404, render, HttpResponseRedirect
from django.views.generic import ListView, CreateView, UpdateView
from django.utils import timezone
from django.urls import reverse

from braces.views import LoginRequiredMixin

from activitylog.models import ActivityLog
from booking.email_helpers import send_bcc_emails
from booking.models import Booking, Course, Event, Track, EventType
from common.utils import full_name

from ..forms import CourseCreateForm, CourseUpdateForm
from .utils import get_current_courses, get_past_courses, get_not_yet_started_courses, \
    staff_required, StaffUserMixin, utc_adjusted_datetime


class CourseAdminListView(LoginRequiredMixin, StaffUserMixin, ListView):
    template_name = "studioadmin/courses.html"
    model = Course
    context_object_name = "courses"
    custom_paginate_by = 10

    def get_queryset(self):
        if self.request.GET.get("include_cancelled") == "yes":
            queryset = super().get_queryset()
        else:
            queryset = super().get_queryset().filter(cancelled=False)
        return get_current_courses(queryset)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.GET.get("include_cancelled") == "yes":
            context["show_cancelled"] = True
        all_courses = self.get_queryset()

        track_id = self.request.GET.get('track')
        requested_track = None
        if track_id:
            try:
                track_id = int(track_id)
                requested_track = Track.objects.get(id=track_id)
            except (ValueError, Track.DoesNotExist):
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
            track_queryset = [course for course in all_courses if course.event_type.track == track]
            if track_queryset:
                # Don't add the track tab if there are no events to display
                track_paginator = Paginator(track_queryset, self.custom_paginate_by)
                page = 1
                if "tab" in self.request.GET and tab == i:
                    try:
                        page = int(self.request.GET.get('page', 1))
                    except ValueError:
                        pass
                page_obj = track_paginator.get_page(page)
                track_obj = {
                    'index': i,
                    'page_obj': page_obj,
                    'track': track.name
                }
                track_courses.append(track_obj)

                if requested_track and requested_track == track:
                    # we returned here from another view that was on a particular track, we want to set the
                    # tab to that track
                    context["active_tab"] = i

        context['track_courses'] = track_courses
        return context


class PastCourseAdminListView(CourseAdminListView):

    def get_queryset(self):
        if self.request.GET.get("include_cancelled") == "yes":
            queryset = Course.objects.all()
        else:
            queryset = Course.objects.filter(cancelled=False)
        # not super, because the super view filters only to current/future
        return get_past_courses(queryset)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.GET.get("include_cancelled") == "yes":
            context["show_cancelled"] = True
        context['past'] = True
        return context


class NotStartedYetCourseAdminListView(CourseAdminListView):

    def get_queryset(self):
        if self.request.GET.get("include_cancelled") == "yes":
            queryset = Course.objects.all()
        else:
            queryset = Course.objects.filter(cancelled=False)
        # not super, because the super view filters only to current/future
        return get_not_yet_started_courses(queryset)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.GET.get("include_cancelled") == "yes":
            context["show_cancelled"] = True
        context['not_started'] = True
        return context


def ajax_toggle_course_visible(request, course_id):
    course = Course.objects.get(id=course_id)
    if course.can_be_visible():
        course.show_on_site = not course.show_on_site
        course.save()

    return render(request, "studioadmin/includes/ajax_toggle_course_visible_btn.html", {"course": course})


def ajax_toggle_course_partial_booking(request, course_id):
    course = Course.objects.get(id=course_id)
    course.allow_partial_booking = not course.allow_partial_booking
    course.save()

    return render(request, "studioadmin/includes/ajax_toggle_course_allow_partial_booking_btn.html", {"course": course})


@login_required
@staff_required
def cancel_course_view(request, slug):
    course = get_object_or_404(Course, slug=slug)
    bookings_to_cancel = Booking.objects.filter(status="OPEN", event__course=course)
    bookings_to_cancel_users = [
        booking.user for booking in bookings_to_cancel.order_by().distinct("user")
    ]

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

            send_email_confirmation = request.POST.get("send_email_confirmation")
            if bookings_to_cancel and send_email_confirmation:
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
                message = f"bookings cancelled{' and notification emails sent to students' if send_email_confirmation else ''}"
            else:
                message = 'no open bookings'
            messages.success(request, f'Course and all associated events cancelled; {message}')
            ActivityLog.objects.create(log=f"Course {course} cancelled by admin user {request.user}; {message}")

        return HttpResponseRedirect(reverse('studioadmin:courses') + f"?track={course.event_type.track_id}")

    context = {
        'course': course,
        'bookings_to_cancel_users': bookings_to_cancel_users,
    }
    return TemplateResponse(request, 'studioadmin/cancel_course.html', context)


@login_required
@staff_required
def course_create_choice_view(request):
    event_types = EventType.objects.all()
    return render(request, "studioadmin/course_create_choose_event_type.html", {"event_types": event_types})


class CourseCreateUpdateMixin:
    template_name = "studioadmin/course_create_update.html"
    model = Course

    def _check_visibility_and_save(self, course):
        if not course.can_be_visible() and course.show_on_site:
            course.show_on_site = False
            messages.error(self.request, "ERROR: Course cannot be made visible until it is fully configured")
        course.save()
        if course.can_be_visible() and not course.is_configured() and course.show_on_site:
            messages.error(
                self.request,
                f"WARNING: Course has started but is no longer fully configured (but is still visible on site)")

    def _create_events(self, course, form):
        event_name = form.cleaned_data["create_events_name"]
        event_time = form.cleaned_data["create_events_time"]
        event_duration = form.cleaned_data["create_events_duration"]
        event_dates = form.cleaned_data["create_events_dates"]
        # event_dates = event_dates.split(",")
        event_dates = [
            datetime.strptime(event_date.strip(), "%d-%b-%Y") for event_date in event_dates.split(",")
        ] if event_dates else []
        # then try to add the new events; reject if class with same name at same date/time already exists
        created_events = []
        duplicates = []
        for event_date in event_dates:
            # If the requested event start date is in DST, we need to adjust the literal time, otherwise it'll be created
            # as that literal time in UTC, which will be 1 hour earlier than we want
            naive_event_start = datetime.combine(event_date, event_time)
            event_start = utc_adjusted_datetime(naive_event_start)
            event, created = Event.objects.get_or_create(
                name=event_name, event_type=course.event_type, start=event_start,
                defaults={
                    "course": course,
                    "description": course.description,
                    "duration": event_duration,
                    "max_participants": course.max_participants,
                    "show_on_site": course.show_on_site,
                }
            )
            created_events.append(event) if created else duplicates.append(event)
        if created_events:
            messages.success(self.request, f"{len(created_events)} new {course.event_type.pluralized_label} created and added to course")
        if duplicates:
            messages.warning(
                self.request, f"{len(duplicates)} {course.event_type.pluralized_label} with the same name, event_type and "
                              f"date/time already existed and were not created."
            )
        return created_events, duplicates

    def get_success_url(self, track_id):
        return reverse('studioadmin:courses') + f"?track={track_id}"


class CourseCreateView(LoginRequiredMixin, StaffUserMixin, CourseCreateUpdateMixin, CreateView):

    form_class = CourseCreateForm

    def get_form_kwargs(self, **kwargs):
        form_kwargs = super().get_form_kwargs(**kwargs)
        form_kwargs["event_type"] = EventType.objects.get(id=self.kwargs["event_type_id"])
        return form_kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["creating"] = True
        context["event_type"] = EventType.objects.get(id=self.kwargs["event_type_id"])
        return context

    def form_valid(self, form):
        course = form.save()
        # first find the existing events and add those
        event_ids = form.cleaned_data["events"]
        events = Event.objects.filter(id__in=event_ids)
        for event in events:
            event.course = course
            event.save()

        # now generate the requested new classes and add those to the course
        self._create_events(course, form)

        self._check_visibility_and_save(course)
        return HttpResponseRedirect(self.get_success_url(course.event_type.track_id))


class CourseUpdateView(LoginRequiredMixin, StaffUserMixin, CourseCreateUpdateMixin, UpdateView):
    form_class = CourseUpdateForm

    def get_form_kwargs(self, **kwargs):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["event_type"] = self.get_object().event_type
        return form_kwargs

    def form_valid(self, form):
        course = form.save(commit=False)
        if not form.hide_events:
            # First update the existing events with the choices in the existing event multiselect
            new_events = form.cleaned_data.get("events")
            for event in course.uncancelled_events:
                if event not in new_events:
                    course.events.remove(event)
            for event in new_events:
                if event not in course.uncancelled_events:
                    course.events.add(event)
            # Now create any requested dates
            self._create_events(course, form)
        self._check_visibility_and_save(course)

        # Make sure all users with uncancelled course bookings have a booking for all events
        # (even if cancelled/no-show).
        booked_users = set(Booking.objects.select_related("event")
                           .filter(status="OPEN", event__course_id=course.id)
                           .order_by().distinct("user").values_list("user", flat=True))
        updated_users = set()
        for event in course.events.all():
            unbooked_users = booked_users - set(event.bookings.values_list("user", flat=True))
            if unbooked_users:
                for user_id in unbooked_users:
                    user = User.objects.get(id=user_id)
                    updated_users.add(user)
                    other_booking = user.bookings.filter(event__course=course).first()
                    Booking.objects.create(
                        user=user, event=event, status="OPEN" if not event.cancelled else "CANCELLED", block=other_booking.block
                    )
        if updated_users:
            messages.info(
                self.request, f"Course events have been added; bookings have been added for the following users who were "
                              f"already booked onto this course: {', '.join([full_name(updated_user) for updated_user in updated_users])}"
            )

        return HttpResponseRedirect(self.get_success_url(course.event_type.track.id))


def clone_course_view(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    course.id = None
    course.show_on_site = False
    course.save()
    messages.success(request, f"Course cloned - not visible on site. Click link below to add {course.event_type.pluralized_label}.")
    return HttpResponseRedirect(reverse('studioadmin:courses') + f"?track={course.event_type.track.id}")
