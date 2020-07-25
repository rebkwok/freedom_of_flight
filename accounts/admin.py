from decimal import Decimal
import json
from math import floor

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django import forms
from django.utils.html import mark_safe, format_html

from accounts.models import OnlineDisclaimer, DisclaimerContent, ArchivedDisclaimer, \
    CookiePolicy, DataPrivacyPolicy, SignedDataPrivacy, NonRegisteredDisclaimer, UserProfile, ChildUserProfile


class OnlineDisclaimerAdmin(admin.ModelAdmin):

    readonly_fields = (
        'user',
        'emergency_contact_name',
        'emergency_contact_relationship', 'emergency_contact_phone',
        'health_questionnaire',
        'date', 'date_updated', 'terms_accepted', 'version'
    )
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def health_questionnaire(self, obj):
        responses = []
        for question, response in obj.health_questionnaire_responses.items():
            if isinstance(response, list):
                response = ", ".join(response)
            responses.append(f"<strong>{question}</strong><br/>{response}")
        return format_html(mark_safe("<br/>".join(responses)))

class NonRegisteredDisclaimerAdmin(admin.ModelAdmin):

    readonly_fields = (
        'first_name', 'last_name', 'email', 'date', 'date_of_birth', 'address', 'postcode', 'phone',
        'emergency_contact_name',
        'emergency_contact_relationship', 'emergency_contact_phone', 'health_questionnaire',
        'terms_accepted',
        'version'
    )
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def health_questionnaire(self, obj):
        responses = []
        for question, response in obj.health_questionnaire_responses.items():
            if isinstance(response, list):
                response = ", ".join(response)
            responses.append(f"<strong>{question}</strong><br/>{response}")
        return format_html(mark_safe("<br/>".join(responses)))


class PolicyAdminFormMixin:

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.PolicyModel = self._meta.model
        self.fields['content'].widget = forms.Textarea()
        self.fields['version'].required = False
        if not self.instance.id:
            current_policy = self.PolicyModel.current()
            if current_policy:
                self.fields['content'].initial = current_policy.content
                self.fields['version'].help_text = 'Current version is {}.  Leave ' \
                                           'blank for next major ' \
                                           'version'.format(current_policy.version)
            else:
                self.fields['version'].initial = 1.0

    def clean_version(self):
        # blank is OK, it'll get auto-generated to the next major version
        form_version = self.cleaned_data.get("version")
        if form_version:
            current_version = self.PolicyModel.current_version()
            if form_version <= current_version:
                self.add_error("version", "Must increment previous version")
                return
        return form_version

    def clean(self):
        new_content = self.cleaned_data.get('content')

        # check content has changed
        current_policy = self.PolicyModel.current()
        if current_policy and current_policy.content == new_content:
            self.add_error(
                None, 'No changes made from previous version; '
                      'new version must update policy content'
            )


class CookiePolicyAdminForm(PolicyAdminFormMixin, forms.ModelForm):

    class Meta:
        model = CookiePolicy
        fields = '__all__'


class DataPrivacyPolicyAdminForm(PolicyAdminFormMixin, forms.ModelForm):

    class Meta:
        model = DataPrivacyPolicy
        fields = '__all__'


class DisclaimerContentAdminForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['version'].required = False
        if not self.instance.id:
            current_content = DisclaimerContent.current()
            if current_content:
                self.fields['disclaimer_terms'].initial = current_content.disclaimer_terms
                self.fields['form'].initial = current_content.form
                next_default_version = Decimal(floor((DisclaimerContent.current_version() + 1)))
                self.fields['version'].help_text = f'Current version is {current_content.version}.  Leave ' \
                                           f'blank for next major version ({next_default_version:.1f})'
            else:
                self.fields['version'].initial = 1.0

    def clean_version(self):
        version = self.cleaned_data.get('version')
        current_version = DisclaimerContent.current_version()
        if version is None or version > current_version:
            return version
        self.add_error('version', f'New version must increment current version (must be greater than {current_version})')

    def clean(self):
        new_disclaimer_terms = self.cleaned_data.get('disclaimer_terms')
        new_health_questionnaire = self.cleaned_data.get('form')

        # check content has changed
        current_content = DisclaimerContent.current()
        if current_content and current_content.disclaimer_terms == new_disclaimer_terms:
            if current_content.form == json.loads(new_health_questionnaire):
                self.add_error(
                    None, 'No changes made from previous version; new version must update disclaimer content'
                )

    class Meta:
        model = DisclaimerContent
        fields = '__all__'


class CookiePolicyAdmin(admin.ModelAdmin):
    readonly_fields = ('issue_date',)
    form = CookiePolicyAdminForm


class DataPrivacyPolicyAdmin(admin.ModelAdmin):
    readonly_fields = ('issue_date',)
    form = DataPrivacyPolicyAdminForm


class SignedDataPrivacyAdmin(admin.ModelAdmin):
    readonly_fields = ('user', 'date_signed', 'version')


class DisclaimerContentAdmin(admin.ModelAdmin):
    readonly_fields = ('issue_date',)
    form = DisclaimerContentAdminForm


# which acts a bit like a singleton
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False


class ChildProfileInline(admin.StackedInline):
    model = ChildUserProfile
    can_delete = False


# Define a new User admin
class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline, ChildProfileInline,)


# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)


admin.site.register(OnlineDisclaimer, OnlineDisclaimerAdmin)
admin.site.register(DataPrivacyPolicy, DataPrivacyPolicyAdmin)
admin.site.register(CookiePolicy, CookiePolicyAdmin)
admin.site.register(SignedDataPrivacy, SignedDataPrivacyAdmin)
admin.site.register(NonRegisteredDisclaimer, NonRegisteredDisclaimerAdmin)
admin.site.register(DisclaimerContent, DisclaimerContentAdmin)
admin.site.register(ArchivedDisclaimer)
