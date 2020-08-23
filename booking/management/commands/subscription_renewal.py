
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.core.management.base import BaseCommand

from activitylog.models import ActivityLog
from booking.email_helpers import send_user_and_studio_emails
from booking.models import Subscription, SubscriptionConfig
from common.utils import full_name


class Command(BaseCommand):
    help = "Find soon-to-expire subscriptions for active recurring subscription configs, send reminders and" \
           "add to cart (i.e. create a new unpaid one for the next period)"

    def handle(self, *args, **options):
        # find active and recurring configs
        config_ids = SubscriptionConfig.objects.filter(active=True, recurring=True).values_list("id", flat=True)
        # find existing active (paid and expires in future) subscriptions that expire soon
        # Exclude any that we've already send reminders for
        subscriptions = [
            subscription for subscription in
            Subscription.objects.filter(config_id__in=config_ids, expiry_date__gt=timezone.now(), reminder_sent=False, paid=True)
            if subscription.expires_soon()
        ]

        subscriptions_for_reminders = []
        for subscription in subscriptions:
            start_options_for_user = subscription.config.get_start_options_for_user(subscription.user)
            if start_options_for_user:
                # The might be no available start options, if the user already has a subscription
                # with the next start date (paid or unpaid)
                # NOTE: we use the calculated start date, even if the start_options type is "signup_date", since
                # we'll only get to this point if the user has a current active subscription.  We want it to start from
                # the date that the previous subscription expires, not necessarily from the purchase date
                start_date = start_options_for_user[-1]  # get the last one, in case we got both current and next
                # get or create in case user has a subscription already.  We want to check for both paid and unpaid
                # existing subscriptions
                _, created = Subscription.objects.get_or_create(
                    config=subscription.config, user=subscription.user, start_date=start_date,
                    defaults={"paid": False}
                )
                if created:
                    subscriptions_for_reminders.append(subscription)

            subscription.reminder_sent = True
            subscription.save()

        for subscription in subscriptions_for_reminders:
            user_to_email = subscription.user.manager_user if subscription.user.manager_user else subscription.user
            subject = f"Subscription expires soon: {subscription.config.name.title()}"
            context = {"subscription": subscription}
            send_user_and_studio_emails(
                context, user_to_email, send_to_studio=False, subjects={"user": subject}, template_short_name="subscription_renewal"
            )

        if subscriptions_for_reminders:
            log = f"Subscription reminders sent to {', '.join([full_name(subscription.user) for subscription in subscriptions_for_reminders])}"
            ActivityLog.objects.create(log=log)
            self.stdout.write(log)
        else:
            self.stdout.write("No reminders to send")
