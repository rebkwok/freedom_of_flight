from django.conf import settings
from django.core.mail import send_mail
from django.core.mail.message import EmailMultiAlternatives
from django.template.loader import get_template

from activitylog.models import ActivityLog


def send_waiting_list_email(event, waiting_list_users, host):
    if waiting_list_users:
        user_emails = [waiting_list_user.user.email for waiting_list_user in waiting_list_users]
        msg = EmailMultiAlternatives(
            '{} {}'.format(settings.ACCOUNT_EMAIL_SUBJECT_PREFIX, event),
            get_template('booking/email/waiting_list_email.txt').render(
                {'event': event, 'host': host}
            ),
            settings.DEFAULT_FROM_EMAIL,
            bcc=user_emails,
        )
        msg.attach_alternative(
            get_template(
                'booking/email/waiting_list_email.html').render(
                {'event': event, 'host': host}
            ),
            "text/html"
        )
        msg.send(fail_silently=False)

        ActivityLog.objects.create(
            log=f'Waiting list email sent to user(s) {", ".join(user_emails)} for event {event}'
        )


def send_user_and_studio_emails(context, user, send_to_studio, subjects, template_short_name):
    # send email to user
    send_mail(
        f'{settings.ACCOUNT_EMAIL_SUBJECT_PREFIX} {subjects["user"]}',
        get_template(f'booking/email/{template_short_name}.txt').render(context),
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=get_template(f'booking/email/{template_short_name}.html').render(context),
        fail_silently=False
    )

    # send email to studio if flagged for the course
    if send_to_studio:
        send_mail(
            f'{settings.ACCOUNT_EMAIL_SUBJECT_PREFIX} {subjects["studio"]}',
            get_template(f'booking/email/to_studio_{template_short_name}.txt').render(context),
            settings.DEFAULT_FROM_EMAIL,
            [settings.DEFAULT_STUDIO_EMAIL],
            fail_silently=False
        )