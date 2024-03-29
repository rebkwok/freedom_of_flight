# -*- coding: utf-8 -*-
from decimal import Decimal
import json
from math import floor

from django.conf import settings
from datetime import datetime
from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

from crispy_forms.bootstrap import InlineCheckboxes, AppendedText, PrependedText
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Button, Layout, Submit, Row, Column, Field, Fieldset, Hidden, HTML, Div
from delorean import Delorean

from .form_utils import Formset
from ..views.utils import get_current_courses
from accounts.admin import CookiePolicyAdminForm, DataPrivacyPolicyAdminForm, DisclaimerContentAdminForm
from accounts.models import CookiePolicy, DisclaimerContent, DataPrivacyPolicy
from booking.models import (
    Booking, Block, Event, Course, EventType, COMMON_LABEL_PLURALS, BlockConfig, SubscriptionConfig,
    Subscription, WaitingListUser
)
from booking.models import has_available_course_block
from common.utils import full_name
from timetable.models import TimetableSession


def validate_future_date(value):
    now = timezone.now()
    value_to_validate = value.date() if isinstance(value, datetime) else value
    if value_to_validate < now.date():
        raise ValidationError('Date must be in the future')


def get_user_choices(event):
    # TODO also show if user has available block/courseblock
    def callable():
        # get all open bookings including no-show
        bookings = event.bookings.filter(status='OPEN')
        booked_user_ids = bookings.values_list('user_id', flat=True)
        users = User.objects.exclude(id__in=booked_user_ids).order_by('first_name')
        return tuple([('', 'Select student')] + [(user.id, "{} {} ({})".format(user.first_name, user.last_name, user.username)) for user in users])

    return callable


def _obj_date_string(obj):
    if obj.start_date:
        dates_string = f"starts {obj.start_date.strftime('%d %b %Y')} -- expires {obj.expiry_date.strftime('%d %b %Y')}"
    else:
        dates_string = "not started yet"
    return dates_string


class EventModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj}{' (drop-in)' if not obj.course else ''}"


class BlockModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.block_config.name} - {_obj_date_string(obj)}"


class SubscriptionModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.config.name} - {_obj_date_string(obj)}"


class BlockConfigModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.name}{' (not active)' if not obj.active else ''}"


class AddRegisterBookingForm(forms.Form):

    def __init__(self, *args, **kwargs):
        event = kwargs.pop('event')
        super(AddRegisterBookingForm, self).__init__(*args, **kwargs)
        self.fields['user'] = forms.ChoiceField(
            choices=get_user_choices(event),
            required=False,
            label = "Add a new booking",
        )
            
        self.helper = FormHelper()
        self.helper.layout = Layout(                
            "user",
            Submit('submit', 'Add booking', css_class="btn btn-success pl-2 pr-2 pt-0 pb-0")
        )


class EventCreateUpdateForm(forms.ModelForm):

    class Meta:
        model = Event
        fields = (
            "event_type",
            "name", "description", "start", "duration",
            "max_participants",
            "video_link",
            "video_link_available_after_class",
            "show_on_site",
            "cancelled"
        )

    def __init__(self,*args, **kwargs):
        self.event_type = kwargs.pop("event_type")
        super().__init__(*args, **kwargs)

        self.fields["start"].widget.format = '%d-%b-%Y %H:%M'
        self.fields["start"].input_formats = ['%d-%b-%Y %H:%M']
        self.fields["description"].initial = self.event_type.description
        self.helper = FormHelper()
        self.helper.layout = Layout(
            "event_type" if self.instance.id else Hidden("event_type", self.event_type.id),
            "name",
            Field("description", rows=10),
            AppendedText(
                "start", "<i id='id_start_open' class='far fa-calendar'></i>", autocomplete="off",
            ),
            Field("duration", type="integer"),
            Field("max_participants", type="integer"),
            "video_link" if self.event_type.is_online else Hidden("video_link", ""),
            "video_link_available_after_class" if self.event_type.is_online else Hidden("video_link_available_after_class", ""),
            "show_on_site",
            "cancelled" if self.instance.id and self.instance.cancelled else Hidden("cancelled", False),
            Submit('submit', 'Save')
        )


class TimetableSessionCreateUpdateForm(forms.ModelForm):

    class Meta:
        model = TimetableSession
        fields = (
            "event_type",
            "name", "description", "day", "time", "duration",
            "max_participants",
        )

    def __init__(self, *args, **kwargs):
        self.event_type = kwargs.pop("event_type")
        super().__init__(*args, **kwargs)

        self.fields["time"].widget.format = '%H:%M'
        self.fields["time"].input_formats = ['%H:%M']
        self.fields["description"].initial = self.event_type.description

        self.helper = FormHelper()
        self.helper.layout = Layout(
            "event_type" if self.instance.id else Hidden("event_type", self.event_type.id),
            "name",
            Field("description", rows=10),
            "day",
            AppendedText(
                "time", "<i id='id_time_open' class='far fa-clock'></i>", autocomplete="off",
            ),
            Field("duration", type="integer"),
            Field("max_participants", type="integer"),
            Submit('submit', 'Save')
        )


def get_course_event_choices(event_type, instance_id=None):

    if instance_id is None:
        queryset = Event.objects.filter(
            event_type=event_type, start__gte=timezone.now(), cancelled=False, course__isnull=True
        ).order_by('start')
    else:
        query = (
            Q(event_type=event_type, start__gte=timezone.now(), cancelled=False, course__isnull=True) |
            Q(course_id=instance_id)
        )
        queryset = Event.objects.filter(query).order_by('start')
    return queryset


