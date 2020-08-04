# -*- coding: utf-8 -*-
from decimal import Decimal
from model_bakery import baker

from django import forms
from django.urls import reverse
from django.test import TestCase

from accounts.models import CookiePolicy, DataPrivacyPolicy, DisclaimerContent
from common.test_utils import TestUsersMixin, EventTestMixin


class HelpViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse("studioadmin:help")

    def test_instructor_or_staff(self):
        self.login(self.student_user)
        self.client.logout()
        resp = self.client.get(self.url)
        assert resp.status_code == 302

        self.login(self.instructor_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 200

        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 200


class CookiePolicyViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.create_admin_users()
        self.login(self.staff_user)

    @classmethod
    def setUpTestData(cls):
        cls.list_url = reverse("studioadmin:cookie_policies")

    def test_list_view_staff_only(self):
        self.login(self.student_user)
        resp = self.client.get(self.list_url)
        assert resp.status_code == 302

        self.login(self.instructor_user)
        resp = self.client.get(self.list_url)
        assert resp.status_code == 302

        self.login(self.staff_user)
        resp = self.client.get(self.list_url)
        assert resp.status_code == 200

    def test_detail_view(self):
        policy = baker.make(CookiePolicy, version=1.0)
        resp = self.client.get(reverse("studioadmin:cookie_policy", args=(policy.version,)))
        assert resp.status_code == 200
