from datetime import timedelta
from django import forms
from django.utils import timezone

from .models import Event


def get_available_users(user):
    return [(user.id, f"{user.first_name} {user.last_name}") for user in user.managed_users]


def get_available_event_names(track):
    def callable():
        cutoff_time = timezone.now() - timedelta(minutes=10)
        event_names = list(
            (name, name) for name in {name.title() for name in Event.objects.select_related("event_type").filter(
                event_type__track=track, start__gt=cutoff_time, show_on_site=True, cancelled=False
            ).order_by("name").distinct("name").values_list("name", flat=True)}
        )
        event_names.insert(0, ("", "Show all"))
        return tuple(event_names)
    return callable


class AvailableUsersForm(forms.Form):

    def __init__(self, **kwargs):
        request = kwargs.pop("request")
        initial_view_as_user = kwargs.pop("view_as_user")
        super().__init__(**kwargs)
        self.fields["view_as_user"] = forms.CharField(
            max_length=255,
            widget=forms.Select(
                attrs={"class": "form-control form-control-sm", "onchange": "form.submit()"},
                choices=get_available_users(request.user),
            ),
            initial=initial_view_as_user.id,
            label="Viewing for user"
        )


class EventNameFilterForm(forms.Form):
    def __init__(self, **kwargs):
        track = kwargs.pop("track")
        super().__init__(**kwargs)
        self.fields["event_name"] = forms.ChoiceField(
            choices=get_available_event_names(track),
            widget=forms.Select(
                attrs={"class": "ml-2 form-control form-control-sm", "onchange": "form.submit()"},
            ),
            label=''
        )