class CourseUpdateForm(forms.ModelForm):

    class Meta:
        model = Course
        fields = (
            "event_type",
            "name", "description",
            "number_of_events",
            "max_participants",
            "show_on_site",
            "allow_drop_in",
            "cancelled",
        )

    def __init__(self,*args, **kwargs):
        self.event_type = kwargs.pop("event_type")
        super().__init__(*args, **kwargs)
        self.back_url = reverse("studioadmin:courses")
        self.fields["event_type"].help_text = (
            "NOTE: Changing event type for the course will change the event type for any associated events"
        )

        for name, field in self.fields.items():
            if name in ["show_on_site", "allow_drop_in"]:
                field.widget.attrs = {"class": "form-check-inline"}
            elif name == "cancelled" and self.instance:
                if self.instance.cancelled:
                    field.widget.attrs = {"class": "form-check-inline"}
                else:
                    field.widget = forms.HiddenInput()
            else:
                field.widget.attrs = {"class": "form-control"}
                if name == "description":
                    field.widget.attrs.update({"rows": 10})

        self.fields["allow_drop_in"].label = "Allow drop-in booking"

        self.hide_events = False
        self.bookings_exist = False
        if self.instance.id:
            self.bookings_exist = Booking.objects.filter(event__in=self.instance.uncancelled_events).exists()
            if self.instance.is_configured() and self.bookings_exist:
                self.hide_events = True

        if not self.hide_events:
            self.fields["events"] = forms.ModelMultipleChoiceField(
                required=False,
                queryset=get_course_event_choices(self.event_type, self.instance.id),
                widget=forms.SelectMultiple(attrs={"class": "form-control"}),
                label=""
            )
            if self.instance.id:
                self.fields["events"].initial = [event.id for event in self.instance.uncancelled_events]
            self.fields["create_events_name"] = forms.CharField(
                max_length=255, label=f"{self.event_type.label.title()} name",
                help_text=f"Name for autogenerated {self.event_type.pluralized_label}",
                required=False
            )
            self.fields["create_events_time"] = forms.TimeField(
                widget=forms.TimeInput(attrs={"autocomplete": "off"}, format='%H:%M'),
                label=f"{self.event_type.label.title()} time",
                help_text=f"Time for autogenerated {self.event_type.pluralized_label}",
                required=False,
                input_formats=['%H:%M'],
            )
            self.fields["create_events_duration"] = forms.IntegerField(
                help_text=f"Duration for autogenerated {self.event_type.pluralized_label}",
                required=False,
                label="Duration",
            )
            self.fields["create_events_dates"] = forms.CharField(
                widget=forms.TextInput(attrs={"autocomplete": "off"}),
                max_length=255, label=f"{self.event_type.label.title()} dates",
                help_text=f"Select multiple dates",
                required=False
            )

        self.helper = FormHelper()
        self.helper.layout = Layout(
            self._layout_name_and_description(),
            self._layout_settings(),
            self._layout_event_selection(self.hide_events),
            self._layout_buttons(),
        )

    def _layout_name_and_description(self, hide_event_type=False):
        return Fieldset(
            "Name and description",
            Hidden("event_type", self.event_type.id) if hide_event_type else "event_type",
            "name",
            "description",
        )

    def _layout_settings(self, hide_cancelled=False):
        return Fieldset(
            "Settings",
            "number_of_events",
            "max_participants",
            "show_on_site",
            "allow_drop_in",
            Hidden("cancelled", self.instance.cancelled) if hide_cancelled else "cancelled",
        )

    def _layout_event_selection(self, hide_events=False):
        if hide_events:
            return HTML("")
        return Fieldset(
            f"Scheduled {self.event_type.pluralized_label.title()}",
            HTML(
                f"<p>Select existing {self.event_type.pluralized_label} or create new ones</p>"
                f"<p class='form-text text-muted'>You can use a combination of these options (e.g. select 1 {self.event_type.label} that "
                f"already exists and create 3 additional {self.event_type.pluralized_label} on specified dates). "
                f"</p>"
            ),
            HTML(f"<h5>Add existing {self.event_type.pluralized_label}:</h5>"),
            "events",
            HTML(f"<h5>Create new {self.event_type.pluralized_label}:</h5>"),
            HTML(
                f"<p class='form-text text-muted'>Enter a single name, time and duration that will be applied to all "
                f"created {self.event_type.pluralized_label}. {self.event_type.label.title()} descriptions will be "
                f"populated with the course description.</p>"
            ),
            "create_events_name",
            Row(
                Column(
                    AppendedText(
                        'create_events_time',
                        '<i id="id_time_open" class="far fa-clock"></i>'
                    ), css_class="col-6"
                ),
                Column(
                    AppendedText('create_events_duration', 'mins'), css_class="col-6"
                ),
            ),
            AppendedText(
                "create_events_dates",
                '<i id="id_event_dates_open" class="far fa-calendar"></i>'
            ),
        )

    def _layout_buttons(self):
        return Row(
            Submit('submit', f'Save', css_class="btn-sm mr-2"),
            HTML(f'<a class="btn btn-sm btn-outline-dark" href="{self.back_url}">Cancel</a>')
        )

    def clean_events(self):
        events = self.cleaned_data["events"]
        if self.bookings_exist:
            # bookings already exist; make sure any uncancelled events are still in the events list
            current_events = self.instance.uncancelled_events
            error = False
            for event in current_events:
                if event not in events:
                    error = True
                    self.add_error(
                        "events", f"{self.event_type.label.title()} {event} has been previously booked and cannot be removed from this course")
            if error:
                return
        return events

    # def clean_number_of_events(self):
    #     number_of_events = self.cleaned_data["number_of_events"]
    #     if number_of_events <= 0:
    #         self.add_error("number_of_events", "Number of events must be > 0")
    #     else:
    #         return number_of_events

    def clean_create_events_dates(self):
        create_events_dates = self.cleaned_data["create_events_dates"]
        if create_events_dates:
            errors = []
            for event_date in create_events_dates.split(","):
                try:
                    datetime.strptime(event_date.strip(), "%d-%b-%Y")
                except ValueError:
                    errors.append(event_date.strip())
            if errors:
                self.add_error(
                    "create_events_dates",
                    f"Some dates were entered in an invalid format ({', '.join(errors)}). Ensure all dates are in "
                    f"the format dd-mmm-yyyy and separated by commas."
                )
            else:
                return create_events_dates

    def clean(self):
        cleaned_data = super().clean()
        if self.errors:
            return
        if "events" in cleaned_data:
            events = cleaned_data["events"]
            create_events_dates = cleaned_data["create_events_dates"]
            create_events_dates_list = create_events_dates.split(",") if create_events_dates else []

            number_of_events = cleaned_data["number_of_events"]
            total_selected_events = len(events) + len(create_events_dates_list)
            if total_selected_events > number_of_events:
                error_msg = f"Too many {self.event_type.pluralized_label} selected or requested for creation; " \
                            f"select a maximum total of {number_of_events}."
                if events:
                    self.add_error("events", error_msg)
                if create_events_dates:
                    self.add_error("create_events_dates", error_msg)

            if create_events_dates:
                create_events_name = cleaned_data["create_events_name"]
                create_events_time = cleaned_data["create_events_time"]
                create_events_duration = cleaned_data["create_events_duration"]
                error_msg = f"This field is required when creating new {self.event_type.pluralized_label}"
                if not create_events_name:
                    self.add_error("create_events_name", error_msg)
                if not create_events_time:
                    self.add_error("create_events_time", error_msg)
                if not create_events_duration:
                    self.add_error("create_events_duration", error_msg)


