from datetime import datetime

from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404, render, HttpResponseRedirect
from django.views.generic import ListView, CreateView, UpdateView
from django.utils import timezone
from django.urls import reverse

from braces.views import LoginRequiredMixin

from activitylog.models import ActivityLog
from booking.email_helpers import send_bcc_emails
from booking.models import Booking, Event, Track, EventType, CourseType, DropInBlockConfig, CourseBlockConfig
from common.utils import full_name

from ..forms import EventTypeForm
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
        track = form.save()
        ActivityLog.objects.create(
            log=f"Track id {track.id} ({track}) created by admin user {full_name(self.request.user)}"
        )
        return HttpResponse(render_to_string('studioadmin/includes/modal-success.html'))


class TrackUpdateView(LoginRequiredMixin, StaffUserMixin, UpdateView):
    template_name = "studioadmin/includes/track-edit-modal.html"
    model = Track
    fields = ("name", "default")

    def form_valid(self, form):
        track = form.save()
        ActivityLog.objects.create(
            log=f"Track id {track.id} ({track}) updated by admin user {full_name(self.request.user)}"
        )
        return HttpResponse(render_to_string('studioadmin/includes/modal-success.html'))


class EventTypeListView(LoginRequiredMixin, StaffUserMixin, ListView):
    template_name = "studioadmin/event_types.html"
    model = EventType
    context_object_name = "event_types"


class BaseEventTypeMixin(LoginRequiredMixin, StaffUserMixin):
    template_name = "studioadmin/event_type_create_update.html"
    model = EventType
    form_class = EventTypeForm

    def get_success_url(self):
        return reverse("studioadmin:event_types")


class EventTypeCreateView(BaseEventTypeMixin, CreateView):

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        track = Track.objects.get(id=self.kwargs["track_id"])
        context["track"] = track
        context["creating"] = True
        return context

    def get_form_kwargs(self):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["track"] = Track.objects.get(id=self.kwargs["track_id"])
        return form_kwargs

    def form_valid(self, form):
        event_type = form.save()
        ActivityLog.objects.create(
            log=f"Event type id {event_type.id} ({event_type.name}) created by admin user {full_name(self.request.user)}"
        )
        return super().form_valid(form)


class EventTypeUpdateView(BaseEventTypeMixin, UpdateView):
    def form_valid(self, form):
        event_type = form.save()
        ActivityLog.objects.create(
            log=f"Event type id {event_type.id} ({event_type.name}) updated by admin user {full_name(self.request.user)}"
        )
        return super().form_valid(form)


@login_required
@staff_required
def event_type_delete_view(request, event_type_id):
    event_type = get_object_or_404(EventType, pk=event_type_id)
    if event_type.event_set.exists():
        return HttpResponseBadRequest("Can't delete event type; it has linked events")
    ActivityLog.objects.create(
        log=f"Event type {event_type.name} (id {event_type_id}) deleted by admin user {full_name(request.user)}"
    )
    event_type.delete()
    return JsonResponse({"deleted": True, "alert_msg": "Event type deleted"})


class ChooseTrackForm(forms.Form):
    track = forms.ModelChoiceField(
        Track.objects.all(),
        label="Choose a track for this event type"
    )


def choose_track_for_event_type(request):
    form = ChooseTrackForm()
    if request.method == "POST":
        form = ChooseTrackForm(request.POST)
        if form.is_valid():
            track_id = form.cleaned_data["track"].id
            return HttpResponseRedirect(reverse("studioadmin:add_event_type", args=(track_id,)))
    return render(request, "studioadmin/includes/event-type-add-modal.html", {"form": form})


class CourseTypeListView(LoginRequiredMixin, StaffUserMixin, ListView):
    template_name = "studioadmin/course_types.html"
    model = CourseType
    context_object_name = "course_types"


class CourseTypeCreateView(LoginRequiredMixin, StaffUserMixin, CreateView):
    template_name = "studioadmin/includes/course-type-add-modal.html"
    model = CourseType
    fields = ("event_type", "number_of_events")

    def form_valid(self, form):
        course_type = form.save()
        ActivityLog.objects.create(
            log=f"Course Type id {course_type.id} ({course_type}) created by admin user {full_name(self.request.user)}"
        )
        return HttpResponse(render_to_string('studioadmin/includes/modal-success.html'))


class CourseTypeUpdateView(LoginRequiredMixin, StaffUserMixin, UpdateView):
    template_name = "studioadmin/includes/course-type-edit-modal.html"
    model = CourseType
    fields = ("event_type", "number_of_events")

    def form_valid(self, form):
        course_type = form.save()
        ActivityLog.objects.create(
            log=f"Course Type id {course_type.id} ({course_type}) updated by admin user {full_name(self.request.user)}"
        )
        return HttpResponse(render_to_string('studioadmin/includes/modal-success.html'))


@login_required
@staff_required
def course_type_delete_view(request, course_type_id):
    course_type = get_object_or_404(CourseType, pk=course_type_id)
    if course_type.course_set.exists():
        return HttpResponseBadRequest("Can't delete course type; it has linked courses")
    ActivityLog.objects.create(
        log=f"Event type {course_type} (id {course_type_id}) deleted by admin user {full_name(request.user)}"
    )
    course_type.delete()
    return JsonResponse({"deleted": True, "alert_msg": "Course type deleted"})


@login_required
@staff_required
def block_config_list_view(request):
    dropin_block_configs = DropInBlockConfig.objects.all().order_by("active")
    course_block_configs = CourseBlockConfig.objects.all().order_by("active")
    context = {
        "dropin_block_configs": dropin_block_configs,
        "course_block_configs": course_block_configs,
    }
    return render(request, "studioadmin/credit_blocks.html", context)


def toggle_active_block_config(request):
    pass


def choose_event_or_course_type_for_block_config(request):
    pass


def delete_dropin_block_config(request, block_config_id):
    block_config = get_object_or_404(DropInBlockConfig, id=block_config_id)


def delete_course_block_config(request, block_config_id):
    block_config = get_object_or_404(CourseBlockConfig, id=block_config_id)


class BlockConfigCreateView(LoginRequiredMixin, StaffUserMixin, CreateView):
    pass


class BlockConfigUpdateView(LoginRequiredMixin, StaffUserMixin, UpdateView):
    pass