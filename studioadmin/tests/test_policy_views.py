# -*- coding: utf-8 -*-
from model_bakery import baker
import json
import pytest

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from accounts.models import CookiePolicy, DataPrivacyPolicy, DisclaimerContent
from common.test_utils import TestUsersMixin, make_disclaimer_content


class HelpViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse("studioadmin:help")

    def test_instructor_or_staff(self):
        self.user_access_test(["instructor", "staff"], self.url)


class CookiePolicyViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.list_url = reverse("studioadmin:cookie_policies")

    def test_list_view_staff_only(self):
        self.user_access_test(["staff"], self.list_url)

    def test_detail_view(self):
        policy = baker.make(CookiePolicy, version=1.0)
        resp = self.client.get(reverse("studioadmin:cookie_policy", args=(policy.version,)))
        assert resp.status_code == 200

    def test_add_policy_policy_type_context(self):
        resp = self.client.get(reverse("studioadmin:add_cookie_policy"))
        assert resp.context_data["policy_type"] == "Cookie Policy"

    def test_add_policy(self):
        CookiePolicy.objects.all().delete()
        self.client.post(
            reverse("studioadmin:add_cookie_policy"), {"content": "A new policy"}
        )
        assert CookiePolicy.objects.count() == 1
        assert CookiePolicy.current().content == "A new policy"

    def test_add_policy_no_content_change(self):
        baker.make(CookiePolicy, content="test", version=None)
        resp = self.client.post(
            reverse("studioadmin:add_cookie_policy"), {"content": "test"}
        )
        assert resp.context_data["form"].errors == {
            "__all__": ['No changes made from previous version; new version must update policy content']
        }


class DataPrivacyPolicyViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.list_url = reverse("studioadmin:data_privacy_policies")

    def test_list_view_staff_only(self):
        self.user_access_test(["staff"], self.list_url)

    def test_list_view_current_version(self):
        baker.make(DataPrivacyPolicy, content='Foo', version=None)
        baker.make(DataPrivacyPolicy, content='Bar', version=None)
        latest = baker.make(DataPrivacyPolicy, content='FooBar', version=None)
        assert DataPrivacyPolicy.current() == latest
        resp = self.client.get(self.list_url)
        assert resp.context_data["current_version"] == latest.version

    def test_detail_view(self):
        policy = baker.make(DataPrivacyPolicy, version=1.0)
        resp = self.client.get(reverse("studioadmin:data_privacy_policy", args=(policy.version,)))
        assert resp.status_code == 200

    def test_add_policy_policy_type_context(self):
        resp = self.client.get(reverse("studioadmin:add_data_privacy_policy"))
        assert resp.context_data["policy_type"] == "Data Privacy Policy"

    def test_add_policy(self):
        DataPrivacyPolicy.objects.all().delete()
        self.client.post(
            reverse("studioadmin:add_data_privacy_policy"), {"content": "A new policy"}
        )
        assert DataPrivacyPolicy.objects.count() == 1
        assert DataPrivacyPolicy.current().content == "A new policy"

    def test_add_policy_no_content_change(self):
        baker.make(DataPrivacyPolicy, content="test", version=None)
        resp = self.client.post(
            reverse("studioadmin:add_data_privacy_policy"), {"content": "test"}
        )
        assert resp.context_data["form"].errors == {
            "__all__": ['No changes made from previous version; new version must update policy content']
        }


class DisclaimerContentViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)
        self.form_default = {"form_title": "Health Questionnaire", "form": "[]", "form_info": ""}

    @classmethod
    def setUpTestData(cls):
        cls.list_url = reverse("studioadmin:disclaimer_contents")

    def test_list_view_staff_only(self):
        self.user_access_test(["staff"], self.list_url)

    def test_list_view_current_version(self):
        make_disclaimer_content(disclaimer_terms='Foo')
        make_disclaimer_content(disclaimer_terms='Bar')
        latest = make_disclaimer_content(disclaimer_terms='Foobar')
        assert DisclaimerContent.current() == latest
        resp = self.client.get(self.list_url)
        assert resp.context_data["current_version"] == latest.version

    def test_detail_view(self):
        policy = make_disclaimer_content(disclaimer_terms='Foo', version=4.1)
        resp = self.client.get(reverse("studioadmin:disclaimer_content", args=(policy.version,)))
        assert resp.status_code == 200

    def test_add_disclaimer_content_no_reset_button(self):
        resp = self.client.get(reverse("studioadmin:add_disclaimer_content"))
        assert "Reset to latest published version" not in resp.rendered_content

    def test_add_disclaimer_content(self):
        DisclaimerContent.objects.all().delete()
        self.client.post(
            reverse("studioadmin:add_disclaimer_content"),
            {**self.form_default, "disclaimer_terms": "A new policy", "publish": "Publish"}
        )
        assert DisclaimerContent.objects.count() == 1
        assert DisclaimerContent.current().disclaimer_terms == "A new policy"

    def test_add_disclaimer_content_no_content_change(self):
        make_disclaimer_content(disclaimer_terms='test', version=None)
        resp = self.client.post(
            reverse("studioadmin:add_disclaimer_content"), {**self.form_default, "disclaimer_terms": "test", "publish": "Publish"}
        )
        assert resp.context_data["form"].errors == {
            "__all__": ['No changes made from previous version; new version must update disclaimer content']
        }

    def test_add_disclaimer_content_save_as_draft(self):
        DisclaimerContent.objects.all().delete()
        self.client.post(
            reverse("studioadmin:add_disclaimer_content"), {**self.form_default, "disclaimer_terms": "test", "save_draft": "Save as draft"}
        )
        assert DisclaimerContent.objects.count() == 1
        disclaimer_content = DisclaimerContent.objects.first()
        assert disclaimer_content.is_draft is True
        assert DisclaimerContent.current_version() == 0

    def test_add_disclaimer_content_publish(self):
        DisclaimerContent.objects.all().delete()
        self.client.post(
            reverse("studioadmin:add_disclaimer_content"), {**self.form_default, "disclaimer_terms": "test", "publish": "Publish"}
        )
        assert DisclaimerContent.objects.count() == 1
        disclaimer_content = DisclaimerContent.objects.first()
        assert disclaimer_content.is_draft is False
        assert DisclaimerContent.current_version() == disclaimer_content.version

    def test_add_disclaimer_content_unknown_action(self):
        DisclaimerContent.objects.all().delete()
        with pytest.raises(ValidationError):
            self.client.post(
                reverse("studioadmin:add_disclaimer_content"), {**self.form_default, "disclaimer_terms": "test", "foo": "Foo"}
            )

    def test_edit_draft_version(self):
        DisclaimerContent.objects.all().delete()
        disclaimer_content = make_disclaimer_content(is_draft=True, disclaimer_terms="Foo", version=None)
        url = reverse("studioadmin:edit_disclaimer_content", args=(disclaimer_content.version,))
        resp = self.client.get(url)
        # no previous version to reset to
        assert "Reset to latest published version" not in resp.rendered_content
        assert resp.context_data["disclaimer_content"] == disclaimer_content

    def test_edit_published_version(self):
        disclaimer_content = make_disclaimer_content(is_draft=False, disclaimer_terms="Foo", version=None)
        url = reverse("studioadmin:edit_disclaimer_content", args=(disclaimer_content.version,))
        resp = self.client.get(url)
        # No other draft versions, redirect to list view
        assert resp.status_code == 302
        assert resp.url == reverse("studioadmin:disclaimer_contents")

        resp = self.client.get(url, follow=True)
        assert "Published disclaimer versions cannot be edited; make a new version if updates are required." in resp.rendered_content

    def test_edit_published_version_with_existing_draft(self):
        published_disclaimer_content = make_disclaimer_content(is_draft=False, disclaimer_terms="Foo", version=None)
        draft_disclaimer_content = make_disclaimer_content(is_draft=True, disclaimer_terms="Bar", version=None)
        url = reverse("studioadmin:edit_disclaimer_content", args=(published_disclaimer_content.version,))
        resp = self.client.get(url)
        # redirect to latest draft view
        assert resp.status_code == 302
        assert resp.url == reverse("studioadmin:edit_disclaimer_content", args=(draft_disclaimer_content.version,))

    def test_add_new_with_existing_draft(self):
        draft_disclaimer_content = make_disclaimer_content(is_draft=True, disclaimer_terms="Bar", version=None)
        resp = self.client.get(reverse("studioadmin:add_disclaimer_content"))
        # redirect to latest draft view
        assert resp.status_code == 302
        assert resp.url == reverse("studioadmin:edit_disclaimer_content", args=(draft_disclaimer_content.version,))
        resp = self.client.get(reverse("studioadmin:add_disclaimer_content"), follow=True)
        assert "Cannot add a new version while a draft already exists. Editing latest draft version" in resp.rendered_content

    def test_edit_disclaimer_content_save_as_draft(self):
        draft_disclaimer_content = make_disclaimer_content(is_draft=True, disclaimer_terms="Bar", version=None)
        url = reverse("studioadmin:edit_disclaimer_content", args=(draft_disclaimer_content.version,))
        self.client.post(
            url,
            {**self.form_default, "disclaimer_terms": "test", "save_draft": "Save as draft", "version": draft_disclaimer_content.version})
        draft_disclaimer_content.refresh_from_db()
        assert draft_disclaimer_content.is_draft is True
        assert DisclaimerContent.current_version() == 0

    def test_edit_disclaimer_content_form_invalid(self):
        published_disclaimer_content = make_disclaimer_content(is_draft=False, disclaimer_terms="Foo", version=None)
        draft_disclaimer_content = make_disclaimer_content(is_draft=True, disclaimer_terms="Bar", version=None)
        url = reverse("studioadmin:edit_disclaimer_content", args=(draft_disclaimer_content.version,))
        resp = self.client.post(
            url,
            {
                **self.form_default, "disclaimer_terms": "Foo", "form": json.dumps(published_disclaimer_content.form),
                "version": draft_disclaimer_content.version, "save_draft": "Save as draft"
            }
        )
        assert resp.status_code == 200
        assert resp.context_data["form_errors"] == {
            "__all__": ["No changes made from previous version; new version must update disclaimer content"]
        }
        draft_disclaimer_content.refresh_from_db()

    def test_edit_disclaimer_content_unknown_action(self):
        draft_disclaimer_content = make_disclaimer_content(is_draft=True, disclaimer_terms="Bar", version=None)
        url = reverse("studioadmin:edit_disclaimer_content", args=(draft_disclaimer_content.version,))
        with pytest.raises(ValidationError):
            self.client.post(
                url,
                {
                    **self.form_default, "disclaimer_terms": "test", "foo": "Foo", "version": draft_disclaimer_content.version}
            )

    def test_reset_draft(self):
        published_disclaimer_content = make_disclaimer_content(is_draft=False, disclaimer_terms="Foo", version=None)
        draft_disclaimer_content = make_disclaimer_content(is_draft=True, disclaimer_terms="Bar", version=None)
        url = reverse("studioadmin:edit_disclaimer_content", args=(draft_disclaimer_content.version,))
        resp = self.client.get(url)
        assert "Reset to latest published version" in resp.rendered_content
        resp = self.client.post(
            url,
            {
                **self.form_default,
                "reset": "Reset to latest published version",
                "disclaimer_terms": draft_disclaimer_content.disclaimer_terms,
                "form": json.dumps(draft_disclaimer_content.form),
                "version": draft_disclaimer_content.version,
            }
        )
        draft_disclaimer_content.refresh_from_db()
        assert draft_disclaimer_content.disclaimer_terms == published_disclaimer_content.disclaimer_terms
        # redirects back to edit page again
        assert resp.status_code == 302
        assert resp.url == reverse("studioadmin:edit_disclaimer_content", args=(draft_disclaimer_content.version,))

    def test_publish_draft(self):
        draft_disclaimer_content = make_disclaimer_content(is_draft=True, disclaimer_terms="Bar", version=None)
        url = reverse("studioadmin:edit_disclaimer_content", args=(draft_disclaimer_content.version,))
        self.client.post(
            url,
            {
                **self.form_default,
                "publish": "Publish",
                "disclaimer_terms": draft_disclaimer_content.disclaimer_terms,
                "form": json.dumps(draft_disclaimer_content.form),
                "version": draft_disclaimer_content.version,
            }
        )
        draft_disclaimer_content.refresh_from_db()
        assert draft_disclaimer_content.is_draft is False
        assert DisclaimerContent.current() == draft_disclaimer_content