class CourseCreateForm(CourseUpdateForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.layout = Layout(
            self._layout_name_and_description(hide_event_type=True),
            self._layout_settings(hide_cancelled=True),
            self._layout_event_selection(),
            self._layout_buttons(),
        )


class CloneEventWeeklyForm(forms.Form):
    recurring_weekly_weekdays = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"},),
        choices=(
            (0, "Mon"), (1, "Tue"), (2, "Wed"), (3, "Thu"), (4, "Fri"), (5, "Sat"), (6, "Sun")
        ),
        label="Days",
        required=True
    )
    recurring_weekly_time = forms.TimeField(
        required=True, label="Time",
        widget=forms.TimeInput(attrs={"autocomplete": "off"}, format='%H:%M'), input_formats=['%H:%M']
    )
    recurring_weekly_start = forms.DateField(
        required=True, label="Start date",
        widget=forms.DateInput(attrs={"autocomplete": "off"}, format='%d-%b-%Y'), input_formats=['%d-%b-%Y'],
        validators=(validate_future_date,)
    )
    recurring_weekly_end = forms.DateField(
        required=True, label="End date",
        widget=forms.DateInput(attrs={"autocomplete": "off"}, format='%d-%b-%Y'), input_formats=['%d-%b-%Y'],
        validators=(validate_future_date,)
    )

    def __init__(self, *args, **kwargs):
        event = kwargs.pop("event")
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                "Recurring on the same day(s) each week:",
                InlineCheckboxes('recurring_weekly_weekdays'),
                Row(
                    Column(
                        AppendedText('recurring_weekly_time', '<i id="id_recurring_weekly_time_open" class="far fa-clock"></i>'),
                        css_class='form-group col-12 col-md-4'
                    ),
                    Column(
                        AppendedText('recurring_weekly_start', "<i id='id_recurring_weekly_start_open' class='far fa-calendar'></i>"),
                        css_class='form-group col-6 col-md-4'
                    ),
                    Column(
                        AppendedText('recurring_weekly_end', "<i id='id_recurring_weekly_end_open' class='far fa-calendar'></i>"),
                        css_class='form-group col-6 col-md-4'
                    ),
                ),
                Submit('submit', f'Clone weekly recurring {event.event_type.label}')
            )
        )

    def clean(self):
        if not self.errors:
            if self.cleaned_data["recurring_weekly_start"] > self.cleaned_data["recurring_weekly_end"]:
                self.add_error("recurring_weekly_end", "End date must be after start date")
        return super().clean()


class CloneEventDailyIntervalsForm(forms.Form):
    recurring_daily_date = forms.DateField(
        required=True, label="Date",
        widget=forms.DateInput(attrs={"autocomplete": "off"}, format='%d-%b-%Y'), input_formats=['%d-%b-%Y'],
        validators=(validate_future_date,)
    )
    recurring_daily_interval = forms.IntegerField(required=True, label="Interval", min_value=0)
    recurring_daily_starttime = forms.TimeField(
        required=True, label="Start time",
        widget=forms.TimeInput(attrs={"autocomplete": "off"}, format='%H:%M'), input_formats=['%H:%M']
    )
    recurring_daily_endtime = forms.TimeField(
        required=True, label="End time",
        widget=forms.TimeInput(attrs={"autocomplete": "off"}, format='%H:%M'), input_formats=['%H:%M']
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                "Recurring on a single day at regular intervals:",
                Row(
                    Column(
                        AppendedText('recurring_daily_date',
                                     "<i id='id_recurring_daily_date_open' class='far fa-calendar'></i>"),
                        css_class='form-group col-12 col-md-12'
                    ),
                    Column(AppendedText('recurring_daily_interval', 'mins'), css_class='form-group col-12 col-md-4'),

                    Column(
                        AppendedText('recurring_daily_starttime',
                                     '<i id="id_recurring_daily_starttime_open" class="far fa-clock"></i>'),
                        css_class='form-group col-6 col-md-4'
                    ),
                    Column(
                        AppendedText('recurring_daily_endtime',
                                     '<i id="id_recurring_daily_endtime_open" class="far fa-clock"></i>'),
                        css_class='form-group col-6 col-md-4'
                    ),
                ),
                Submit('submit', f'Clone at recurring intervals')
            ),
        )

    def clean(self):
        if self.cleaned_data["recurring_daily_starttime"] > self.cleaned_data["recurring_daily_endtime"]:
            self.add_error("recurring_daily_endtime", "End time must be after start time")
        return super().clean()


class CloneSingleEventForm(forms.Form):

    recurring_once_datetime = forms.DateTimeField(
        required=True, label="Date and time",
        widget=forms.DateTimeInput(attrs={"autocomplete": "off"}, format='%d-%b-%Y %H:%M'),
        input_formats=['%d-%b-%Y %H:%M'],
        validators=(validate_future_date,)
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                "Recurring once at a specific date and time:",
                AppendedText('recurring_once_datetime', "<i id='id_recurring_once_datetime_open' class='far fa-calendar'></i>"),
                Submit('submit', 'Clone once')
            ),
        )


class CloneTimetableSessionForm(forms.Form):
    days = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"},),
        choices=TimetableSession.DAY_CHOICES,
        label="Days",
        required=True
    )
    time = forms.TimeField(
        required=True, label="Time",
        widget=forms.TimeInput(attrs={"autocomplete": "off"}, format='%H:%M'), input_formats=['%H:%M']
    )
    name = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            InlineCheckboxes('days'),
            AppendedText('time', '<i id="id_recurring_weekly_time_open" class="far fa-clock"></i>'),
            "name",
            Submit('submit', f'Clone timetable session')
        )


def get_session_choices(track):
    def callable():
        sessions = TimetableSession.objects.filter(event_type__track=track).order_by("day", "time")
        return tuple([(tsession.id, tsession) for tsession in sessions])
    return callable


