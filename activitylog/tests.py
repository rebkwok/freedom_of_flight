import os
import sys
from io import StringIO
from unittest.mock import patch

from datetime import datetime, timedelta
from model_bakery import baker
from dateutil.relativedelta import relativedelta

from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.core import management
from django.test import TestCase
from django.utils import timezone

from activitylog import admin
from activitylog.models import ActivityLog


class ActivityLogModelTests(TestCase):

    def test_str(self):
        # str method formats dates and truncates long log messages to
        # 100 chars
        activitylog = ActivityLog.objects.create(
            log="This is a long log message with many many many many many "
                "many characters.  126 in total, in fact. It will be "
                "truncated to 100."
        )
        truncated_log = 'This is a long log message with many many many ' \
                        'many many many characters.  126 in total, in fact. ' \
                        'It'
        assert activitylog.log[:100] == truncated_log
        assert len(truncated_log) == 100

        assert str(activitylog) =='{} - {}'.format(
            timezone.now().strftime('%Y-%m-%d %H:%M %Z'), truncated_log
        )


class ActivityLogAdminTests(TestCase):

    def test_timestamp_display(self):
        activitylog = ActivityLog.objects.create(
            timestamp=datetime(
                2016, 9, 15, 13, 45, 10, 12455, tzinfo=timezone.utc
            ),
            log="Message"
        )

        activitylog_admin = admin.ActivityLogAdmin(ActivityLog, AdminSite())
        al_query = activitylog_admin.get_queryset(None)[0]
        assert  activitylog_admin.timestamp_formatted(al_query) =='15-Sep-2016 13:45:10 (UTC)'


class DeleteOldActivityLogsTests(TestCase):

    def setUp(self):

        # logs 13, 25, 37 months ago, one for each empty job text msg, one other
        self.mock_now = datetime(2019, 10, 1, tzinfo=timezone.utc)
        self.log_11monthsold = baker.make(ActivityLog, log='message', timestamp=self.mock_now-relativedelta(months=11))
        self.log_25monthsold = baker.make(ActivityLog, log='message', timestamp=self.mock_now-relativedelta(months=25))
        self.log_37monthsold = baker.make(ActivityLog, log='message', timestamp=self.mock_now-relativedelta(months=37))

    @patch('activitylog.management.commands.delete_old_activitylogs.subprocess.run')
    @patch('activitylog.management.commands.delete_old_activitylogs.timezone.now')
    def test_delete_default_old_logs(self, mock_now, mock_run):
        mock_now.return_value = self.mock_now
        assert ActivityLog.objects.count() == 3
        # no age, defaults to 1 yr
        management.call_command('delete_old_activitylogs')
        # 2 logs left - the one that's < 1 yrs old plus the new one to log this activity
        assert ActivityLog.objects.count() == 2
        all_log_ids = ActivityLog.objects.values_list("id", flat=True)
        for log in [self.log_25monthsold, self.log_37monthsold]:
            self.assertNotIn(log.id, all_log_ids)
        self.assertIn(self.log_11monthsold.id, all_log_ids)

        assert mock_run.call_count == 1
        cutoff = (self.mock_now-relativedelta(years=1)).strftime('%Y-%m-%d')
        filename = f"{settings.S3_LOG_BACKUP_ROOT_FILENAME}_{cutoff}_{self.mock_now.strftime('%Y%m%d%H%M%S')}.csv"
        mock_run.assert_called_once_with(
            ['aws', 's3', 'cp', filename, os.path.join(settings.S3_LOG_BACKUP_PATH, filename)], check=True
        )

    @patch('activitylog.management.commands.delete_old_activitylogs.subprocess.run')
    @patch('activitylog.management.commands.delete_old_activitylogs.timezone.now')
    def test_delete_old_logs_with_args(self, mock_now, mock_run):
        mock_now.return_value = self.mock_now
        assert ActivityLog.objects.count() == 3
        management.call_command('delete_old_activitylogs', age=3)
        # 3 logs left - the 2 that are < 3 yrs old plus the new one to log this activity
        assert ActivityLog.objects.count() == 3
        all_log_ids = ActivityLog.objects.values_list("id", flat=True)
        for log in [self.log_11monthsold, self.log_25monthsold]:
            self.assertIn(log.id, all_log_ids)
        self.assertNotIn(self.log_37monthsold.id, all_log_ids)

        assert mock_run.call_count == 1
        cutoff = (self.mock_now-relativedelta(years=3)).strftime('%Y-%m-%d')
        filename = f"{settings.S3_LOG_BACKUP_ROOT_FILENAME}_{cutoff}_{self.mock_now.strftime('%Y%m%d%H%M%S')}.csv"
        mock_run.assert_called_once_with(
            ['aws', 's3', 'cp', filename, os.path.join(settings.S3_LOG_BACKUP_PATH, filename)], check=True
        )
