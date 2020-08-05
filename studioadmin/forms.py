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
from accounts.models import CookiePolicy, DisclaimerContent, DataPrivacyPolicy
from booking.models import (
    Booking, Block, Event, Course, EventType, COMMON_LABEL_PLURALS, BlockConfig
)
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
            "cancelled"
        )

    def __init__(self,*args, **kwargs):
        self.event_type = kwargs.pop("event_type")
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

        self.fields["events"] = forms.ModelMultipleChoiceField(
            required=False,
            queryset=get_course_event_choices(self.event_type, self.instance.id),
            widget=forms.SelectMultiple(attrs={"class": "form-control"}),
            label=f"Add {self.event_type.pluralized_label} to this course"
        )

        if self.instance:
            self.fields["events"].initial = [event.id for event in self.instance.events.all()]

    def clean_events(self):
        events = self.cleaned_data["events"]
        number_of_events = self.cleaned_data["number_of_events"]
        if len(events) > number_of_events:
            self.add_error("events", f"Too many {self.event_type.pluralized_label} selected; select a maximum of {number_of_events}")
        else:
            return events


class CourseCreateForm(CourseUpdateForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["event_type"].widget = forms.HiddenInput(attrs={"value": self.event_type.id})
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
            "track", "name", "label", "plural_suffix", "description", "booking_restriction",
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
            AppendedText('booking_restriction', 'mins'),
            AppendedText('cancellation_period', 'hrs'),
            "email_studio_when_booked",
            "allow_booking_cancellation",
            "is_online",
            Submit('submit', f'Save')
        )


class BlockConfigForm(forms.ModelForm):
    class Meta:
        model = BlockConfig
        fields = ("event_type", "name", "description", "size", "duration", "course", "cost", "active")

    def __init__(self, *args, **kwargs):
        is_course = kwargs.pop("is_course")
        super().__init__(*args, **kwargs)
        self.fields["event_type"].help_text = "Each credit block is associated with a single event type and will be valid " \
                                              "for the number of events you select, for events of that event type only."
        self.fields["description"].help_text = "This will be displayed to users when purchasing credit blocks."
        self.fields["name"].help_text = "A short name for the credit block"
        self.fields["active"].help_text = "Active credit blocks are available for purchase by users and will be displayed " \
                                          "on the credit block purchase page."
        self.helper = FormHelper()
        back_url = reverse('studioadmin:block_configs')
        self.helper.layout = Layout(
            "event_type",
            "name",
            "description",
            "size",
            "duration",
            Hidden("course", is_course),
            PrependedText('cost', '£'),
            "active",
            Submit('submit', f'Save', css_class="btn btn-success"),
            HTML(f'<a class="btn btn-outline-dark" href="{back_url}">Back</a>')
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
            Submit('reset', 'Reset to latest published version', css_class="btn btn-secondary") if not hide_reset_button else '',
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


class AddEditBookingForm(forms.ModelForm):

    send_confirmation = forms.BooleanField(
        widget=forms.CheckboxInput(attrs={'class': "regular-checkbox",}), initial=False, required=False,
        help_text="Send confimation email to student"
    )

    class Meta:
        model = Booking
        fields = (
            'user', 'event', 'status', 'no_show', 'attended', 'block',
        )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.user is not None:
            self.fields['user'].initial = self.user.id

        if self.instance.id:
            already_booked = self.user.bookings.exclude(event_id=self.instance.event.id).values_list("event_id", flat=True)
        else:
            already_booked = self.user.bookings.values_list("event_id", flat=True)

        self.fields['event'] = forms.ModelChoiceField(
            queryset=Event.objects.filter(
                start__gte=timezone.now()
            ).filter(cancelled=False).exclude(id__in=already_booked).order_by('-start'),
            widget=forms.Select(attrs={'class': 'form-control input-sm'}),
            required=True
        )

        active_user_blocks = [
            block.id for block in self.user.blocks.all() if block.active_block
        ]
        self.has_available_block = True if active_user_blocks else False

        self.fields['block'] = (forms.ModelChoiceField(
            queryset=self.user.blocks.filter(id__in=active_user_blocks),
            widget=forms.Select(attrs={'class': 'form-control input-sm'}),
            required=False,
            empty_label="--------None--------"
        ))

    def clean(self):
        """
        make sure that block selected is for the correct event type
        Add form validation for cancelled bookings
        """
        block = self.cleaned_data.get('block')
        event = self.cleaned_data.get('event')
        status = self.cleaned_data.get('status')
        no_show = self.cleaned_data.get('status')

        if block:
            # check block validity; this will check both events and courses
            if not block.valid_for_event(event):
                msg = f"{event.event_type.pluralized_label} on this course" if event.course else f"this {event.event_type.label}"
                self.add_error("block", f"Block is not valid for {msg} (wrong event type or expired by date of {event.event_type.label})")
            if status == "CANCELLED" and not no_show and not event.course:
                self.add_error(
                    "block", f"Block cannot be assigned for cancelled booking.  "
                             f"Set to open and no_show if a block should be used.")

        # full event
        if not event.spaces_left:
            if not self.instance.id:
                if status == "OPEN" and not no_show:
                    # Trying to make a new, open booking
                    self.add_error("__all__", f"This {event.event_type.label} is full, can't make new booking.")
            else:
                # if this is an existing booking for a course, booking can be reopened, no need to check
                if not event.course:
                    existing_booking = self.user.bookings.get(event=event)
                    if (status == "OPEN" and not no_show) and (existing_booking.status == "CANCELLED" or existing_booking.no_show):
                        # trying to reopen cancelled booking for full event
                        if status == "OPEN" and not no_show:
                            self.add_error("__all__", f"This {event.event_type.label} is full, can't make new booking.")


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

        self.fields["block_config"].label = "Block type"
        if not self.instance.id or not self.instance.bookings.exists():
            block_type_queryset = BlockConfig.objects.filter(active=True)
        else:
            # choices should only include the same event type if there are any events already booking
            block_type_queryset = BlockConfig.objects.filter(active=True, event_type=self.instance.block_config.event_type)
            self.fields["block_config"].help_text = "Bookings have already been made using this block; can only change to a block " \
                                                  "of the same type"
        self.fields["block_config"].queryset = block_type_queryset

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Hidden("user", self.user.id),
            "block_config",
            HTML(f"<p>Purchase date: <b>{self.instance.purchase_date.strftime('%d-%b-%y')}</b></p>") if self.instance.id else "",
            HTML(f"<p>Start date (set to date of first booking): <b>{self.instance.start_date.strftime('%d-%b-%y')}</b></p>") if self.instance.id and self.instance.start_date else "",
            "paid",
            HTML("<p>By default, expiry date is calculated from date of first booking, as determined by the block duration. "
                 "If required, you can override it here with a manually set date.</p>"),
            HTML(f"<p>Expiry date: <b>{self.instance.expiry_date.strftime('%d-%b-%y')}</b></p>") if self.instance.id and self.instance.expiry_date else "",
            "manual_expiry_date",
            Submit('submit', 'Save')
        )