class UploadTimetableForm(forms.Form):
    track = forms.IntegerField()
    track_index = forms.IntegerField()
    show_on_site = forms.BooleanField(initial=False, required=False, help_text="Make all uploaded sessions immediately visible to students")
    start_date = forms.DateField(
        required=True, label="Start date",
        widget=forms.DateInput(attrs={"autocomplete": "off"}, format='%d-%b-%Y'), input_formats=['%d-%b-%Y'],
        validators=(validate_future_date,)
    )
    end_date = forms.DateField(
        required=True, label="End date",
        widget=forms.DateInput(attrs={"autocomplete": "off"}, format='%d-%b-%Y'), input_formats=['%d-%b-%Y'],
        validators=(validate_future_date,)
    )

    def __init__(self, *args, **kwargs):
        track = kwargs.pop("track")
        track_index = kwargs.pop("track_index")
        super().__init__(*args, **kwargs)
        # This form is duplicated for each track tab, so we need the ids to be unique.  They should all be
        # appended with the track index
        for field_name, field in self.fields.items():
            field.widget.attrs.update({"id": f"id_{field_name}_{track_index}"})
        # Need to name the sessions field with the track index, otherwise it's option checkboxes will still be
        # named the same way as all other tracks
        # Do this after updating the ids for other fields, since it'll get the right id anyway
        self.fields[f"sessions_{track_index}"] = forms.MultipleChoiceField(
            widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}, ),
            choices=get_session_choices(track),
            required=True,
            label="Choose sessions to upload:"
        )
        self.fields[f"sessions_{track_index}"].initial = [
            choice[0] for choice in self.fields[f"sessions_{track_index}"].choices
        ]
        self.fields["start_date"].widget.attrs.update({"class": "upload_start"})

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Hidden("track", track.id),
            Hidden("track_index", track_index),
            f'sessions_{track_index}',
            Button(f'Toggle All {track_index}', "Select/Deselect All", css_class="btn btn-sm btn-outline-primary mb-4"),
            Row(
                Column(
                    AppendedText(
                        "start_date",
                        f"<i id='id_start_date_{track_index}_open' class='start_date_open far fa-calendar'></i>"
                    ),
                    css_class='form-group col-6 col-md-4'
                ),
                Column(
                    AppendedText(
                        'end_date',
                        f"<i id='id_end_date_{track_index}_open' class='end_date_open far fa-calendar'></i>"
                    ),
                    css_class='form-group col-6 col-md-4'
                ),
            ),
            "show_on_site",
            Submit('submit', f'Upload selected sessions')
        )

    def clean(self):
        if not self.errors:
            if self.cleaned_data["start_date"] > self.cleaned_data["end_date"]:
                self.add_error("end_date", "End date must be after start date")
        return super().clean()


class BaseEmailForm(forms.Form):
    message = forms.CharField(widget=forms.Textarea())
    reply_to_email = forms.EmailField(initial=settings.DEFAULT_STUDIO_EMAIL)
    cc = forms.BooleanField(initial=False, label="Send a copy to me", required=False)
    subject = forms.CharField()

    def get_form_helper(self):
        helper = FormHelper()
        helper.layout = Layout(
            HTML(
                "<div class='helptext pt-0 mt-0 mb-2'>For child/dependent users, the email will be sent to the main user account</div>"
            ),
            'students',
            "subject",
            "reply_to_email",
            "cc",
            Field("message", rows=15),
            Submit('submit', f'Send email')
        )
        return helper

    def clean(self):
        if not self.cleaned_data.get("students"):
            self.add_error("students", "Select at least one student to email")


class EmailWaitingListUsersForm(BaseEmailForm):

    def __init__(self, *args, **kwargs):
        event = kwargs.pop("event", None)
        super().__init__(*args, **kwargs)
        waiting_list_users = WaitingListUser.objects.filter(event=event).order_by("date_joined")
        choices = [
            (waiting_list_user.user.id, f"{full_name(waiting_list_user.user)} (joined {waiting_list_user.date_joined.strftime('%d-%b-%y')})")
            for waiting_list_user in waiting_list_users
        ]

        self.fields["students"] = forms.MultipleChoiceField(
            widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
            choices=choices,
            required=False,
            label=f"The following students are on the waiting list for this {event.event_type.label}.",
            initial={waiting_list_user.user.id for waiting_list_user in waiting_list_users},
        )
        self.fields["subject"].initial = event
        self.helper = self.get_form_helper()


class EmailUsersForEventOrCourseForm(BaseEmailForm):

    def __init__(self, *args, **kwargs):
        event = kwargs.pop("event", None)
        course = kwargs.pop("course", None)
        subscription_config = kwargs.pop("subscription_config", None)
        super().__init__(*args, **kwargs)
        target = "event" if event else "course" if course else "subscription"
        if course:
            # flattened list of all bookings (no-shows included but not cancelled)
            bookings = sum([list(event.bookings.filter(status="OPEN")) for event in course.events.all()], [])
            cancelled_bookings = []
        elif event:
            bookings = event.bookings.filter(status="OPEN", no_show=False)
            cancelled_bookings = event.bookings.filter(Q(status="CANCELLED") | Q(no_show=True))

        if subscription_config:
            not_expired = subscription_config.subscription_set.filter(paid=True, expiry_date__gte=timezone.now())
            not_expired_user_ids = not_expired.distinct("user_id").values_list("user_id", flat=True)
            expired = subscription_config.subscription_set.filter(paid=True).exclude(user_id__in=not_expired_user_ids)
            choices = [
                *{(subscription.user.id, f"{full_name(subscription.user)}") for subscription in not_expired},
                *{(subscription.user.id, f"{full_name(subscription.user)} (expired)") for subscription in expired}
            ]
            students_label = "The following students have purchased subscriptions."
            students_initial = {subscription.user.id for subscription in not_expired}
        else:
            choices = [
                # a set for the first bunch of choices, because courses will have duplicates
                *{(booking.user.id, f"{full_name(booking.user)}") for booking in bookings},
                *((booking.user.id, f"{full_name(booking.user)} (cancelled)") for booking in cancelled_bookings)
            ]
            students_label = f"The following students have booked for this {target}."
            students_initial = {booking.user.id for booking in bookings}
        self.fields["students"] = forms.MultipleChoiceField(
            widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
            choices=choices,
            required=False,
            label=students_label,
            initial=students_initial,
        )

        self.fields["subject"].initial = event if target == "event" else course.name if target == "course" else subscription_config.name

        self.helper = self.get_form_helper()


class EventTypeForm(forms.ModelForm):
    class Meta:
        model = EventType
        fields = (
            "track", "name", "label", "plural_suffix", "description", "booking_restriction",
            "minimum_age_for_booking", "maximum_age_for_booking",
            "cancellation_period", "email_studio_when_booked",
            "allow_booking_cancellation", "is_online"
        )

    def __init__(self, *args, **kwargs):
        track = kwargs.pop("track", None)
        super().__init__(*args, **kwargs)
        self.fields["description"].help_text = "Optional: this will be used to populate the description field " \
                                               "on events and timetable sessions (but it can be added/edited " \
                                               "for individual events/sessions too)"
        self.fields["plural_suffix"] = forms.ChoiceField(
            choices=sorted({(value, value) for value in COMMON_LABEL_PLURALS.values()}), required=False,
            label="Common options:"
        )
        self.fields["other_plural_suffix"] = forms.CharField(required=False, label="Or enter a custom suffix:")

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Hidden("track", track.id) if track is not None else "track",
            "name",
            "label",
            HTML(
                """
                How do we pluralise the label?<br/>
                <span class='helptext text-secondary'>Enter a suffix to pluralize the label. E.g. 'es' (class -> classes), or for plurals 
                that aren't simple suffixes, a single and plural suffix separated by a comma, e.g. 'y,ies' (party -> parties)</span>
                """
            ),
            Row(
                Column("plural_suffix", css_class="col-6"),
                Column("other_plural_suffix", css_class="col-6"),
            ),
            "description",
            AppendedText('booking_restriction', 'mins'),
            AppendedText('cancellation_period', 'hrs'),
            HTML(
                """
                <p>
                <strong>Optional age restrictions for booking:</strong><br/>
                <span class='helptext text-secondary'>
                    Note: restrictions will be applied to purchase of blocks/subscriptions, not to booking once a block/subscription
                    is purchased.
                </span>
                </p>"""
            ),
            Row(
                Column(AppendedText('minimum_age_for_booking', 'years'), css_class="col-6"),
                Column(AppendedText('maximum_age_for_booking', 'years'), css_class="col-6"),
            ),
        "email_studio_when_booked",
        "allow_booking_cancellation",
        "is_online",
        Submit('submit', f'Save')
    )

    def clean_name(self):
        name = self.cleaned_data["name"]
        return name.lower()

    def clean(self):
        super().clean()
        if self.cleaned_data.get("minimum_age_for_booking") and self.cleaned_data.get("maximum_age_for_booking"):
            self.add_error("minimum_age_for_booking", "Specify at most one of min/max age for booking")
            self.add_error("maximum_age_for_booking", "Specify at most one of min/max age for booking")


