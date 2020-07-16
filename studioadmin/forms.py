# -*- coding: utf-8 -*-
from django import forms
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from booking.models import Event, Course
from booking.utils import has_available_block, has_available_course_block


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


class EventUpdateForm(forms.ModelForm):

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
        for name, field in self.fields.items():
            if name == "show_on_site":
                field.widget.attrs = {"class": "form-check-inline"}
            elif name == "video_link" and not self.event_type.is_online:
                field.widget = forms.HiddenInput()
            elif name == "cancelled" and self.instance:
                if self.instance.cancelled:
                    field.widget.attrs = {"class": "form-check-inline"}
                else:
                    field.widget = forms.HiddenInput()
            else:
                field.widget.attrs = {"class": "form-control"}
                if name == "description":
                    field.widget.attrs.update({"rows": 10})
                if name == "start":
                    field.widget.attrs.update({"autocomplete": "off"})
                    field.widget.format = '%d %b %Y %H:%M'
                    field.input_formats = ['%d %b %Y %H:%M']


class EventCreateForm(EventUpdateForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["event_type"].widget = forms.HiddenInput(attrs={"value": self.event_type.id})
        self.fields["cancelled"].widget = forms.HiddenInput()


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

