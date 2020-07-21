from datetime import datetime

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404, render, HttpResponseRedirect
from django.views.generic import ListView, CreateView, UpdateView
from django.utils import timezone
from django.urls import reverse

from braces.views import LoginRequiredMixin

from activitylog.models import ActivityLog
from booking.email_helpers import send_bcc_emails
from booking.models import Booking, Event, Track, EventType, CourseType

from ..forms import EventCreateUpdateForm
from .utils import is_instructor_or_staff, staff_required, StaffUserMixin, InstructorOrStaffUserMixin


def help(request):
    return TemplateResponse(request, "studioadmin/help.html")


class TrackListView(LoginRequiredMixin, StaffUserMixin, ListView):
    template_name = "studioadmin/tracks.html"
    model = Track
    context_object_name = "tracks"


def toggle_track_default(request, track_id):
    track = get_object_or_404(Track, pk=track_id)
    track.default = not track.default
    track.save()
    messages.success(request, f"Default track set to {track.name}")
    return HttpResponseRedirect(reverse("studioadmin:tracks"))


class TrackCreateView(LoginRequiredMixin, StaffUserMixin, CreateView):
    template_name = "studioadmin/includes/track-add-modal.html"
    model = Track
    fields = ("name", "default")

    def form_valid(self, form):
        form.save()
        return HttpResponse(render_to_string('studioadmin/includes/modal-success.html'))


class TrackUpdateView(LoginRequiredMixin, StaffUserMixin, UpdateView):
    template_name = "studioadmin/includes/track-edit-modal.html"
    model = Track
    fields = ("name", "default")

    def form_valid(self, form):
        form.save()
        return HttpResponse(render_to_string('studioadmin/includes/modal-success.html'))


class EventTypeListView(LoginRequiredMixin, StaffUserMixin, ListView):
    template_name = "studioadmin/event_types.html"
    model = Track


class CourseTypeListView(LoginRequiredMixin, StaffUserMixin, ListView):
    template_name = "studioadmin/course_types.html"
    model = Track

