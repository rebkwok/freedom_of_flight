# -*- coding: utf-8 -*-
from django.urls import reverse
from django.test import TestCase

from common.test_utils import TestUsersMixin, make_disclaimer_content


class MiscViewTests(TestUsersMixin, TestCase):
    def setUp(self):
        self.create_users()
        make_disclaimer_content(version=None)
        self.login(self.student_user)

    def test_disclaimer_required(self):
        """
        test that page redirects if there is no user logged in
        """
        url = reverse("booking:disclaimer_required", args=(self.student_user.id,))
        resp = self.client.get(url)
        assert resp.status_code == 200
        assert resp.context['has_expired_disclaimer'] is False
        assert resp.context['disclaimer_user'] == self.student_user

        self.make_disclaimer(self.student_user)
        make_disclaimer_content(version=None)
        resp = self.client.get(url)
        assert resp.status_code == 200
        assert resp.context['has_expired_disclaimer'] is True

    def test_permission_denied(self):
        self.client.logout()
        url = reverse("booking:permission_denied")
        resp = self.client.get(url)
        assert resp.status_code == 200

    def test_terms_and_conditions(self):
        self.client.logout()
        url = reverse("booking:terms_and_conditions")
        resp = self.client.get(url)
        assert resp.status_code == 200

    def test_covid19_policy(self):
        self.client.logout()
        url = reverse("booking:covid19_policy")
        resp = self.client.get(url)
        assert resp.status_code == 200