class BlockConfigForm(forms.ModelForm):
    class Meta:
        model = BlockConfig
        fields = ("event_type", "name", "description", "size", "duration", "course", "cost", "active")

    def __init__(self, *args, **kwargs):
        is_course = kwargs.pop("is_course")
        super().__init__(*args, **kwargs)
        if self.instance.id:
            self.existing_blocks = Block.objects.filter(block_config=self.instance, paid=True).exists()
        else:
            self.existing_blocks = False
        if is_course:
            self.fields["event_type"].help_text = "Each credit block is associated with a single event type and will be valid " \
                                          "for one course of that event type."
            self.fields["size"].help_text = "Number of events in the course."
        else:
            self.fields["event_type"].help_text = "Each credit block is associated with a single event type and will be valid " \
                                                  "for the number of events you select, for events of that event type only."
            self.fields["description"].help_text = "This will be displayed to users when purchasing credit blocks."
        self.fields["name"].help_text = "A short name for the credit block"
        self.fields["active"].label = "Purchaseable on site"
        self.fields["active"].help_text = "Available for purchase by users and will be displayed " \
                                          "on the credit block purchase page."
        self.helper = FormHelper()
        back_url = reverse('studioadmin:block_configs')
        self.helper.layout = Layout(
            HTML(f"<p><strong>Event Type: {self.instance.event_type.name}</strong></p>")
            if self.existing_blocks else HTML(""),
            Hidden('event_type', self.instance.event_type.id) if self.existing_blocks else "event_type",
            "name",
            "description",
            Field('size', readonly=True) if self.existing_blocks else "size",
            Field('duration', readonly=True) if self.existing_blocks else "duration",
            Hidden("course", is_course),
            PrependedText('cost', '£'),
            "active",
            Submit('submit', f'Save', css_class="btn btn-success"),
            HTML(f'<a class="btn btn-outline-dark" href="{back_url}">Back</a>')
        )


class BookableEventTypesForm(forms.Form):
    event_type = forms.ModelChoiceField(queryset=EventType.objects.all(), required=False)
    allowed_number = forms.ChoiceField(choices=[(None, "No limit"), *[(i, i) for i in range(100)]], required=False)
    allowed_unit = forms.ChoiceField(choices=(("day", "day"), ("week", "week"), ("month", "month")), required=False)


class SubscriptionConfigForm(forms.ModelForm):
    class Meta:
        model = SubscriptionConfig
        fields = ("recurring", "name", "description", "current_subscriber_info", "duration", "duration_units", "cost", "start_date",
                  "start_options", "advance_purchase_allowed", "partial_purchase_allowed",
                  "cost_per_week", "active", "include_no_shows_in_usage")

    def __init__(self, *args, **kwargs):
        recurring = kwargs.pop("recurring")
        super().__init__(*args, **kwargs)
        self.fields["description"].help_text = "This will be displayed to users when purchasing subscriptions."
        self.fields["name"].help_text = "A short name for the subscription"
        self.fields["active"].help_text = "Active subscriptions are available for purchase by users and will be displayed " \
                                          "on the subscriptions purchase page."

        self.fields["start_date"].widget = forms.DateInput(attrs={"autocomplete": "off"}, format='%d-%b-%Y')
        self.fields["start_date"].input_formats = ['%d-%b-%Y']

        if self.instance.id and not recurring:
            disable_start_date = Subscription.objects.filter(config=self.instance, paid=True).exists()
        else:
            disable_start_date = False

        if not recurring:
            self.fields["start_date"].required = True
            self.fields["start_date"].help_text = "Date the subscription starts"
            self.fields["advance_purchase_allowed"].help_text = "Allow students to purchase the subscription before the start date."
            self.fields["partial_purchase_allowed"].help_text = "Allow purchase of the subscription at a reduced price after the first week"
        else:
            self.fields["start_date"].initial = ""

        self.helper = FormHelper()
        back_url = reverse('studioadmin:subscription_configs')
        self.helper.layout = Layout(
            Hidden("recurring", recurring),
            Fieldset(
                "Subscription Details",
                "name",
                "description",
                "current_subscriber_info",
            ),
            Fieldset(
                "Duration and start",
                Row(
                    Column("duration", css_class="col-6"),
                    Column("duration_units", css_class="col-6")
                ),
                "start_options" if recurring else Hidden("start_options", "start_date"),
                HTML(
                    "<small>Note: cannot update start date for this subscription as it has already been purchased. "
                    "If you want to make a new subscription period, amke a copy of this subscription instead.</small>"
                ) if disable_start_date else HTML(""),
                AppendedText(
                    'start_date',
                    f"<i id='id_start_date_open' class='start_date_open far fa-calendar'></i>"
                ) if not disable_start_date else Field('start_date', readonly=True),
            ),
            Fieldset(
                "Payment settings",
                PrependedText('cost', '£'),
                "advance_purchase_allowed",
                "partial_purchase_allowed",
                PrependedText('cost_per_week', '£'),
            ),
            "active",
            Fieldset(
                "Usage (optional)",
                HTML(
                    "<small class='form-text text-muted'>Specify event types which can be booked with this subscription, with optional limits on use.<br/>"
                    "Subscriptions are not valid for courses.<br/>"
                    "Note that weekly/monthly allowed must match subscription duration (i.e. specify a weekly allowance for "
                    "subscriptions lasting a set number of weeks, and a monthly allowance for subscriptions lasting a set "
                    "number of months).  Daily limits can be set on any subscription.</small><br/>"
                ),
                "include_no_shows_in_usage",
                Formset("bookable_event_types_formset"),
            ),

            Submit('submit', f'Save', css_class="btn btn-success"),
            HTML(f'<a class="btn btn-outline-dark" href="{back_url}">Back</a>')
        )

    def clean_start_date(self):
        start_date = self.cleaned_data["start_date"]
        if start_date:
            # At this point start date is in local time, interpreted by the form
            # add the UTC offset, if there is one and convert it to UTC now, so that the model's save doesn't convert it
            # in local time
            utc_offset = start_date.utcoffset()
            start_date = Delorean(start_date)
            start_date = start_date + utc_offset
            start_date.shift("utc")
            start_date = start_date.datetime
        return start_date

    def clean(self):
        total_formset_forms = int(self.data['form-TOTAL_FORMS'])
        duration_units = self.cleaned_data["duration_units"]
        seen = set()
        age_restrictions = {}

        for i in range(total_formset_forms):
            event_type = self.data[f"form-{i}-event_type"]
            allowed_unit = self.data[f"form-{i}-allowed_unit"]
            allowed_number = self.data[f"form-{i}-allowed_number"]
            # don't bother validating items we're deleting
            deleting = self.data.get(f"form-{i}-DELETE")
            if event_type and not deleting:
                event_type_obj = EventType.objects.get(id=int(event_type))
                if allowed_number and allowed_unit != "day":
                    # Don't bother validating week/month units if no max number specified
                    duration_unit = duration_units.rstrip("s")
                    if allowed_unit != duration_unit:
                        self.add_error(
                            "__all__", f"Cannot specify {allowed_unit}ly usage for a subscription with a {duration_unit}ly duration. "
                                       f"Specify usage per {duration_unit} instead.")
                if event_type in seen:
                    self.add_error("__all__", f"Usage specified twice for event type {event_type_obj.name} (track {event_type_obj.track})")
                seen.add(event_type)

                if event_type_obj.minimum_age_for_booking:
                    age_restrictions[event_type_obj] = ("min", event_type_obj.minimum_age_for_booking)
                if event_type_obj.maximum_age_for_booking:
                    age_restrictions[event_type_obj] = ("max", event_type_obj.maximum_age_for_booking)

        if len(set(age_restrictions.values())) > 1:
            error_strings = [
                f"{ev_type.name.title()} ({ev_type.track}) - {restriction[0]} {restriction[1]} yrs"
                for ev_type, restriction in age_restrictions.items()
            ]
            self.add_error(
                "__all__", f"Event types have conflicting age restrictions: {', '.join(error_strings)}"
            )


