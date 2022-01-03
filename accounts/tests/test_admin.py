from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.urls import reverse

from model_bakery import baker
import pytest

from accounts.admin import OnlineDisclaimerAdmin, NonRegisteredDisclaimerAdmin
from accounts.models import OnlineDisclaimer, NonRegisteredDisclaimer, UserProfile, \
    DisclaimerContent, DataPrivacyPolicy
from common.test_utils import make_online_disclaimer, make_nonregistered_disclaimer, \
    make_disclaimer_content


@pytest.mark.django_db
def test_online_disclaimer_admin_name():
    admin = OnlineDisclaimerAdmin(OnlineDisclaimer, AdminSite())
    user = baker.make(User, first_name="test", last_name="user")
    disc = make_online_disclaimer(user=user)
    assert admin.name(disc) == "test user"


@pytest.mark.django_db
def test_online_disclaimer_admin_permissions():
    admin = OnlineDisclaimerAdmin(OnlineDisclaimer, AdminSite())
    user = baker.make(User, first_name="test", last_name="user")
    disc = make_online_disclaimer(user=user)
    assert admin.has_add_permission(disc) is False
    assert admin.has_delete_permission(disc) is False
    assert admin.has_change_permission(disc) is False


@pytest.mark.django_db
def test_online_disclaimer_admin_health_questionnaire():
    admin = OnlineDisclaimerAdmin(OnlineDisclaimer, AdminSite())
    user = baker.make(User, first_name="test", last_name="user")
    disc = make_online_disclaimer(
        user=user,
        health_questionnaire_responses={
            "Say something": "OK",
            'What is your favourite colour?': ["blue"]
        }
    )
    assert admin.health_questionnaire(disc) == (
        "<strong>Say something</strong><br/>OK<br/>"
        "<strong>What is your favourite colour?</strong><br/>blue"
    )


@pytest.mark.django_db
def test_non_registered_disclaimer_admin_permissions():
    admin = NonRegisteredDisclaimerAdmin(NonRegisteredDisclaimer, AdminSite())
    disc = make_nonregistered_disclaimer()
    assert admin.has_add_permission(disc) is False
    assert admin.has_delete_permission(disc) is False
    assert admin.has_change_permission(disc) is False


@pytest.mark.django_db
def test_non_registered_disclaimer_admin_health_questionnaire():
    admin = NonRegisteredDisclaimerAdmin(NonRegisteredDisclaimer, AdminSite())
    disc = make_nonregistered_disclaimer(
        health_questionnaire_responses={
            "Say something": "OK",
            'What is your favourite colour?': ["blue"]
        }
    )
    assert admin.health_questionnaire(disc) == (
        "<strong>Say something</strong><br/>OK<br/>"
        "<strong>What is your favourite colour?</strong><br/>blue"
    )


def test_clean_disclaimer_content_version(client, admin_user):
    UserProfile.objects.create(user=admin_user)
    client.login(username="admin", password="password")
    content = make_disclaimer_content()
    assert content.version == 1.0
    assert DisclaimerContent.objects.count() == 1
    url = reverse("admin:accounts_disclaimercontent_add")
    data = {
        "form_title": "Health Questionnaire", "form": "[]", "form_info": "",
        "disclaimer_terms": "test", "save_draft": "Save as draft", "version": content.version
    }
    resp = client.post(url, data)
    assert resp.status_code == 200
    assert resp.context_data["adminform"].form.errors == {
        "version": ['New version must increment current version (must be greater than 1.0)']
    }

    data["version"] += 0.1
    resp = client.post(url, data)
    assert resp.status_code == 302

    assert DisclaimerContent.objects.count() == 2
    latest_content = DisclaimerContent.objects.latest("id")
    assert float(latest_content.version) == 1.1


def test_clean_data_privacy_version(client, admin_user):
    UserProfile.objects.create(user=admin_user)
    client.login(username="admin", password="password")
    policy = baker.make(DataPrivacyPolicy, version=None)
    assert policy.version == 1.0
    assert DataPrivacyPolicy.objects.count() == 1
    url = reverse("admin:accounts_dataprivacypolicy_add")
    data = {
        "content": "new", "version": policy.version
    }
    resp = client.post(url, data)
    assert resp.status_code == 200
    assert resp.context_data["adminform"].form.errors == {
        "version": ['Must increment previous version']
    }

    data["version"] += 0.1
    resp = client.post(url, data)
    assert resp.status_code == 302

    assert DataPrivacyPolicy.objects.count() == 2
    latest_policy = DataPrivacyPolicy.objects.latest("id")
    assert float(latest_policy.version) == 1.1
