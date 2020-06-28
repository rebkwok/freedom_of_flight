from datetime import datetime

from django import forms
from django.contrib.auth.models import User
from django.utils import timezone


from accounts import validators as account_validators
from .models import DataPrivacyPolicy, SignedDataPrivacy, OnlineDisclaimer, UserProfile, \
    DisclaimerContent, has_expired_disclaimer, NonRegisteredDisclaimer


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
            widget=forms.DateInput(
                    attrs={'class': "form-control", 'id': 'dobdatepicker', "autocomplete": "off"},
                    format='%d %b %Y'
                )
        )
        self.fields["address"] = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control'}))
        self.fields["postcode"] = forms.CharField(max_length=10, widget=forms.TextInput(attrs={'class': 'form-control'}))
        self.fields["phone"] = forms.CharField(max_length=20, widget=forms.TextInput(attrs={'class': 'form-control'}))
        self.fields["emergency_contact_name"] = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control'}))
        self.fields["emergency_contact_relationship"] = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control'}))
        self.fields["emergency_contact_phone"] = forms.CharField(max_length=20, widget=forms.TextInput(attrs={'class': 'form-control'}))

    def clean(self):
        dob = self.data.get('date_of_birth', None)
        if dob and self.errors.get('date_of_birth'):
            del self.errors['date_of_birth']
        if dob:
            try:
                dob = datetime.strptime(dob, '%d %b %Y').date()
                self.cleaned_data['date_of_birth'] = dob
            except ValueError:
                self.add_error(
                    'date_of_birth', 'Invalid date format.  Select from the date picker '
                           'or enter date in the format e.g. 08 Jun 1990')
        return self.cleaned_data

class SignupForm(AccountFormMixin, forms.Form):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # get the current version here to make sure we always display and save
        # with the same version, even if it changed while the form was being
        # completed
        self.fields['email'].widget.attrs.update({'autofocus': 'autofocus', "class": "form-control"})
        if DataPrivacyPolicy.current():
            self.data_privacy_policy = DataPrivacyPolicy.current()
            self.fields['data_privacy_confirmation'] = forms.BooleanField(
                widget=forms.CheckboxInput(attrs={'class': "regular-checkbox"}),
                required=False,
                label='I confirm I have read and agree to the terms of the data ' \
                      'privacy policy'
            )

    def clean_data_privacy_confirmation(self):
        dp = self.cleaned_data.get('data_privacy_confirmation')
        if not dp:
            self.add_error(
               'data_privacy_confirmation',
               'You must check this box to continue'
            )
        else:
            return dp

    def signup(self, request, user):
        profile_data = self.cleaned_data.copy()
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.username = self.cleaned_data['email']
        user.save()

        non_profile_fields = [
            'first_name', 'last_name', 'password1', 'password2', 'username',
            'email', 'email2', 'data_privacy_confirmation'
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


class ProfileForm(AccountFormMixin, forms.ModelForm):

    first_name = forms.CharField(
        widget=forms.TextInput(attrs={'class': "form-control"}), required = True
    )
    last_name = forms.CharField(
        widget=forms.TextInput(attrs={'class': "form-control"}), required = True
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        self.fields['date_of_birth'].initial = self.instance.date_of_birth.strftime('%d %b %Y')
        self.fields['first_name'].initial = user.first_name
        self.fields['last_name'].initial = user.last_name

    class Meta:
        model = UserProfile
        fields = ("first_name", "last_name", "address", "postcode", "phone", "date_of_birth",
                  "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relationship")


class DisclaimerForm(forms.ModelForm):

    terms_accepted = forms.BooleanField(
        validators=[account_validators.validate_confirm],
        required=False,
        widget=forms.CheckboxInput(
            attrs={'class': 'regular-checkbox'}
        ),
        label='Please tick to accept terms.'
    )
    password = forms.CharField(
        widget=forms.PasswordInput(),
        label="Please re-enter your password to confirm and submit.",
        required=True
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user')
        super().__init__(*args, **kwargs)

        if self.instance.id:
            self.disclaimer_content = DisclaimerContent.objects.get(version=self.instance.version)
        else:
            self.disclaimer_content = DisclaimerContent.current()
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
                        if field_name == 'date_of_birth':
                            last_value = last_value.strftime('%d %b %Y')
                        self.fields[field_name].initial = last_value

    class Meta:
        model = OnlineDisclaimer
        fields = ('terms_accepted',)

    def clean(self):
        dob = self.data.get('date_of_birth', None)
        if dob and self.errors.get('date_of_birth'):
            del self.errors['date_of_birth']
        if dob:
            try:
                dob = datetime.strptime(dob, '%d %b %Y').date()
                self.cleaned_data['date_of_birth'] = dob
            except ValueError:
                self.add_error(
                    'date_of_birth', 'Invalid date format.  Select from '
                                        'the date picker or enter date in the '
                                        'format e.g. 08 Jun 1990')
        return super().clean()


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
            'emergency_contact_phone',
            'terms_accepted', 'event_date')

        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'date_of_birth': forms.DateInput(attrs={'class': "form-control",'id': 'dobdatepicker',},format='%d %b %Y'),
            'event_date': forms.DateInput(attrs={'class': "form-control",'id': 'eventdatepicker',},format='%d %b %Y'),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'postcode': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'emergency_contact_name': forms.TextInput(attrs={'class': 'form-control'}),
            'emergency_contact_relationship': forms.TextInput(attrs={'class': 'form-control'}),
            'emergency_contact_phone': forms.TextInput(attrs={'class': 'form-control'}),
        }


    def __init__(self, *args, **kwargs):
        kwargs['user'] = None
        super().__init__(*args, **kwargs)
        del self.fields['password']
        self.fields['event_date'].help_text = "Please enter the date of the " \
                                              "event you will be attending.  This will help us " \
                                              "retrieve your disclaimer on the day."

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

        event_date = self.data.get('event_date', None)
        if event_date and self.errors.get('event_date'):
            del self.errors['event_date']
        if event_date:
            try:
                event_date = datetime.strptime(event_date, '%d %b %Y').date()
                self.cleaned_data['event_date'] = event_date
            except ValueError:
                self.add_error(
                    'event_date', 'Invalid date format.  Select from '
                                        'the date picker or enter date in the '
                                        'format e.g. 08 Jun 1990')

        return cleaned_data


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
