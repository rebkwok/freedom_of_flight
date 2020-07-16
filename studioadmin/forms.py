# -*- coding: utf-8 -*-
from django import forms
from django.contrib.auth.models import User

from booking.models import Event
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
        )

    def __init__(self,*args, **kwargs):
        self.event_type = kwargs.pop("event_type")
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == "show_on_site":
                field.widget.attrs = {"class": "form-check-inline"}
            elif name == "video_link" and not self.event_type.is_online:
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
