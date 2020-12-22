from datetime import timedelta
from django import forms
from django.utils import timezone

from .models import Event, GiftVoucherConfig, BlockVoucher


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


class GiftVoucherForm(forms.Form):

    voucher_type = forms.ModelChoiceField(
        label="Voucher for:",
        queryset=GiftVoucherConfig.objects.filter(active=True),
        widget=forms.Select(attrs={"class": "form-control"})
    )
    user_email = forms.EmailField(
        label="Email address:",
        widget=forms.TextInput(attrs={"class": "form-control"})
    )
    user_email1 = forms.EmailField(
        label="Confirm email address:",
        widget=forms.TextInput(attrs={"class": "form-control"})
    )
    recipient_name = forms.CharField(
        label="Recipient name to display on voucher (optional):",
        widget=forms.TextInput(attrs={"class": "form-control"}),
        required=False
    )
    message = forms.CharField(
        label="Message to display on voucher (optional):",
        widget=forms.Textarea(attrs={"class": "form-control", 'rows': 4}),
        required=False,
        max_length=500,
        help_text="Max 500 characters"
    )

    def __init__(self, **kwargs):
        user = kwargs.pop("user", None)
        instance = kwargs.pop("instance", None)
        super().__init__(**kwargs)
        if instance:
            self.instance = instance
            self.fields["user_email"].initial = instance.purchaser_email
            self.fields["user_email1"].initial = instance.purchaser_email

            if instance.activated:
                self.fields["voucher_type"].disabled = True
                self.fields["user_email"].disabled = True
                self.fields["user_email1"].disabled = True

            self.fields["voucher_type"].initial = GiftVoucherConfig.objects.get(block_config=instance.block_configs.first()).id

            self.fields["recipient_name"].initial = instance.name
            self.fields["message"].initial = instance.message
        elif user:
            self.fields["user_email"].initial = user.email
            self.fields["user_email1"].initial = user.email

    def clean_user_email(self):
        return self.cleaned_data.get('user_email').strip()

    def clean_user_email1(self):
        return self.cleaned_data.get('user_email1').strip()

    def clean(self):
        user_email = self.cleaned_data["user_email"]
        user_email1 = self.cleaned_data["user_email1"]
        if user_email != user_email1:
            self.add_error("user_email1", "Email addresses do not match")
