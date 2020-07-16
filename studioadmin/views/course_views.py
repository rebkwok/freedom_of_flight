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
from booking.models import Course, Event, Track, EventType

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
        context['track_courses'] = track_courses
        return context
