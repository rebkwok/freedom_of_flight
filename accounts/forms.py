from copy import deepcopy
from datetime import datetime

from django import forms
from django.contrib.auth.password_validation import get_password_validators, password_validators_help_text_html
from django.utils.html import mark_safe, linebreaks
from django.utils import timezone

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Button, Layout, Submit, Row, Column, Field, Fieldset, Hidden, HTML

from accounts import validators as account_validators
from .models import DataPrivacyPolicy, SignedDataPrivacy, OnlineDisclaimer, UserProfile, \
    DisclaimerContent, has_expired_disclaimer, NonRegisteredDisclaimer, ChildUserProfile


class AccountFormMixin:

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"] = forms.CharField(
            max_length=30, label='First name',
            widget=forms.TextInput(
                attrs={
                    'class': "form-control", 'placeholder': 'First name',
                    'autofocus': 'autofocus'
                }
            )
        )
        self.fields["last_name"] = forms.CharField(
            max_length=30, label='Last name',
            widget=forms.TextInput(
                attrs={'class': "form-control", 'placeholder': 'Last name'}
            )
        )
        self.fields["date_of_birth"] = forms.DateField(
            widget=forms.DateInput(attrs={"autocomplete": "off"}, format='%d-%b-%Y'), input_formats=['%d-%b-%Y'],
        )
        self.fields["address"] = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control'}))
        self.fields["postcode"] = forms.CharField(max_length=10, widget=forms.TextInput(attrs={'class': 'form-control'}))
        self.fields["phone"] = forms.CharField(max_length=20, widget=forms.TextInput(attrs={'class': 'form-control'}))
        self.fields["phone"].validators = [account_validators.phone_number_validator]


class CoreAccountFormMixin:

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["student"] = forms.BooleanField(
            widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            label="Tick if you are registering as a student yourself",
            required=False,
        )
        self.fields["manager"] = forms.BooleanField(
            widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            label="Tick if you will manage child account(s)",
            help_text="You'll be able to add managed accounts on the next page.",
            required=False,
        )


class SignupForm(CoreAccountFormMixin, AccountFormMixin, forms.Form):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # get the current version here to make sure we always display and save
        # with the same version, even if it changed while the form was being
        # completed
        if "email" in self.fields:  # it's not there in form tests
            self.fields['email'].widget.attrs.update({'autofocus': 'autofocus', "class": "form-control"})
        if DataPrivacyPolicy.current():
            self.data_privacy_policy = DataPrivacyPolicy.current()
            self.fields['data_privacy_confirmation'] = forms.BooleanField(
                widget=forms.CheckboxInput(attrs={'class': "form-check-input"}),
                required=True,
                label='I confirm I have read and agree to the terms of the data privacy policy'
            )
        self.password_help_text = password_validators_help_text_html()

    def signup(self, request, user):
        profile_data = self.cleaned_data.copy()
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.username = self.cleaned_data['email']
        user.save()

        non_profile_fields = [
            'first_name', 'last_name', 'password1', 'password2', 'username',
            'email', 'email2', 'data_privacy_confirmation', 'student', 'manager'
        ]
        for field in non_profile_fields:
            if field in profile_data:
                del profile_data[field]

        UserProfile.objects.create(user=user, **profile_data)

        if hasattr(self, 'data_privacy_policy'):
           SignedDataPrivacy.objects.create(
               user=user, version=self.data_privacy_policy.version,
               date_signed=timezone.now()
           )


