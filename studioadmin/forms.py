# -*- coding: utf-8 -*-
from decimal import Decimal
import json
from math import floor

from django.conf import settings
from datetime import datetime, date
from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import reverse
from django.utils import timezone

from crispy_forms.bootstrap import InlineCheckboxes, AppendedText, PrependedText
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Button, Layout, Submit, Row, Column, Field, Fieldset, Hidden, HTML

from accounts.admin import CookiePolicyAdminForm, DataPrivacyPolicyAdminForm, DisclaimerContentAdminForm
from accounts.models import DisclaimerContent
from booking.models import Event, Course, EventType, COMMON_LABEL_PLURALS, DropInBlockConfig, CourseBlockConfig
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
        booked_user_ids = event.bookings.filter(status='OPEN', no_show=False).values_list('user_id', flat=True)
        users = User.objects.exclude(id__in=booked_user_ids).order_by('first_name')
        return tuple([(user.id, "{} {} ({})".format(user.first_name, user.last_name, user.username)) for user in users])

    return callable


class AddRegisterBookingForm(forms.Form):

    def __init__(self, *args, **kwargs):
        event = kwargs.pop('event')
        super(AddRegisterBookingForm, self).__init__(*args, **kwargs)
        self.fields['user'] = forms.ChoiceField(
            choices=get_user_choices(event),
            required=True,
            label="Student",
            widget=forms.Select(
                attrs={'id': 'id_new_user', 'class': 'form-control'})
        )