class StudioadminCookiePolicyForm(CookiePolicyAdminForm):

    class Meta:
        model = CookiePolicy
        exclude = ('issue_date',)


class StudioadminDataPrivacyPolicyForm(DataPrivacyPolicyAdminForm):

    class Meta:
        model = DataPrivacyPolicy
        exclude = ('issue_date',)


class StudioadminDisclaimerContentForm(DisclaimerContentAdminForm):

    def __init__(self, *args, **kwargs):
        hide_reset_button = kwargs.pop("hide_reset_button", False)
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        back_url = reverse('studioadmin:disclaimer_contents')
        self.helper.layout = Layout(
            "disclaimer_terms",
            HTML(
                """
                <h4>Questionnaire</h4>
                <div class="helptext">Hover over each question to edit or remove.  To change the question type, you'll need to add a 
                new one.  Select from various question types in the right hand menu.</div>
                <div class="helptext">If you choose a question type with options (Select, Checkbox group, Radio Group), the two fields for 
                each option represent the value stored in the database and the label shown to users. Enter the same value
                in each field.</div>
                """
            ),
            "form_title",
            "form",
            "form_info",
            "version",
            Submit('save_draft', 'Save as draft', css_class="btn btn-primary"),
            Submit('publish', 'Publish', css_class="btn btn-success"),
            Submit('reset', 'Reset to latest published version', css_class="btn btn-secondary") if not hide_reset_button else HTML(''),
            HTML(f'<a class="btn btn-outline-dark" href="{back_url}">Back</a>')
        )

    class Meta:
        model = DisclaimerContent
        fields = ("disclaimer_terms", "version", "form", "form_title", "form_info")


