from decimal import Decimal
import json
import logging

from django.conf import settings
from django.contrib.sites.models import Site
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from django.shortcuts import render, HttpResponse

from paypal.standard.pdt.views import process_pdt
import stripe

from activitylog.models import ActivityLog
from .emails import send_processed_payment_emails, send_failed_payment_emails, send_processed_refund_emails
from .exceptions import PayPalProcessingError, StripeProcessingError
from .models import Invoice, Seller
from .utils import check_paypal_data, get_paypal_form, get_invoice_from_ipn_or_pdt, \
    get_invoice_from_payment_intent, check_stripe_data

logger = logging.getLogger(__name__)


@require_GET
def paypal_return(request):
    pdt_obj, failed = process_pdt(request)
    context = {"pdt_obj": pdt_obj}
    error = None
    if not failed:
        invoice = get_invoice_from_ipn_or_pdt(pdt_obj, "PDT", raise_immediately=False)
        if invoice is not None:
            if invoice.transaction_id is None:
                # not already processed by IPN, do it now
                # Check expected invoice details and receiver email
                try:
                    check_paypal_data(pdt_obj, invoice)
                except PayPalProcessingError as e:
                    logging.error("Error processing paypal PDT %s", e)
                    failed = True
                    error = f"Error processing paypal PDT {e}",
                else:
                    # Everything is OK
                    for block in invoice.blocks.all():
                        block.paid = True
                        block.save()
                    for subscription in invoice.subscriptions.all():
                        subscription.paid = True
                        subscription.save()
                    invoice.transaction_id = pdt_obj.txn_id
                    invoice.paid = True
                    invoice.save()
                    # SEND EMAILS
                    send_processed_payment_emails(invoice)
                    ActivityLog.objects.create(
                        log=f"Invoice {invoice.invoice_id} (user {invoice.username}) paid by PayPal"
                    )
            else:
                logger.info("PDT signal received for invoice %s; already processed", invoice.invoice_id)
        else:
            # No invoice retrieved, fail
            failed = True
            error = "No invoice on PDT on return from paypal"
    if not failed:
        context.update({"cart_items": invoice.items_dict()})
        return render(request, 'payments/valid_payment.html', context)

    error = error or "Failed status on PDT return from paypal"
    send_failed_payment_emails(ipn_or_pdt=pdt_obj, error=error)
    return render(request, 'payments/non_valid_payment.html', context)


def paypal_cancel_return(request):
    return render(request, 'payments/cancelled_payment.html')


def paypal_test(request):
    # encrypted custom field so we can verify it on return from paypal
    if request.user.is_anonymous:
        username = "paypal_test"
    else:
        username = request.user.username
    invoice = Invoice.objects.create(
        invoice_id=Invoice.generate_invoice_id(), amount=Decimal(1.0), username=username
    )
    paypal_form = get_paypal_form(request, invoice, paypal_test=True)
    return render(request, 'payments/paypal_test.html', {"form": paypal_form})


def _process_completed_stripe_payment(payment_intent, invoice):
    if not invoice.paid:
        logging.info("Updating items to paid for invoice %s", invoice.invoice_id)
        check_stripe_data(payment_intent, invoice)
        logging.info("Stripe check OK")
        for block in invoice.blocks.all():
            block.paid = True
            block.save()
        for subscription in invoice.subscriptions.all():
            subscription.paid = True
            subscription.save()
        invoice.paid = True
        invoice.save()
        # SEND EMAILS
        send_processed_payment_emails(invoice)
        ActivityLog.objects.create(
            log=f"Invoice {invoice.invoice_id} (user {invoice.username}) paid by Stripe"
        )
    else:
        logger.info(
            "Payment Intents signal received for invoice %s; already processed", invoice.invoice_id
        )


def stripe_payment_complete(request):
    payload = json.loads(request.POST.get("payload"))
    logger.info("Processing payment intent from payload %s", payload)
    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe_account = Seller.objects.filter(site=Site.objects.get_current(request)).first().stripe_user_id
    payment_intent = stripe.PaymentIntent.retrieve(payload["id"], stripe_account=stripe_account)
    failed = False

    if payment_intent.status == "succeeded":
        invoice = get_invoice_from_payment_intent(payment_intent, raise_immediately=False)
        if invoice is not None:
            try:
                _process_completed_stripe_payment(payment_intent, invoice)
            except StripeProcessingError as e:
                error = f"Error processing Stripe payment: {e}"
                logging.error(e)
                failed = True
        else:
            # No invoice retrieved, fail
            failed = True
            error = f"No invoice could be retrieved from succeeded payment intent {payment_intent.id}"
            logging.error(error)
    else:
        failed = True
        error = f"Payment intent id {payment_intent.id} status: {payment_intent.status}"
        logging.error(error)
    payment_intent.metadata.pop("invoice_id")
    payment_intent.metadata.pop("invoice_signature")
    if not failed:
        context = {"cart_items": payment_intent.metadata}
        return render(request, 'payments/valid_payment.html', context)
    else:
        send_failed_payment_emails(payment_intent=payment_intent, error=error)
        return render(request, 'payments/non_valid_payment.html')


@csrf_exempt
def stripe_webhook(request):
    stripe.api_key = settings.STRIPE_SECRET_KEY
    payload = request.body
    sig_header = request.META['HTTP_STRIPE_SIGNATURE']

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_ENDPOINT_SECRET)
    except ValueError as e:
        # Invalid payload
        logging.error(e)
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        logging.error(e)
        return HttpResponse(status=400)

    payment_intent = event.data.object
    try:
        invoice = get_invoice_from_payment_intent(payment_intent, raise_immediately=True)
        error = None
        if event["type"] == "payment_intent.succeeded":
            _process_completed_stripe_payment(payment_intent, invoice)
        elif event["type"] == "payment_intent.refunded":
            send_processed_refund_emails(invoice)
        elif event["type"] == "payment_intent.payment_failed":
            error = f"Failed payment intent id: {event['data']['object']['id']}; invoice id {invoice.invoice_id}"
            send_processed_refund_emails(invoice)
        elif event["type"] == "payment_intent.requires_action":
            error = f"Payment intent requires action: {event['data']['object']['id']}; invoice id {invoice.invoice_id}"
        if error:
            send_failed_payment_emails(error=error)
    except Exception as e:  # log anything else
        logging.error(e)
        return HttpResponse(status=400)
    return HttpResponse(status=200)
