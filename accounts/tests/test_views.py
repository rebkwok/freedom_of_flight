from datetime import timedelta
from model_bakery import baker
import pytest

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from ..models import DataPrivacyPolicy, OnlineDisclaimer, has_active_data_privacy_agreement, UserProfile
from common.test_utils import (
    make_disclaimer_content, TestUsersMixin, make_online_disclaimer
)


def _signup_form_data():
    return {
        'first_name': 'Test',
        'last_name': 'User',
        'address': 'test',
        'postcode': 'test',
        'phone': '1234',
        'date_of_birth': '01-Jan-1990',
        "student": True,
        "manager": False,
        'data_privacy_confirmation': True,
        "email": "testuser@test.com",
        "email2": "testuser@test.com",
        "password1": "foo123456",
        "password2": "foo123456"
    }

@pytest.mark.django_db
def test_signup(client):
    # signup creates user and userprofile
    url = reverse("account_signup")
    assert User.objects.exists() is False
    client.post(url, _signup_form_data())

    assert User.objects.count() == 1
    assert UserProfile.objects.count() == 1
    new_user = User.objects.first()
    assert new_user.username == "testuser@test.com"


@pytest.mark.django_db
def test_signup_with_data_privacy_policy(client):
    # signup creates user and userprofile, and dataprivacy policy if there is one
    baker.make(DataPrivacyPolicy, content="foo")
    url = reverse("account_signup")
    assert User.objects.exists() is False
    client.post(url, _signup_form_data())

    assert User.objects.count() == 1
    assert UserProfile.objects.count() == 1
    new_user = User.objects.first()
    assert new_user.username == "testuser@test.com"
    assert has_active_data_privacy_agreement(new_user)


class ProfileUpdateViewTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super(ProfileUpdateViewTests, cls).setUpTestData()
        cls.url = reverse('accounts:update_profile')
        cls.group, _ = Group.objects.get_or_create(name='subscribed')

    def setUp(self):
        self.create_users()

    def test_updating_user_data(self):
        """
        Test custom view to allow users to update their details
        """
        self.login(self.student_user)
        resp = self.client.post(
            self.url,
            {
                'username': self.student_user.username,
                'first_name': 'Fred',
                'last_name': self.student_user.last_name,
                "address": self.student_user.userprofile.address,
                "postcode": self.student_user.userprofile.postcode,
                "phone": self.student_user.userprofile.phone,
                "date_of_birth": "15-Jun-1976",
                "student": True,
                "manager": False,
            }
        )
        self.student_user.refresh_from_db()
        assert self.student_user.first_name == "Fred"


class ChildUserCreateViewTests(TestUsersMixin, TestCase):
    def setUp(self):
        self.create_users()
        self.content = make_disclaimer_content()
        self.url = reverse('accounts:register_child_user')
        self.login(self.manager_user)

    def test_add_child(self):
        self.client.post(
            self.url,
            {
                'first_name': 'Bugs',
                'last_name': "Bunny",
                "address": self.manager_user.userprofile.address,
                "postcode": self.manager_user.userprofile.postcode,
                "phone": self.manager_user.userprofile.phone,
                "date_of_birth": "15-Jun-2000",
            }
        )
        child_user = User.objects.get(first_name="Bugs")
        assert child_user.email == ""
        assert child_user.manager_user == self.manager_user
        assert child_user.is_student is True


class ProfileTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.content = make_disclaimer_content()
        self.url = reverse('accounts:profile')

    def test_profile_view(self):
        self.login(self.student_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 200

    def test_profile_view_shows_disclaimer_info(self):
        self.login(self.student_user)
        # no disclaimer yet
        resp = self.client.get(self.url)
        assert "Add new disclaimer" in str(resp.content)
        assert "/accounts/disclaimer" in str(resp.content)

        self.make_disclaimer(self.student_user)
        resp = self.client.get(self.url)
        assert "Completed" in str(resp.content)
        assert "Add new disclaimer" not in str(resp.content)
        assert "/accounts/disclaimer" not in str(resp.content)

    def test_profile_view_shows_managed_user_disclaimer_info(self):
        self.login(self.manager_user)
        # no disclaimer yet
        resp = self.client.get(self.url)
        assert "Add new disclaimer" in str(resp.content)
        assert "/accounts/disclaimer" in str(resp.content)

        self.make_disclaimer(self.child_user)
        resp = self.client.get(self.url)
        assert "Completed" in str(resp.content)
        assert "Add new disclaimer" not in str(resp.content)
        assert "/accounts/disclaimer" not in str(resp.content)


class DisclaimerCreateViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.content = make_disclaimer_content(
            form=[{"label": "test", "type": "text"}]
        )
        self.form_data = {
            "date_of_birth": '01-Jan-1990', 'address': '1 test st',
            'postcode': 'TEST1', 'home_phone': '123445', 'mobile_phone': '124566',
            'emergency_contact_name': 'test1',
            'emergency_contact_relationship': 'mother',
            'emergency_contact_phone': '4547',
            'terms_accepted': True,
            'health_questionnaire_responses_0': ["foo"],
            'password': 'test'
        }

    def test_login_required(self):
        url = reverse('accounts:disclaimer_form', args=(self.student_user.id,))
        resp = self.client.get(url)
        redirected_url = reverse('account_login') + "?next={}".format(url)

        assert resp.status_code == 302
        assert redirected_url in resp.url

    def test_shows_msg_if_already_has_disclaimer(self):
        self.login(self.student_user)
        make_online_disclaimer(user=self.student_user, version=self.content.version)
        url = reverse('accounts:disclaimer_form', args=(self.student_user.id,))
        # user has disclaimer and gets redirected
        resp = self.client.get(url)
        assert resp.status_code == 302
        assert resp.url == reverse("accounts:profile")

    def test_submitting_form_without_valid_password(self):
        cache.clear()
        assert OnlineDisclaimer.objects.count() == 0
        url = reverse('accounts:disclaimer_form', args=(self.student_user.id,))
        self.login(self.student_user)
        resp = self.client.post(url, {**self.form_data, "password": "wrong"})
        form = resp.context_data["form"]
        assert form.errors == {"password": ['Invalid password entered']}

    def test_phone_number_validation(self):
        self.login(self.student_user)
        assert OnlineDisclaimer.objects.count() == 0
        url = reverse('accounts:disclaimer_form', args=(self.student_user.id,))
        resp = self.client.post(url, {**self.form_data, "emergency_contact_phone": 'test'})
        form = resp.context_data["form"]
        assert form.errors == {"emergency_contact_phone": ['Enter a valid phone number (no dashes or brackets).']}

    def test_disclaimer_health_questionnaire(self):
        # Make new disclaimer version with questionnaire - this should be the new current version
        make_disclaimer_content(
            form=[
                    {
                        'type': 'text',
                        'required': False,
                        'label': 'Say something',
                        'name': 'text-1',
                        'subtype': 'text'
                    },
                    {
                        'type': 'text',
                        'required': True,
                        'label': 'What is your favourite colour?',
                        'name': 'text-2',
                        'choices': ["red", "green", "blue"],
                        'subtype': 'text'
                    }
                ],
            version=None
        )
        self.login(self.student_user)
        url = reverse('accounts:disclaimer_form', args=(self.student_user.id,))
        resp = self.client.get(url)
        form = resp.context_data["form"]
        # disclaimer content questionnaire fields have been translated into form fields
        questionnaire_fields = form.fields['health_questionnaire_responses'].fields
        assert questionnaire_fields[0].label == "Say something"
        # text field initial is set to "-"
        assert questionnaire_fields[0].initial == "-"
        assert questionnaire_fields[1].label == "What is your favourite colour?"

    def test_submitting_form_checks_logged_in_user_password(self):
        cache.clear()
        assert OnlineDisclaimer.objects.count() == 0

        # student_user1's password is unusable
        self.student_user1.set_unusable_password()
        assert self.student_user1.check_password("test") is False
        url = reverse('accounts:disclaimer_form', args=(self.student_user1.id,))
        # Login student_user, who does have valid password
        assert self.student_user.check_password("test") is True
        self.login(self.student_user)

        resp = self.client.post(url, {**self.form_data, "password": "wrong"})
        assert resp.status_code == 200
        form = resp.context_data["form"]
        assert form.errors == {"password": ['Invalid password entered']}

        resp = self.client.post(url, {**self.form_data, "password": "test"})
        assert resp.status_code == 302

    def test_submitting_form_creates_disclaimer(self):
        cache.clear()
        assert OnlineDisclaimer.objects.count() == 0
        url = reverse('accounts:disclaimer_form', args=(self.student_user.id,))
        self.login(self.student_user)
        self.client.post(url, self.form_data)

        assert OnlineDisclaimer.objects.count() == 1

        # user now has disclaimer and gets redirected
        resp = self.client.get(url)
        assert resp.status_code == 302
        assert resp.url == reverse("accounts:profile")

    def test_post_form_with_already_active_disclaimer(self):
        cache.clear()
        url = reverse('accounts:disclaimer_form', args=(self.student_user.id,))
        self.login(self.student_user)
        make_online_disclaimer(user=self.student_user, version=self.content.version)
        resp = self.client.post(url, self.form_data)
        assert resp.status_code == 302
        assert resp.url == reverse("accounts:profile")

    def test_disclaimer_health_questionnaire_required_fields(self):
        make_disclaimer_content(
            form=[
                    {
                        'type': 'text',
                        'required': False,
                        'label': 'Say something',
                        'name': 'text-1',
                        'subtype': 'text'
                    },
                    {
                        'type': 'text',
                        'required': True,
                        'label': 'What is your favourite colour?',
                        'name': 'text-2',
                        'choices': ["red", "green", "blue"],
                        'subtype': 'text'
                    }
                ],
            version=None  # make sure it's the latest
        )
        self.login(self.student_user)
        url = reverse('accounts:disclaimer_form', args=(self.student_user.id,))
        # form data only has response for qn 0 (not required)
        resp = self.client.post(url, {**self.form_data})
        assert resp.status_code == 200
        form = resp.context_data["form"]
        assert form.errors == {"health_questionnaire_responses": ["Please fill in all required fields."]}

        form_data = {**self.form_data}
        del form_data["health_questionnaire_responses_0"]
        form_data["health_questionnaire_responses_1"] = "red"
        resp = self.client.post(url, {**form_data})
        assert resp.status_code == 302

    def test_updating_disclaimer_health_questionnaire(self):
        # health questionnaire fields that exist on the new disclaimer are prepopulated
        # skip choices fields that are different now
        # health form fields are extracted and set to expired disclaimer
        content_with_questionnaire = make_disclaimer_content(
            form=[
                    {
                        'type': 'text',
                        'required': False,
                        'label': 'Say something',
                        'name': 'text-1',
                        'subtype': 'text'
                    },
                    {
                        'type': 'select',
                        'required': True,
                        'label': 'What is your favourite colour?',
                        'name': 'text-2',
                        'values': [
                            {"label": "Red", "value": "red"},
                            {"label": "Green", "value": "green"},
                            {"label": "Blue", "value": "blue"},
                        ],
                        'subtype': 'text'
                    }
                ]
        )
        # make expired disclaimers with existing entries
        make_online_disclaimer(
            user=self.student_user, version=content_with_questionnaire.version,
            date=timezone.now() - timedelta(days=370),
            health_questionnaire_responses={
                "Say something": "OK",
                'What is your favourite colour?': ["blue"]
            }
        )
        make_online_disclaimer(
            user=self.student_user1, version=content_with_questionnaire.version,
            date=timezone.now() - timedelta(days=370),
            health_questionnaire_responses={
                "Say something": "Boo",
                'What is your favourite colour?': ["purple"]  # not in new disclaimer choices
            }
        )
        self.login(self.student_user)
        url = reverse('accounts:disclaimer_form', args=(self.student_user.id,))
        resp = self.client.get(url)
        form = resp.context_data["form"]
        # disclaimer content questionnaire fields have been prepopulated
        questionnaire_fields = form.fields['health_questionnaire_responses'].fields
        assert questionnaire_fields[0].initial == "OK"
        assert questionnaire_fields[1].initial == ["blue"]

        self.login(self.student_user1)
        url = reverse('accounts:disclaimer_form', args=(self.student_user1.id,))
        resp = self.client.get(url)
        form = resp.context_data["form"]
        # disclaimer content questionnaire fields have been prepopulated
        questionnaire_fields = form.fields['health_questionnaire_responses'].fields
        assert questionnaire_fields[0].initial == "Boo"
        assert questionnaire_fields[1].initial is None


class DisclaimerContactUpdateViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()

    def test_update_contact_info(self):
        self.login(self.student_user)
        make_online_disclaimer(
            user=self.student_user,
            emergency_contact_name='test1',
            emergency_contact_relationship="mother",
            emergency_contact_phone="4547"
        )
        assert self.student_user.online_disclaimer.first().emergency_contact_name == "test1"
        url = reverse('accounts:update_emergency_contact', args=(self.student_user.id,))
        self.client.post(
            url,
            dict(
                emergency_contact_name='test2',
                emergency_contact_relationship="father",
                emergency_contact_phone="6789"
            )
        )
        assert self.student_user.online_disclaimer.first().emergency_contact_name == "test2"


# class NonRegisteredDisclaimerCreateViewTests(TestUsersMixin, TestCase):
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
#         self.url = reverse('nonregistered_disclaimer_form')
#
#     def test_login_not_required(self):
#         resp = self.client.get(self.url)
#         resp.status_code = 200
#
#     def test_submitting_form_creates_disclaimer_and_redirects(self):
#         self.assertEqual(NonRegisteredDisclaimer.objects.count(), 0)
#         resp = self.client.post(self.url, self.form_data)
#         self.assertEqual(resp.status_code, 302)
#         self.assertEqual(resp.url, reverse('nonregistered_disclaimer_submitted'))
#
#         self.assertEqual(NonRegisteredDisclaimer.objects.count(), 1)
#         # email sent to email address in form
#         self.assertEqual(len(mail.outbox), 1)
#         self.assertEqual(mail.outbox[0].to, ['test@test.com'])


# class NonRegisteredDisclaimerSubmittedTests(TestCase):
#
#     def test_get_non_registered_disclaimer_submitted_view(self):
#         # no need to be a logged in user to access
#         resp = self.client.get(reverse('accounts:nonregistered_disclaimer_submitted'))
#         assert resp.status_code ==  200


class DataPrivacyViewTests(TestCase):

    def test_get_data_privacy_view(self):
        # no need to be a logged in user to access
        resp = self.client.get(reverse('accounts:data_privacy_policy'))
        assert resp.status_code == 200


class CookiePolicyViewTests(TestCase):

    def test_get_cookie_view(self):
        # no need to be a logged in user to access
        resp = self.client.get(reverse('accounts:cookie_policy'))
        assert resp.status_code == 200


class SignedDataPrivacyCreateViewTests(TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.url = reverse('accounts:data_privacy_review')
        cls.data_privacy_policy = baker.make(DataPrivacyPolicy, version=None)
        cls.subscribed, _ = Group.objects.get_or_create(name='subscribed')

    def setUp(self):
        self.create_users()
        self.login(self.student_user)
        self.make_data_privacy_agreement(self.student_user)

    def test_user_already_has_active_signed_agreement(self):
        # dp agreement is created in setup
        assert has_active_data_privacy_agreement(self.student_user) is True
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == reverse('booking:schedule')

        # make new policy
        baker.make(DataPrivacyPolicy, version=None)
        assert has_active_data_privacy_agreement(self.student_user) is False
        resp = self.client.get(self.url)
        assert resp.status_code == 200

    def test_create_new_agreement(self):
        # make new policy
        baker.make(DataPrivacyPolicy, version=None)
        assert has_active_data_privacy_agreement(self.student_user) is False

        self.client.post(self.url, data={'confirm': True})
        assert has_active_data_privacy_agreement(self.student_user) is True
