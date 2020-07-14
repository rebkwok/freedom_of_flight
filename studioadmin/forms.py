# -*- coding: utf-8 -*-
from django import forms
from django.contrib.auth.models import User

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
