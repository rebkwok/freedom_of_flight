from datetime import timedelta
from django import forms
from django.utils import timezone

from crispy_forms.bootstrap import InlineCheckboxes, AppendedText, PrependedText
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Button, Layout, Submit, Row, Column, Field, Fieldset, Hidden, HTML

from .models import Event, GiftVoucher, GiftVoucherConfig


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


class GiftVoucherForm(forms.ModelForm):

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

    class Meta:
        model = GiftVoucher
        fields = ("gift_voucher_config",)

    def __init__(self, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(**kwargs)

        self.fields["gift_voucher_config"].queryset = GiftVoucherConfig.objects.filter(active=True)
        self.fields["gift_voucher_config"].label = "Select gift voucher type:"

        if self.instance.id:
            voucher = self.instance.block_voucher or self.instance.total_voucher
            self.fields["user_email"].initial = voucher.purchaser_email
            self.fields["user_email1"].initial = voucher.purchaser_email
            if voucher.activated:
                self.fields["gift_voucher_config"].disabled = True
                self.fields["user_email"].disabled = True
                self.fields["user_email1"].disabled = True
            self.fields["recipient_name"].initial = voucher.name
            self.fields["message"].initial = voucher.message
        elif user:
            self.fields["user_email"].initial = user.email
            self.fields["user_email1"].initial = user.email
            self.fields["user_email"].disabled = True
            self.fields["user_email1"].disabled = True

        self.helper = FormHelper()
        if self.instance.id:
            submit_button = Submit('submit', 'Update')
        else:
            submit_button = Submit('submit', 'Add to cart') if user is not None else Submit('submit', 'Checkout as guest')

        self.helper.layout = Layout(
            "gift_voucher_config",
            "user_email",
            "user_email1",
            "recipient_name",
            "message",
            submit_button
        )

    def clean_user_email(self):
        return self.cleaned_data.get('user_email').strip()

    def clean_user_email1(self):
        return self.cleaned_data.get('user_email1').strip()

    def clean(self):
        user_email = self.cleaned_data["user_email"]
        user_email1 = self.cleaned_data["user_email1"]
        if user_email != user_email1:
            self.add_error("user_email1", "Email addresses do not match")

    def save(self, commit=True):
        gift_voucher = super(GiftVoucherForm, self).save(commit=commit)
        if commit:
            voucher = gift_voucher.block_voucher or gift_voucher.total_voucher
            voucher.name = self.cleaned_data["recipient_name"]
            voucher.message = self.cleaned_data["message"]
            voucher.purchaser_email = self.cleaned_data["user_email"]
            voucher.save()
        return gift_voucher