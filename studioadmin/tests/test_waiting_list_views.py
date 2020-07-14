from model_bakery import baker

from django.urls import reverse
from django.test import TestCase

from common.test_utils import TestUsersMixin


class WaitingListViewStudioAdminTests(TestUsersMixin, TestCase):

    def test_staff_or_instructor_allowed(self):
        pass

    def test_waiting_list_users_shown(self):
        """
        Only show users on the waiting list for the relevant event
        """
        pass


class AjaxRemoveUserFromWaitingListTests(TestUsersMixin, TestCase):

    def test_remove_user_from_waiting_list(self):
        pass

    def test_user_and_event_mismatch(self):
        pass

    def test_waitinglistuser_not_found(self):
        pass