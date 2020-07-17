# -*- coding: utf-8 -*-
from datetime import datetime, date
from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from crispy_forms.bootstrap import InlineCheckboxes, AppendedText
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, Field, Fieldset, Hidden, HTML

from booking.models import Event, Course
from booking.utils import has_available_block, has_available_course_block


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
            widget=forms.SelectMultiple(attrs={"class": "form-control"})
        )
        if self.instance:
            self.fields["events"].initial = [event.id for event in self.instance.events.all()]

    def clean_events(self):
        events = self.cleaned_data["events"]
        if len(events) > self.course_type.number_of_events:
            self.add_error("events", f"Too many events selected; select a maximum of {self.course_type.number_of_events}")
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