class SearchForm(forms.Form):
    search = forms.CharField(
        help_text="Search name or email address", required=False, initial="", label=""
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = "get"
        self.helper.form_class = "form-inline"
        self.helper.layout = Layout(
            Row(
                Column("search", css_class="col-6"),
                Column(
                    Submit('action', 'Search', css_class="btn btn-sm btn-success"),
                    Submit('action', 'Reset', css_class="btn btn-sm btn-secondary"), css_class="col-6"),
            )
        )


class AddEditBookingForm(forms.ModelForm):

    send_confirmation = forms.BooleanField(
        widget=forms.CheckboxInput(attrs={'class': "regular-checkbox",}), initial=False, required=False,
        help_text="Send confimation email to student"
    )

    class Meta:
        model = Booking
        fields = (
            'user', 'event', 'status', 'no_show', 'attended', 'block', 'subscription',
        )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)
        if self.instance.id:
            self.event = self.instance.event
            course_event = self.event.course is not None
        else:
            self.event = None
            course_event = False
            already_booked = self.user.bookings.values_list("event_id", flat=True)
            events = Event.objects.filter(
                start__gte=timezone.now()
            ).filter(cancelled=False).exclude(id__in=already_booked).order_by('start')
            non_full_ids = [event.id for event in events if not event.full]
            self.fields['event'] = EventModelChoiceField(
                queryset=Event.objects.filter(id__in=non_full_ids),
                widget=forms.Select(attrs={'class': 'form-control input-sm'}),
                required=True,
                help_text="This is limited to events with spaces.  You can add a single event from a "
                          "course here (if the course is not fully booked), but if you want to add a"
                          " full course, use the 'Add Course Booking' button"
            )

        if course_event:
            # editing and existing booking for a course event; we'll hide the block/subscription
            # fields
            self.fields['block'] = BlockModelChoiceField(
                queryset=Block.objects.filter(id=self.instance.block.id) if self.instance.block else Block.objects.none(),
                required=False,
            )
            self.fields['subscription'] = SubscriptionModelChoiceField(
                queryset=Subscription.objects.none(),
                required=False,
            )
        else:
            # adding a new booking; include subscription and block fields, limit block options to
            # non-course blocks
            active_user_blocks = [
                block.id for block in self.user.blocks.filter(block_config__course=False)
                if block.active_block or block == self.instance.block

            ]
            self.fields['block'] = (BlockModelChoiceField(
                queryset=self.user.blocks.filter(id__in=active_user_blocks),
                widget=forms.Select(attrs={'class': 'form-control input-sm'}),
                required=False,
                empty_label="--------None--------"
            ))

            active_user_subscriptions = [
                subscription.id for subscription in self.user.subscriptions.filter(
                    paid=True, start_date__lte=timezone.now(), expiry_date__gte=timezone.now()
                ) if subscription.config.bookable_event_types
            ]
            self.fields['subscription'] = (SubscriptionModelChoiceField(
                queryset=self.user.subscriptions.filter(id__in=active_user_subscriptions),
                widget=forms.Select(attrs={'class': 'form-control input-sm'}),
                required=False,
                empty_label="--------None--------"
            ))

        self.fields['auto_assign_available_subscription_or_block'] = forms.BooleanField(
            initial=False, required=False,
            help_text="If user has a valid subscription/block for the selected event, assign it automatically.  "
                      "Subscriptions are used before blocks, if both exist.  Any entries in the subscription/block "
                      "fields below will be ignored.  This will NOT assign single event bookings to course credit blocks."
        )
        if (self.instance.id and (self.instance.block or self.instance.subscription)) or course_event:
            self.fields['auto_assign_available_subscription_or_block'].widget = forms.HiddenInput()
        else:
            self.fields['auto_assign_available_subscription_or_block'].initial = True

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Hidden("user", self.user.id),
            Hidden("event", self.event.id) if self.event else "event",
            "status",
            "no_show",
            "attended",
            "auto_assign_available_subscription_or_block",
            Hidden("subscription", self.instance.subscription.id if self.instance.subscription else "") if course_event else "subscription",
            Hidden("block", self.instance.block.id if self.instance.block else "") if course_event else "block",
            HTML(f"<p class='helptext'>Credit blocks used for courses are not editable on single booking.  "
                 f"If you want to update the credit block used for this booking, you can change the course "
                 f"assigned to it in the student's blocks list.</p>") if course_event else HTML(""),
            Submit('submit', 'Save')
        )

    def clean(self):
        """
        make sure that block selected is for the correct event type
        Add form validation for cancelled bookings
        """
        auto_assign_available_subscription_or_block = self.cleaned_data.get("auto_assign_available_subscription_or_block")
        block = self.cleaned_data.get('block')
        subscription = self.cleaned_data.get('subscription')
        event = self.event or self.cleaned_data.get('event')
        status = self.cleaned_data.get('status')
        no_show = self.cleaned_data.get('no_show')

        if self.event is not None and event.course:
            # no options to change existing course blocks
            return

        if not auto_assign_available_subscription_or_block:
            # We'll ignore any assigned blocks/subscriptions if auto-assigning
            if block and subscription:
                self.add_error("__all__", "Assign booking to EITHER a block or a subscription, not both")
            if block:
                # check block validity; only needs to be checked on non-courses
                if not block.valid_for_event(event):
                    self.add_error("block", f"Block is not valid for this {event.event_type.label} (wrong event type or expired by date of {event.event_type.label})")
                if status == "CANCELLED" and not no_show:
                    self.add_error(
                        "block", f"Block cannot be assigned for cancelled booking. Set to open and no_show if a block should be used.")
            if subscription:
                # check subscription validity; this will check both events and courses
                if not subscription.valid_for_event(event):
                    msg = f"Subscription is not valid for this {event.event_type.label} (invalid event type, usage limits " \
                          f"reached, or expired by date of {event.event_type.label})"
                    self.add_error("subscription", msg)
        else:
            # unset and entered block and subscription values if auto-assigning
            if block:
                self.cleaned_data["block"] = None
            if subscription:
                self.cleaned_data["subscription"] = None

        # full event
        if not event.spaces_left:
            if not self.instance.id:
                if status == "OPEN" and not no_show:
                    # Trying to make a new, open booking
                    self.add_error("__all__", f"This {event.event_type.label} is full, can't make new booking.")
            else:
                # if this is an existing booking for a course, booking can be reopened, no need to check
                existing_booking = self.user.bookings.get(event=event)
                if (status == "OPEN" and not no_show) and (existing_booking.status == "CANCELLED" or existing_booking.no_show):
                    # trying to reopen cancelled booking for full event
                    if status == "OPEN" and not no_show:
                        self.add_error("__all__", f"This {event.event_type.label} is full, can't make new booking.")

    def full_clean(self):
        super().full_clean()
        if self.errors.get("__all__"):
            errorlist = [*self.errors["__all__"]]
            for error in self.errors["__all__"]:
                # remove the default full booking messages, it's not user friendly and we should have added a nicer one already
                if error.startswith("Attempting to create booking for full event") and len(self.errors["__all__"]) >= 2:
                    errorlist.remove(error)
            if errorlist != self.errors["__all__"]:
                self.errors["__all__"] = errorlist


class AddEditBlockForm(forms.ModelForm):

    class Meta:
        model = Block
        fields = ('user', 'paid', 'block_config', 'manual_expiry_date')

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields["manual_expiry_date"] = forms.DateField(
            required=False, label="Manual expiry date",
            widget=forms.DateInput(attrs={"autocomplete": "off"}, format='%d-%b-%Y'), input_formats=['%d-%b-%Y'],
            help_text="Leave blank to auto-calculate expiry date"
        )

        if not self.instance.id or not self.instance.bookings.exists():
            block_type_queryset = BlockConfig.objects.all().order_by("-active")
            block_type_help_text = "Active blocks are purchaseable by users. Inactive blocks can be used " \
                                   "to give students credit or allow purchase at a custom rate.  If you add " \
                                   "an unpaid block here, it will appear in the user's shopping cart for purchase."
        else:
            # choices should only include the same event type if there are any events already booked
            block_type_queryset = BlockConfig.objects.filter(active=True, event_type=self.instance.block_config.event_type).order_by("-active")
            block_type_help_text = "Bookings have already been made using this block; can only change to a block " \
                                   "of the same type"
        self.fields["block_config"] = BlockConfigModelChoiceField(label="Block Type", queryset=block_type_queryset, help_text=block_type_help_text)

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Hidden("user", self.user.id),
            "block_config",
            HTML(f"<p>Purchase date: <b>{self.instance.purchase_date.strftime('%d-%b-%y')}</b></p>") if self.instance.id else HTML(""),
            HTML(f"<p>Start date (set to date of first booking): <b>{self.instance.start_date.strftime('%d-%b-%y')}</b></p>") if self.instance.id and self.instance.start_date else HTML(""),
            "paid",
            HTML("<p>By default, expiry date is calculated from date of first booking, as determined by the block duration. "
                 "If required, you can override it here with a manually set date.</p>"),
            HTML(f"<p>Expiry date: <b>{self.instance.expiry_date.strftime('%d-%b-%y')}</b></p>") if self.instance.id and self.instance.expiry_date else HTML(""),
            "manual_expiry_date",
            Submit('submit', 'Save')
        )


