from datetime import timedelta
from model_bakery import baker

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from accounts.admin import CookiePolicyAdminForm, DataPrivacyPolicyAdminForm
from accounts.forms import DataPrivacyAgreementForm, SignupForm, DisclaimerForm
from accounts.models import CookiePolicy, DataPrivacyPolicy
from common.test_utils import (
    make_disclaimer_content, TestUsersMixin, make_online_disclaimer
)

class SignUpFormTests(TestUsersMixin, TestCase):

    base_form_data = {
        'first_name': 'Test',
        'last_name': 'User',
        'pronouns': 'they/them',
        'address': 'test',
        'postcode': 'test',
        'phone': '1234',
        'date_of_birth': '01-Jan-1990',
        "student": True,
        "manager": False,
        'data_privacy_confirmation' : True
    }

    def test_signup_form(self):
        # email and password are added by allauth, not tested here - test in views instead
        form = SignupForm(data=self.base_form_data)
        assert form.is_valid()

    def test_signup_form_with_invalid_data(self):
        # first_name must have 30 characters or fewer
        form_data = {
            **self.base_form_data,
            'first_name': 'abcdefghijklmnopqrstuvwxyz12345',
         }
        form = SignupForm(data=form_data)
        assert form.is_valid() is False

    def test_signup_dataprotection_confirmation_required(self):
        # no policy yet, no need to confirm
        assert DataPrivacyPolicy.objects.exists() is False
        form_data = {
            **self.base_form_data,
            'data_privacy_confirmation': False
        }
        form = SignupForm(data=form_data)
        assert form.is_valid()

        baker.make(DataPrivacyPolicy)
        form_data = {
            **self.base_form_data,
            'data_privacy_confirmation': False
        }
        form = SignupForm(data=form_data)
        assert form.is_valid() is False

    def test_must_be_over_16(self):
        form_data = {
            **self.base_form_data,
            'date_of_birth': (timezone.now() - timedelta(360*16)).strftime("%d-%b-%Y"),
        }
        form = SignupForm(data=form_data)
        assert form.is_valid() is False
        form_data = {
            **self.base_form_data,
            'date_of_birth': (timezone.now() - timedelta(366 * 16)).strftime("%d-%b-%Y"),
        }
        form = SignupForm(data=form_data)
        assert form.is_valid() is True

    def test_must_choose_role(self):
        form_data = {
            **self.base_form_data,
            'student': False, 'manager': False
        }
        form = SignupForm(data=form_data)
        assert form.is_valid() is False
        assert form.non_field_errors() == [
            "You must select at least one role: student or manager (or both)"
        ]


# class NonRegisteredDisclaimerFormTests(TestUsersMixin, TestCase):
#
#     def setUp(self):
#         super().setUp()
#         self.form_data = {
#             'first_name': 'test',
#             'last_name': 'user',
#             'email': 'test@test.com',
#             'event_date': '01 Mar 2019',
#             'dob': '01 Jan 1990', 'address': '1 test st',
#             'postcode': 'TEST1', 'home_phone': '123445', 'mobile_phone': '124566',
#             'emergency_contact1_name': 'test1',
#             'emergency_contact1_relationship': 'mother',
#             'emergency_contact1_phone': '4547',
#             'emergency_contact2_name': 'test2',
#             'emergency_contact2_relationship': 'father',
#             'emergency_contact2_phone': '34657',
#             'medical_conditions': False, 'medical_conditions_details': '',
#             'joint_problems': False, 'joint_problems_details': '',
#             'allergies': False, 'allergies_details': '',
#             'medical_treatment_permission': True,
#             'terms_accepted': True,
#             'age_over_18_confirmed': True,
#             'confirm_name': 'test user'
#         }
#
#     def test_no_password_field(self):
#         form = NonRegisteredDisclaimerForm()
#         self.assertNotIn('password', form.fields)
#
#     def test_disclaimer_form(self):
#         form = NonRegisteredDisclaimerForm(data=self.form_data)
#         self.assertTrue(form.is_valid())
#
#     def test_mismatched_confirm_name(self):
#         # name must match exactly, including case
#         self.form_data['confirm_name'] = 'Test user'
#         form = NonRegisteredDisclaimerForm(data=self.form_data)
#         self.assertFalse(form.is_valid())
#         self.assertEqual(
#             form.errors,
#             {
#                 'confirm_name':
#                     ['Please enter your first and last name exactly as on the form (case sensitive) to confirm.']
#             }
#         )
#
#         # surrounding whitespace is ignored
#         self.form_data['confirm_name'] = ' test user '
#         form = NonRegisteredDisclaimerForm(data=self.form_data)
#         self.assertTrue(form.is_valid())


class DataPrivacyAgreementFormTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = baker.make(User)
        baker.make(DataPrivacyPolicy)

    def test_confirm_required(self):
        form = DataPrivacyAgreementForm(next_url='/', data={})
        assert form.is_valid() is False

        form = DataPrivacyAgreementForm(next_url='/', data={"confirm": True})
        assert form.is_valid()


class CookiePolicyAdminFormTests(TestCase):

    def test_create_cookie_policy_version_help(self):
        form = CookiePolicyAdminForm()
        # version initial set to 1.0 for first policy
        assert form.fields['version'].help_text == ''
        assert form.fields['version'].initial == 1.0

        baker.make(CookiePolicy, version=1.0)
        # help text added if updating
        form = CookiePolicyAdminForm()
        assert form.fields['version'].help_text == 'Current version is 1.0.  Leave blank for next major version'
        assert form.fields['version'].initial is None

    def test_validation_error_if_no_changes(self):
        policy = baker.make(CookiePolicy, version=1.0, content='Foo')
        form = CookiePolicyAdminForm(
            data={
                'content': 'Foo',
                'version': 1.5,
                'issue_date': policy.issue_date
            }
        )
        assert form.is_valid() is False
        assert form.non_field_errors() == [
            'No changes made from previous version; new version must update policy content'
        ]


class DataPrivacyPolicyAdminFormTests(TestCase):

    def test_create_data_privacy_policy_version_help(self):
        form = DataPrivacyPolicyAdminForm()
        # version initial set to 1.0 for first policy
        assert form.fields['version'].help_text == ''
        assert form.fields['version'].initial == 1.0

        baker.make(DataPrivacyPolicy, version=1.0)
        # help text added if updating
        form = DataPrivacyPolicyAdminForm()
        assert form.fields['version'].help_text == 'Current version is 1.0.  Leave blank for next major version'
        assert form.fields['version'].initial is None

    def test_validation_error_if_no_changes(self):
        policy = baker.make(DataPrivacyPolicy, version=1.0, content='Foo')
        form = DataPrivacyPolicyAdminForm(
            data={
                'content': 'Foo',
                'version': 1.5,
                'issue_date': policy.issue_date
            }
        )
        assert form.is_valid() is False
        assert form.non_field_errors() == [
            'No changes made from previous version; new version must update policy content'
        ]
