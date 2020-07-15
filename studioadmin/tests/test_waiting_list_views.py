from model_bakery import baker

from django.urls import reverse
from django.test import TestCase

from booking.models import Booking, WaitingListUser
from common.test_utils import TestUsersMixin
from common.utils import full_name


class WaitingListViewStudioAdminTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_admin_users()
        self.create_users()
        self.event = baker.make_recipe("booking.future_event")
        self.url = reverse("studioadmin:event_waiting_list", args=(self.event.id,))
        self.ajax_remvove_url = reverse("studioadmin:ajax_remove_from_waiting_list")

    def test_staff_or_instructor_allowed(self):
        self.login(self.student_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == reverse("booking:permission_denied")

        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 200

        self.login(self.instructor_user)
        resp = self.client.get(self.url)
        assert resp.status_code == 200

    def test_waiting_list_users_shown(self):
        """
        Only show users on the waiting list for the relevant event
        """
        self.login(self.staff_user)
        resp = self.client.get(self.url)
        assert list(resp.context_data["waiting_list_users"]) == []
        assert "There are no students on the waiting list" in resp.rendered_content

        baker.make(WaitingListUser, event=self.event, _quantity=10)
        baker.make(WaitingListUser, _quantity=5)
        resp = self.client.get(self.url)
        assert len(resp.context_data["waiting_list_users"]) == 10

    def test_cleanup_waitinglist(self):
        self.login(self.staff_user)
        baker.make(WaitingListUser, event=self.event, _quantity=10)
        baker.make(WaitingListUser, event=self.event, user=self.student_user)
        resp = self.client.get(self.url)
        assert len(resp.context_data["waiting_list_users"]) == 11

        # make a booking for this user
        baker.make(Booking, user=self.student_user, event=self.event, status="OPEN")
        # booked user removed from waitinglist
        resp = self.client.get(self.url)
        assert len(resp.context_data["waiting_list_users"]) == 10
        assert WaitingListUser.objects.filter(
            user=self.student_user, event=self.event
        ).exists() is False

    def test_ajax_remove_user_from_waiting_list(self):
        self.login(self.staff_user)
        wl_user = baker.make(WaitingListUser, event=self.event, user=self.student_user)
        resp = self.client.post(self.ajax_remvove_url, data={"wluser_id": wl_user.id, "event_id": self.event.id}).json()
        assert WaitingListUser.objects.filter(id=wl_user.id).exists() is False
        assert "removed" in resp
        assert resp["alert_msg"] == f"{full_name(self.student_user)} removed from waiting list"

    def test_ajax_remove_waitinglistuser_not_found(self):
        self.login(self.staff_user)
        resp = self.client.post(self.ajax_remvove_url, data={"wluser_id": 1, "event_id": self.event.id})
        assert resp.status_code == 400
        assert resp.content.decode("utf-8") == "User is not on waiting list"

    def test_ajax_remove_user_and_event_mismatch(self):
        self.login(self.staff_user)
        wl_user = baker.make(WaitingListUser, event=self.event, user=self.student_user)
        resp = self.client.post(self.ajax_remvove_url, data={"wluser_id": wl_user.id, "event_id": 999})
        assert WaitingListUser.objects.filter(id=wl_user.id).exists()
        assert resp.status_code == 400
        assert resp.content.decode("utf-8") == "User is not on waiting list"
