# -*- coding: utf-8 -*-
import pytz

from django import forms
from django.conf import settings
from django.contrib.auth.models import User
from django.forms.models import modelformset_factory, BaseModelFormSet
from django.utils import timezone
from booking.models import Course, Event

from ..views.utils import get_current_courses, get_current_and_started_courses

DATETIME_FORMAT = '%a %d %b %y, %H:%M'

def get_event_names():

    def callable():
        EVENT_CHOICES = [
            (
                event.id,
                f"{event.name} - {event.start.astimezone(pytz.timezone('Europe/London')).strftime(DATETIME_FORMAT)}"
            )
            for event in Event.objects.filter(start__gte=timezone.now()).order_by('start')]
        return tuple(EVENT_CHOICES)

    return callable


def get_course_names():

    def callable():
        def _course_start(course):
            if course.start:
                return f"start {course.start.astimezone(pytz.timezone('Europe/London')).strftime(DATETIME_FORMAT)}"
            return "not started"
        # exclude not started courses
        queryset = Course.objects.all()
        COURSE_CHOICES = [(course.id, f"{course.name} - {_course_start(course)}") for course in get_current_and_started_courses(queryset)]
        return tuple(COURSE_CHOICES)
    return callable


def get_students():

    def callable():
        return tuple(
            [
                (user.id, '{} {} ({})'.format(
                    user.first_name, user.last_name, user.username
                )) for user in User.objects.all()
                ]
        )
    return callable


class UserFilterForm(forms.Form):

    events = forms.MultipleChoiceField(
        choices=get_event_names(),
        widget=forms.SelectMultiple(attrs={"class": "form-control"}),
        required=False,
        label=""
    )

    courses = forms.MultipleChoiceField(
        choices=get_course_names(),
        widget=forms.SelectMultiple(attrs={"class": "form-control"}),
        required=False,
        label=""
    )
    students = forms.MultipleChoiceField(
        choices=get_students(),
        widget=forms.SelectMultiple(attrs={"class": "form-control"}),
        required=False,
        label=""
    )


class ChooseUsersBaseFormSet(BaseModelFormSet):

    def add_fields(self, form, index):
        super(ChooseUsersBaseFormSet, self).add_fields(form, index)

        form.fields['email_user'] = forms.BooleanField(
            widget=forms.CheckboxInput(),
            initial=True,
            required=False
        )

ChooseUsersFormSet = modelformset_factory(
    User,
    fields=('id',),
    formset=ChooseUsersBaseFormSet,
    extra=0,
    max_num=2000,
    can_delete=False)


class EmailUsersForm(forms.Form):
    subject = forms.CharField(max_length=255, required=True,
                              widget=forms.TextInput(
                                  attrs={'class': 'form-control'}))
    from_address = forms.EmailField(max_length=255,
                                    initial=settings.DEFAULT_STUDIO_EMAIL,
                                    required=True,
                                    widget=forms.TextInput(attrs={'class': 'form-control'}),
                                    help_text='This will be the reply-to address')
    cc = forms.BooleanField(
        widget=forms.CheckboxInput(),
        label="cc. from address",
        initial=True,
        required=False
    )

    message = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-control'}))