class EventCreateUpdateForm(forms.ModelForm):

    class Meta:
        model = Event
        fields = (
            "event_type",
            "name", "description", "start", "duration",
            "max_participants",
            "video_link",
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
            "video_link" if self.event_type.is_online else Hidden("cancelled", ""),
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


def get_course_event_choices(course_type, instance_id=None):

    def callable():
        if instance_id is None:
            queryset = Event.objects.filter(
                event_type=course_type.event_type, start__gte=timezone.now(), cancelled=False, course__isnull=True
            ).order_by('start')
        else:
            query = (
                Q(event_type=course_type.event_type, start__gte=timezone.now(), cancelled=False, course__isnull=True) |
                Q(course_id=instance_id)
            )
            queryset = Event.objects.filter(query).order_by('start')
        EVENT_CHOICES = [(event.id, str(event)) for event in queryset]
        return tuple(EVENT_CHOICES)

    return callable


class CourseUpdateForm(forms.ModelForm):

    class Meta:
        model = Course
        fields = (
            "course_type",
            "name", "description",
            "max_participants",
            "show_on_site",
            "cancelled"
        )

    def __init__(self,*args, **kwargs):
        self.course_type = kwargs.pop("course_type")
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == "show_on_site":
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

        self.fields["events"] = forms.MultipleChoiceField(
            required=False,
            choices=get_course_event_choices(self.course_type, self.instance.id),
            widget=forms.SelectMultiple(attrs={"class": "form-control"}),
            help_text="Select one or more (ctrl/cmd+click to select multiple)",
            label=f"Add {self.course_type.event_type.pluralized_label} to this course"
        )

        if self.instance:
            self.fields["events"].initial = [event.id for event in self.instance.events.all()]

    def clean_events(self):
        events = self.cleaned_data["events"]
        if len(events) > self.course_type.number_of_events:
            self.add_error("events", f"Too many {self.course_type.event_type.pluralized_label} selected; select a maximum of {self.course_type.number_of_events}")
        else:
            return events


class CourseCreateForm(CourseUpdateForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course_type"].widget = forms.HiddenInput(attrs={"value": self.course_type.id})
        self.fields["cancelled"].widget = forms.HiddenInput()


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
        self.fields[f"sessions_{track_index}"].initial = [choice[0] for choice in self.fields[f"sessions_{track_index}"].choices]
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


class EmailUsersForm(forms.Form):
    message = forms.CharField(widget=forms.Textarea())
    reply_to_email = forms.EmailField(initial=settings.DEFAULT_STUDIO_EMAIL)
    cc = forms.BooleanField(initial=False, label="Send a copy to me", required=False)
    subject = forms.CharField()

    def __init__(self, *args, **kwargs):
        event = kwargs.pop("event", None)
        course = kwargs.pop("course", None)
        super().__init__(*args, **kwargs)
        target = "event" if event else "course"
        if course:
            # flattened list of all bookings
            bookings = sum([list(event.bookings.all()) for event in course.events.all()], [])
            cancelled_bookings = []
        else:
            bookings = event.bookings.filter(status="OPEN", no_show=False)
            cancelled_bookings = event.bookings.filter(Q(status="CANCELLED") | Q(no_show=True))
        choices = [
            # a set for the first bunch of choices, because courses will have duplicates
            *{(booking.user.id, f"{full_name(booking.user)}") for booking in bookings},
            *((booking.user.id, f"{full_name(booking.user)} (cancelled)") for booking in cancelled_bookings)
       ]
        self.fields["students"] = forms.MultipleChoiceField(
            widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
            choices=choices,
            required=False,
            label=f"The following students have booked for this {target}.",
            initial={booking.user.id for booking in bookings},
        )

        self.fields["subject"].initial = event if target == "event" else course.name

        self.helper = FormHelper()
        self.helper.layout = Layout(
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

    def clean(self):
        if not self.cleaned_data.get("students"):
            self.add_error("students", "Select at least one student to email")


class EventTypeForm(forms.ModelForm):
    class Meta:
        model = EventType
        fields = (
            "track", "name", "label", "plural_suffix", "description", "cancellation_period", "email_studio_when_booked",
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
            Hidden("track", track) if track is not None else "track",
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
            AppendedText('cancellation_period', 'hrs'),
            "email_studio_when_booked",
            "allow_booking_cancellation",
            "is_online",
            Submit('submit', f'Save')
        )


class DropInBlockConfigForm(forms.ModelForm):
    class Meta:
        model = DropInBlockConfig
        fields = ("event_type", "identifier", "description", "size", "duration", "cost", "active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["event_type"].help_text = "Each credit block is associated with a single event type and will be valid " \
                                              "for the number of events you select, for events of that event type only."
        self.fields["description"].help_text = "This will be displayed to users when purchasing credit blocks."
        self.fields["identifier"].help_text = "A short name for the credit block"
        self.fields["active"].help_text = "Active credit blocks are available for purchase by users and will be displayed " \
                                          "on the credit block purchase page."
        self.helper = FormHelper()
        back_url = reverse('studioadmin:block_configs')
        self.helper.layout = Layout(
            "event_type",
            "identifier",
            "description",
            "size",
            "duration",
            PrependedText('cost', '£'),
            "active",
            Submit('submit', f'Save', css_class="btn btn-success"),
            HTML(f'<a class="btn btn-outline-dark" href="{back_url}">Back</a>')
        )


class CourseBlockConfigForm(forms.ModelForm):
    class Meta:
        model = CourseBlockConfig
        fields = ("course_type", "identifier", "description", "duration", "cost", "active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course_type"].help_text = "Each course credit block is associated with a single course type which " \
                                               "defines the event type and number of events and in the course."
        self.fields["description"].help_text = "This will be displayed to users when purchasing credit blocks."
        self.fields["identifier"].help_text = "A short name for the credit block"
        self.fields["active"].help_text = "Active credit blocks are available for purchase by users and will be displayed " \
                                          "on the credit block purchase page."
        self.helper = FormHelper()
        back_url = reverse('studioadmin:block_configs')
        self.helper.layout = Layout(
            "course_type",
            "identifier",
            "description",
            "duration",
            PrependedText('cost', '£'),
            "active",
            Submit('submit', f'Save', css_class="btn btn-success"),
            HTML(f'<a class="btn btn-outline-dark" href="{back_url}">Back</a>')
        )


class StudioadminDisclaimerContentForm(DisclaimerContentAdminForm):

    def __init__(self, *args, **kwargs):
        same_as_published = kwargs.pop("same_as_published", False)
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        back_url = reverse('studioadmin:disclaimer_contents')
        self.helper.layout = Layout(
            "disclaimer_terms",
            HTML(
                """
                <h4>Health Questionnaire</h4>
                <div class="helptext">Hover over each question to edit or remove.  To change the question type, you'll need to add a 
                new one.  Select from various question types in the right hand menu.</div>
                <div class="helptext">If you choose a question type with options (Select, Checkbox group, Radio Group), the two fields for 
                each option represent the value stored in the database and the label shown to users. Enter the same value
                in each field.</div>
                """
            ),
            "form",
            "version",
            Submit('save_draft', 'Save as draft', css_class="btn btn-primary"),
            Submit('publish', 'Publish', css_class="btn btn-success"),
            Submit('reset', 'Reset to latest published version', css_class="btn btn-secondary") if not same_as_published else '',
            HTML(f'<a class="btn btn-outline-dark" href="{back_url}">Back</a>')
        )

    class Meta:
        model = DisclaimerContent
        fields = ("disclaimer_terms", "version", "form")


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
