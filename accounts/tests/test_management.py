
from datetime import timedelta

from model_bakery import baker

from django.contrib.auth.models import User
from django.core import management
from django.test import TestCase
from django.utils import timezone

from accounts.models import ArchivedDisclaimer, NonRegisteredDisclaimer, OnlineDisclaimer
from activitylog.models import ActivityLog
from common.test_utils import TestUsersMixin, make_online_disclaimer, make_nonregistered_disclaimer, make_archived_disclaimer


class DeleteExpiredDisclaimersTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        make_online_disclaimer(
            user=self.student_user, date=timezone.now()-timedelta(2200)
        )  # > 6 yrs
        make_online_disclaimer(
            user=self.student_user1,
            date=timezone.now()-timedelta(2200)  # > 6 yrs
        )
        make_nonregistered_disclaimer(
            first_name='Test', last_name='Nonreg',
            date=timezone.now()-timedelta(2200)  # > 6 yrs
        )
        make_archived_disclaimer(name='Test Archived',
            date=timezone.now()-timedelta(2200)  # > 6 yrs
        )

    def test_disclaimers_deleted_if_more_than_6_years_old(self):
        assert OnlineDisclaimer.objects.count() == 2
        management.call_command('delete_expired_disclaimers')
        assert OnlineDisclaimer.objects.count() == 0
        activitylogs = ActivityLog.objects.values_list('log', flat=True)
        online_users = [
            '{} {}'.format(user.first_name, user.last_name)
            for user in [self.student_user, self.student_user1]
        ]

        assert 'Online disclaimers more than 6 yrs old deleted for users: {}'.format(
                ', '.join(online_users)
            ) in activitylogs

        assert 'Non-registered disclaimers more than 6 yrs old deleted for users: Test Nonreg' in activitylogs

        assert 'Archived disclaimers more than 6 yrs old deleted for users: Test Archived' in activitylogs

    def test_disclaimers_not_deleted_if_created_in_past_6_years(self):
        # make a user with a disclaimer created today
        user = baker.make(User)
        make_online_disclaimer(user=user)
        make_nonregistered_disclaimer()
        make_archived_disclaimer()

        assert OnlineDisclaimer.objects.count() == 3
        assert NonRegisteredDisclaimer.objects.count() == 2
        assert ArchivedDisclaimer.objects.count() == 2

        # disclaimer should not be deleted because it was created < 3 yrs ago.
        # All others will be.
        management.call_command('delete_expired_disclaimers')
        assert OnlineDisclaimer.objects.count() == 1

    def test_disclaimers_not_deleted_if_updated_in_past_6_years(self):
        # make a user with a disclaimer created > yr ago but updated in past yr
        user = baker.make(User)
        make_online_disclaimer(user=user, date=timezone.now() - timedelta(2200),
            date_updated=timezone.now() - timedelta(2000),
        )
        assert  OnlineDisclaimer.objects.count() == 3

        management.call_command('delete_expired_disclaimers')
        assert OnlineDisclaimer.objects.count() == 1

    def test_no_disclaimers_to_delete(self):
        for disclaimer_list in [
            ArchivedDisclaimer.objects.all(),
            NonRegisteredDisclaimer.objects.all(),
            OnlineDisclaimer.objects.all()
        ]:
            for disclaimer in disclaimer_list:
                if hasattr(disclaimer, 'date_updated'):
                    disclaimer.date_updated = timezone.now() - timedelta(600)
                    disclaimer.save()
                else:
                    disclaimer.delete()

        management.call_command('delete_expired_disclaimers')
        assert OnlineDisclaimer.objects.count() == 2
        assert ArchivedDisclaimer.objects.count() == 1

