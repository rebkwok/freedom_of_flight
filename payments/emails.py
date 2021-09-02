from django.conf import settings
from django.core.mail import send_mail
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.template.loader import get_template


def _get_user_from_invoice(invoice):
    if invoice.username == "paypal_test":
        user, _ = User.objects.get_or_create(email=settings.SUPPORT_EMAIL)
    else:
        user = User.objects.get(username=invoice.username)
    return user


def send_processed_payment_emails(invoice):
    user = _get_user_from_invoice(invoice)
    ctx = {
        'host': f"https://{Site.objects.get_current().domain}",
        'user': user,
        'invoice': invoice,
        "studio_email": settings.DEFAULT_STUDIO_EMAIL
    }

    # send email to studio
    if settings.SEND_ALL_STUDIO_EMAILS:
        send_mail(
            '{} Payment processed'.format(settings.ACCOUNT_EMAIL_SUBJECT_PREFIX),
            get_template('payments/email/payment_processed_to_studio.txt').render(ctx),
            settings.DEFAULT_FROM_EMAIL,
            [settings.DEFAULT_STUDIO_EMAIL],
            html_message=get_template('payments/email/payment_processed_to_studio.html').render(ctx),
            fail_silently=False
        )

    # send email to user
    send_mail(
        f'{settings.ACCOUNT_EMAIL_SUBJECT_PREFIX} Your payment has been processed',
        get_template('payments/email/payment_processed_to_user.txt').render(ctx),
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=get_template('payments/email/payment_processed_to_user.html').render(ctx),
        fail_silently=False
    )


def send_processed_refund_emails(invoice):
    user = _get_user_from_invoice(invoice)
    ctx = {
        'host': f"https://{Site.objects.get_current().domain}",
        'user': user,
        'invoice': invoice,
        "studio_email": settings.DEFAULT_STUDIO_EMAIL
    }

    # send email to support only for checking;
    # user will have received automated paypal payment
    send_mail(
        'WARNING: Payment refund processed',
        get_template('payments/email/payment_refund_processed.txt').render(ctx),
        settings.DEFAULT_FROM_EMAIL,
        [settings.SUPPORT_EMAIL],
        fail_silently=False
    )


def send_failed_payment_emails(ipn_or_pdt=None, payment_intent=None, error=None):
    # send email to support only for checking;
    send_mail(
        'WARNING: Something went wrong with a payment!',
        get_template('payments/email/payment_error.txt').render(
            {"ipn_or_pdt": ipn_or_pdt, "payment_intent": payment_intent, "error": error}
        ),
        settings.DEFAULT_FROM_EMAIL,
        [settings.SUPPORT_EMAIL],
        fail_silently=False
    )
