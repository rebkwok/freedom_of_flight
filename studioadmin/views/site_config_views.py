from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404, render, HttpResponseRedirect
from django.views.decorators.http import require_http_methods
from django.views.generic import ListView, CreateView, UpdateView
from django.urls import reverse

from braces.views import LoginRequiredMixin

from activitylog.models import ActivityLog
from booking.models import Track, EventType, BlockConfig
from common.utils import full_name

from ..forms import EventTypeForm, BlockConfigForm
from .utils import staff_required, StaffUserMixin, is_instructor_or_staff


@login_required
@is_instructor_or_staff
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


class TrackCreateUpdateMixin(LoginRequiredMixin, StaffUserMixin):
    model = Track
    fields = ("name", "default")

    def form_valid(self, form):
        track = form.save()
        ActivityLog.objects.create(
            log=f"Track id {track.id} ({track}) {self.action} by admin user {full_name(self.request.user)}"
        )
        return HttpResponse(render_to_string('studioadmin/includes/modal-success.html'))


class TrackCreateView(TrackCreateUpdateMixin, CreateView):
    template_name = "studioadmin/includes/track-add-modal.html"
    action = "created"


class TrackUpdateView(TrackCreateUpdateMixin, UpdateView):
    template_name = "studioadmin/includes/track-edit-modal.html"
    action = "updated"


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


@login_required
@staff_required
def block_config_list_view(request):
    block_configs = BlockConfig.objects.all().order_by("active")
    context = {
        "block_config_groups": {
            "Drop-in Credit Blocks": block_configs.exclude(course=True),
            "Course Credit Blocks": block_configs.filter(course=True),
        }
    }
    return render(request, "studioadmin/credit_blocks.html", context)


@require_http_methods(['POST'])
def ajax_toggle_block_config_active(request):
    block_config_id = request.POST["block_config_id"]
    block_config = get_object_or_404(BlockConfig, pk=block_config_id)
    block_config.active = not block_config.active
    block_config.save()
    ActivityLog.objects.create(
        log=f"Credit block '{block_config.name}' "
            f"set to {'active' if block_config.active else 'not active'} by admin user {full_name(request.user)}"
    )
    return render(request, "studioadmin/includes/ajax_toggle_block_config_active_btn.html", {"block_config": block_config})


def block_config_delete_view(request, block_config_id):
    block_config = get_object_or_404(BlockConfig, pk=block_config_id)
    if block_config.block_set.exists():
        return HttpResponseBadRequest("Cannot delete credit block; blocks have already been purchased/created")
    ActivityLog.objects.create(
        log=f"Credit block {block_config.name} (id {block_config_id}) deleted by admin user {full_name(request.user)}"
    )
    block_config.delete()
    return JsonResponse({"deleted": True, "alert_msg": "Credit block deleted"})


def choose_block_config_type(request):
    if request.method == "POST":
        if "dropin" in request.POST:
            return HttpResponseRedirect(reverse("studioadmin:add_block_config", args=("dropin",)))
        elif "course" in request.POST:
            return HttpResponseRedirect(reverse("studioadmin:add_block_config", args=("course",)))
    return render(request, "studioadmin/includes/block-config-add-modal.html")


class BlockConfigCreateView(CreateView):
    model = BlockConfig
    template_name = "studioadmin/block_config_create_update.html"
    form_class = BlockConfigForm

    def dispatch(self, request, *args, **kwargs):
        self.block_config_type = kwargs["block_config_type"]
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["is_course"] = True if self.block_config_type == "course" else False
        return form_kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["creating"] = True
        context["block_config_type"] = "Course" if self.block_config_type == "course" else "Drop-in"
        return context

    def get_success_url(self):
        return reverse("studioadmin:block_configs")


class BlockConfigUpdateView(LoginRequiredMixin, StaffUserMixin, UpdateView):
    model = BlockConfig
    form_class = BlockConfigForm
    template_name = "studioadmin/block_config_create_update.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["block_config_type"] = "Course" if self.object.course else "Drop-In"
        return context

    def get_form_kwargs(self):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["is_course"] = True if self.object.course else False
        return form_kwargs

    def form_valid(self, form):
        form.save()
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("studioadmin:block_configs")