class ProfileForm(CoreAccountFormMixin, AccountFormMixin, forms.ModelForm):

    first_name = forms.CharField(
        widget=forms.TextInput(attrs={'class': "form-control"}), required = True
    )
    last_name = forms.CharField(
        widget=forms.TextInput(attrs={'class': "form-control"}), required = True
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        self.fields['first_name'].initial = user.first_name
        self.fields['last_name'].initial = user.last_name

    class Meta:
        model = UserProfile
        fields = ("first_name", "last_name", "address", "postcode", "phone", "date_of_birth", "student", "manager")


class RegisterChildUserForm(AccountFormMixin, forms.ModelForm):
    first_name = forms.CharField(
        widget=forms.TextInput(attrs={'class': "form-control"}), required = True
    )
    last_name = forms.CharField(
        widget=forms.TextInput(attrs={'class': "form-control"}), required = True
    )

    def __init__(self, *args, **kwargs):
        parent_user_profile = kwargs.pop("parent_user_profile")
        super().__init__(*args, **kwargs)
        if not self.instance.id:
            # prepopulate fields from parent profile
            self.fields['address'].initial = parent_user_profile.address
            self.fields['postcode'].initial = parent_user_profile.postcode
            self.fields['phone'].initial = parent_user_profile.phone

    class Meta:
        model = ChildUserProfile
        fields = ("first_name", "last_name", "address", "postcode", "phone", "date_of_birth")


BASE_DISCLAIMER_FORM_WIDGETS = {
    'emergency_contact_name': forms.TextInput(attrs={'class': 'form-control', 'autofocus': 'autofocus'}),
    'emergency_contact_relationship': forms.TextInput(attrs={'class': 'form-control'}),
    'emergency_contact_phone': forms.TextInput(attrs={'class': 'form-control'}),
}


class DisclaimerForm(forms.ModelForm):

    terms_accepted = forms.BooleanField(
        validators=[account_validators.validate_confirm],
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Please tick to accept terms.'
    )
    password = forms.CharField(
        widget=forms.PasswordInput(),
        label="Please re-enter your password to confirm.",
        required=True
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('disclaimer_user', None)
        self.request_user = kwargs.pop('request_user')
        super().__init__(*args, **kwargs)

        if self.instance.id:
            self.disclaimer_content = DisclaimerContent.objects.get(version=self.instance.version)
        else:
            self.disclaimer_content = DisclaimerContent.current()
        self.fields["health_questionnaire_responses"].required = any(field.get("required") for field in self.disclaimer_content.form)
        self.fields["emergency_contact_phone"].validators = [account_validators.phone_number_validator]

        # in the DisclaimerForm, these fields are autopoulated
        self.disclaimer_terms = self.disclaimer_content.disclaimer_terms
        if user is not None:
            if has_expired_disclaimer(user):
                last_disclaimer = OnlineDisclaimer.objects.filter(user=user).last()
                # set initial on all fields except password and confirmation fields
                # to data from last disclaimer
                for field_name in self.fields:
                    if field_name not in ['terms_accepted', 'password']:
                        last_value = getattr(last_disclaimer, field_name)
                        self.fields[field_name].initial = last_value

        self.helper = FormHelper()
        self.helper.layout = Layout(
            HTML("<h3>Emergency Contact Information</h3>"),
            "emergency_contact_name",
            "emergency_contact_phone",
            "emergency_contact_relationship",
            HTML("<h3>Health Questionnaire</h3>") if self.disclaimer_content.form else "",
            "health_questionnaire_responses",
            HTML("<h3>Disclaimer Terms</h3>"),
            HTML(mark_safe(linebreaks(self.disclaimer_content.disclaimer_terms))),
            "terms_accepted",
            "password",
            Submit('submit', 'Save')
        )

    class Meta:
        model = OnlineDisclaimer
        fields = (
            'terms_accepted', 'emergency_contact_name',
            'emergency_contact_relationship', 'emergency_contact_phone', 'health_questionnaire_responses'
        )
        widgets = deepcopy(BASE_DISCLAIMER_FORM_WIDGETS)

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if self.request_user.check_password(password):
            return password
        self.add_error("password", "Invalid password entered")


class NonRegisteredDisclaimerForm(DisclaimerForm):

    confirm_name = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label="Please re-enter your first and last name to submit your data.<br/>"
              "By submitting this form, you confirm that "
              "the information you have provided is complete and accurate.",
        required=True,
    )

    class Meta:
        model = NonRegisteredDisclaimer

        fields = (
            'first_name', 'last_name', 'email', 'date_of_birth', 'address', 'postcode',
            'phone', 'emergency_contact_name', 'emergency_contact_relationship',
            'emergency_contact_phone', 'health_questionnaire_responses',
            'terms_accepted', 'event_date')

        widgets = deepcopy(BASE_DISCLAIMER_FORM_WIDGETS)
        widgets.update({
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'date_of_birth': forms.DateInput(attrs={'class': "form-control"}, format='%d-%b-%Y'),
            'event_date': forms.DateInput(attrs={'class': "form-control"}, format='%d-%b-%Y'),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'postcode': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
        })

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields['password']
        self.fields["phone"].validators = [account_validators.phone_number_validator]
        self.fields['event_date'].input_formats = ['%d-%b-%Y']
        self.fields['event_date'].help_text = "Please enter the date of the " \
                                              "event you will be attending.  This will help us " \
                                              "retrieve your disclaimer on the day."

        self.helper = FormHelper()
        self.helper.layout = Layout(
            HTML("<h3>Your details</h3>"),
            "first_name",
            "last_name",
            "email",
            "address",
            "postcode",
            "phone",
            "date_of_birth",
            "event_date",
            HTML("<h3>Emergency Contact Information</h3>"),
            "emergency_contact_name",
            "emergency_contact_phone",
            "emergency_contact_relationship",
            HTML("<h3>Health Questionnaire</h3>"),
            "health_questionnaire_responses",
            HTML("<h3>Disclaimer Terms</h3>"),
            HTML(mark_safe(linebreaks(self.disclaimer_content.disclaimer_terms))),
            "terms_accepted",
            "password",
            Submit('submit', 'Save')
        )

    def clean(self):
        cleaned_data = super().clean()
        first_name = cleaned_data['first_name']
        last_name = cleaned_data['last_name']
        confirm_name = cleaned_data['confirm_name'].strip()
        if confirm_name != '{} {}'.format(first_name, last_name):
            self.add_error(
                'confirm_name', 'Please enter your first and last name exactly as on '
                                'the form (case sensitive) to confirm.'
            )

        return cleaned_data


class DisclaimerContactUpdateForm(forms.ModelForm):

    class Meta:
        model = OnlineDisclaimer
        fields = (
            'emergency_contact_name', 'emergency_contact_relationship', 'emergency_contact_phone'
        )
        widgets = deepcopy(BASE_DISCLAIMER_FORM_WIDGETS)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["emergency_contact_phone"].validators = [account_validators.phone_number_validator]
        self.helper = FormHelper()
        self.helper.layout = Layout(
            "emergency_contact_name",
            "emergency_contact_phone",
            "emergency_contact_relationship",
            Submit('submit', 'Save', css_class="btn btn-success")
        )


class DataPrivacyAgreementForm(forms.Form):

    confirm = forms.BooleanField(
        widget=forms.CheckboxInput(attrs={'class': "regular-checkbox"}),
        required=False,
        label='I confirm I have read and agree to the terms of the data ' \
              'privacy policy'
    )

    def __init__(self, *args, **kwargs):
        self.next_url = kwargs.pop('next_url')
        super().__init__(*args, **kwargs)
        self.data_privacy_policy = DataPrivacyPolicy.current()

    def clean_confirm(self):
        confirm = self.cleaned_data.get('confirm')
        if not confirm:
            self.add_error('confirm', 'You must check this box to continue')
        return