class AddEditSubscriptionForm(forms.ModelForm):

    class Meta:
        model = Subscription
        fields = ('user', 'paid')

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        # add field for subscriptions with start options for user
        configs = SubscriptionConfig.objects.filter(active=True)
        config_choices = []

        def _format_option(option):
            if not option:
                return "None"
            return option.strftime("%d-%b-%Y")

        def _format_option_display(config, option):
            if not option:
                if config.start_options == "signup_date":
                    return "starts on purchase date"
                elif config.start_options == "first_booking_date":
                    return "starts on date of first use"
                else:
                    return ""
            return f"start {option.strftime('%d-%b-%Y')}"

        for config in configs:
            options = config.get_start_options_for_user(self.user)
            config_choices.extend([(f"{config.id}_{_format_option(option)}", f"{config.name} - {_format_option_display(config, option)}") for option in options])
        if self.instance.id:
            current_value = f"{self.instance.config.id}_{_format_option(self.instance.start_date)}"
            config_choices.insert(
                0,
                (
                    current_value,
                    f"{self.instance.config.name} - {_format_option_display(self.instance.config, self.instance.start_date)}"
                )
            )
        self.fields["subscription_options"] = forms.ChoiceField(
            choices=config_choices,
            help_text="Select the subscription and start date (if applicable) that you want to add. Note this only shows "
                      "options that are available to this user. For subscriptions that recur from a specific date and "
                      "allow advance purchase, a user can have one for both the current and next period"
        )
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Hidden("user", self.user.id),
            "subscription_options",
            HTML(f"<p>Purchase date: <b>{self.instance.purchase_date.strftime('%d-%b-%y')}</b></p>") if self.instance.id else HTML(""),
            "paid",
            Submit('submit', 'Save')
        )


class CourseBookingAddChangeForm(forms.Form):

    send_confirmation = forms.BooleanField(
        widget=forms.CheckboxInput(attrs={'class': "regular-checkbox", }), initial=False, required=False,
        help_text="Send confimation email to student"
    )

    def __init__(self, *args, **kwargs):
        booking_user = kwargs.pop('booking_user')
        # block None == adding a course booking afresh, not editing a block to add a course to it
        block = kwargs.pop('block', None)
        old_course = kwargs.pop('old_course', None)
        old_course_id = old_course.id if old_course else None
        super().__init__(*args, **kwargs)
        if block is None:
            help_text = mark_safe(
                "Note that this list shows only ongoing/future courses:"
                "<ul>"
                "<li>that are fully configured</li>"
                "<li>have spaces in all classes</li>"
                "<li>that this user hasn't already booked for</li>"
                "<li>that this user has a valid block for</li>"
                "</ul>"
                "You can't make a new course booking for a full course.<br/>"
                "If the course you want to book isn't shown here, you may need to create "
                "a block for the user first."
            )
        else:
            help_text = mark_safe(
                "Note that this list shows only ongoing/future courses:"
                "<ul>"
                "<li>that are fully configured</li>"
                "<li>have spaces in all classes</li>"
                "<li>that are valid for this credit block</li>"
                "</ul>"
                "You can't reassign the block to a full course."
            )

        self.helper = FormHelper()
        course_choices = get_course_choices_for_user(booking_user, block, old_course_id)
        if not course_choices:
            if block is None:
                self.helper.layout = Layout(
                    HTML(
                        f"<p>No courses are available to book for this student.</p>"
                        f"<p>Either the student has booked/part-booked for all available courses, or "
                        f"student has no available course credit blocks for available courses. Go to their"
                        f" <a href={reverse('studioadmin:user_blocks', args=(booking_user.id,))}>blocks list</a> to "
                        f"add one first. You will be able to assign a course to the new block from there.</p>"
                        f"")
                )
            else:
                self.helper.layout = Layout(
                    HTML(
                        f"<p>No courses are available to book for this student and block.</p>")
                    )
        else:
            self.fields['course'] = forms.ChoiceField(
                choices=course_choices,
                required=True,
                help_text=help_text,
            )

            self.helper.layout = Layout(
                HTML(f"<p><strong>Current course:</strong> {old_course.name + ' - start ' + old_course.start.strftime('%d-%b') if old_course else 'None'}</p>")
                if block else HTML(""),
                "course",
                HTML(
                    f"<p>Changing an existing course on a block will cancel the student's bookings for the old course "
                    f"and create a booking for every {block.block_config.event_type.label} in the new course.</p>"
                ) if block is not None else HTML(
                    "<p>The course will be automatically assigned to the student's next available block.</p>"
                ),
                "send_confirmation",
                Submit('submit', 'Save')
            )

    def full_clean(self):
        super().full_clean()
        if self.errors.get("course"):
            errorlist = [*self.errors["course"]]
            for i, error in enumerate(self.errors["course"]):
                # remove the default full booking messages, it's not user friendly and we should have added a nicer one already
                if "select a valid choice" in error.lower():
                    course_choice = self.data.get("course")
                    try:
                        course = Course.objects.get(id=course_choice)
                        if course.full:
                            errorlist.remove(error)
                            errorlist.insert(i, f"The course {course} is now full")
                        elif not self.fields["course"].choices:
                            errorlist.remove(error)
                            errorlist.insert(i, f"No valid course options")
                    except Exception:
                        pass
            if errorlist != self.errors["course"]:
                self.errors["course"] = errorlist


def get_course_choices_for_user(user, block, current_course_id):
    if block is not None:
        # CHANGING COURSE ON A BLOCK
        # get only courses that that haven't ended yet, match the block's event type and size,
        # excluding the one it's already used for
        course_ids = [
            course.id for course in Course.objects.filter(event_type=block.block_config.event_type)
            if course.number_of_events == block.block_config.size
            or course.events_left.count() == block.block_config.size
        ]
        queryset = Course.objects.filter(id__in=course_ids)

        if current_course_id:
            queryset = queryset.exclude(id=current_course_id)
        courses = get_current_courses(queryset)
        # filter out courses that are full and not configured.  We already filtered to courses of the same
        # event type and size of this block, so any choices are valid switches
        courses = [course for course in courses if course.is_configured() and not course.full]
    else:
        # ADDING A COURSE BOOKING TO AN AVAILABLE BLOCK
        # get all courses that haven't ended yet and that the user hasn't already booked for
        user_booked_course_ids = user.bookings.filter(
            event__course__isnull=False, status="OPEN"
        ).order_by().distinct("event__course").values_list("event__course_id")
        queryset = Course.objects.exclude(id__in=user_booked_course_ids)
        courses = get_current_courses(queryset)
        # filter out courses that are full and not configured, and limit to ones the student has a
        # block for
        courses = [
            course for course in courses if course.is_configured() and not course.full
            and has_available_course_block(user, course)
        ]

    return tuple(
        [
            (course.id, f"{course.name} - start {course.start.strftime('%d-%b')}") for course in courses
        ]
    )
