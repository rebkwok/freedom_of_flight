from decimal import Decimal
import json
import logging

from django.conf import settings
from django.contrib.sites.models import Site
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import ListView
from django.shortcuts import render, HttpResponse

from braces.views import LoginRequiredMixin

from paypal.standard.pdt.views import process_pdt
import stripe

from activitylog.models import ActivityLog
from .emails import send_failed_payment_emails, send_processed_refund_emails
from .exceptions import PayPalProcessingError, StripeProcessingError, UnknownTransactionError
from .models import Invoice, Seller, StripePaymentIntent
from .utils import check_paypal_data, get_paypal_form, get_invoice_from_ipn_or_pdt, \
    get_invoice_from_payment_intent, check_stripe_data, process_invoice_items

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
                    logger.error("Error processing paypal PDT %s", e)
                    failed = True
                    error = f"Error processing paypal PDT {e}",
                else:
                    # Everything is OK
                    process_invoice_items(invoice, payment_method="PayPal", transaction_id=pdt_obj.txn_id)
            else:
                logger.info("PDT signal received for invoice %s; already processed", invoice.invoice_id)
        else:
            # No invoice retrieved, fail
            failed = True
            error = "No invoice on PDT on return from paypal"
    if not failed:
        if invoice.blocks.exists():
            redirect_track = invoice.blocks.first().block_config.event_type.track
        else:
            redirect_track = None

        context = {
            "cart_items": invoice.items_dict().values(),
            "item_types": invoice.item_types(),
            "total_charged": invoice.amount,
            "redirect_track": redirect_track
        }
        if "total_voucher_code" in request.session:
            context.update({"total_voucher_code": request.session["total_voucher_code"]})
            del request.session["total_voucher_code"]
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


def _process_completed_stripe_payment(payment_intent, invoice, seller=None):
    if not invoice.paid:
        logger.info("Updating items to paid for invoice %s", invoice.invoice_id)
        check_stripe_data(payment_intent, invoice)
        logger.info("Stripe check OK")
        process_invoice_items(invoice, payment_method="Stripe")
        # update/create the django model PaymentIntent - this is just for records
        StripePaymentIntent.update_or_create_payment_intent_instance(payment_intent, invoice, seller)
    else:
        logger.info(
            "Payment Intents signal received for invoice %s; already processed", invoice.invoice_id
        )


@require_POST
def stripe_payment_complete(request):
    payload = request.POST.get("payload")
    if payload is None:
        logger.error("No payload found %s", payload)
        send_failed_payment_emails(
            payment_intent=None, error=f"POST: {str(request.POST)}"
        )
        return render(request, 'payments/non_valid_payment.html')

    payload = json.loads(payload)
    logger.info("Processing payment intent from payload %s", payload)
    stripe.api_key = settings.STRIPE_SECRET_KEY
    seller = Seller.objects.filter(site=Site.objects.get_current(request)).first()
    stripe_account = seller.stripe_user_id
    payment_intent = stripe.PaymentIntent.retrieve(payload["id"], stripe_account=stripe_account)
    failed = False

    if payment_intent.status == "succeeded":
        try:  
            invoice = get_invoice_from_payment_intent(payment_intent, raise_immediately=False)
        except UnknownTransactionError as e:
            # This is a transaction from teamup; just log it and ignore
            logger.warning(e)
            error = "Unknown transaction"
            failed = True
        
        if invoice is not None:
            try:
                _process_completed_stripe_payment(payment_intent, invoice, seller)
            except StripeProcessingError as e:
                error = f"Error processing Stripe payment: {e}"
                logger.error(e)
                failed = True
        else:
            # No invoice retrieved, fail
            failed = True
            error = f"No invoice could be retrieved from succeeded payment intent {payment_intent.id}"
            logger.error(error)
    else:
        failed = True
        error = f"Payment intent id {payment_intent.id} status: {payment_intent.status}"
        logger.error(error)
    payment_intent.metadata.pop("invoice_id", None)
    payment_intent.metadata.pop("invoice_signature", None)
    if not failed:
        if invoice.blocks.exists():
            redirect_track = invoice.blocks.first().block_config.event_type.track
        else:
            redirect_track = None

        context = {
            "cart_items": invoice.items_dict().values(),
            "item_types": invoice.item_types(),
            "total_charged": invoice.amount,
            "redirect_track": redirect_track,
        }
        if "total_voucher_code" in request.session:
            del request.session["total_voucher_code"]
        context.update({"total_voucher_code": invoice.total_voucher_code})

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
        logger.error(e)
        return HttpResponse(str(e), status=400)
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        logger.error(e)
        return HttpResponse(str(e), status=400)

    event_object = event.data.object
    if event.type == "account.application.authorized":
        connected_accounts = stripe.Account.list().data
        for connected_account in connected_accounts:
            seller = Seller.objects.filter(stripe_user_id=connected_account.id)
            if not seller.exists():
                logger.error(f"Connected Stripe account has no associated seller %s", connected_account.id)
                return HttpResponse("Connected Stripe account has no associated seller", status=400)
        return HttpResponse(status=200)

    elif event.type == "account.application.deauthorized":
        connected_accounts = stripe.Account.list().data
        connected_account_ids = [account.id for account in connected_accounts]
        for seller in Seller.objects.all():
            if seller.stripe_user_id not in connected_account_ids:
                seller.site = None
                seller.save()
                logger.info(f"Stripe account disconnected: %s", seller.stripe_user_id)
                ActivityLog.objects.create(log=f"Stripe account disconnected: {seller.stripe_user_id}")
        return HttpResponse(status=200)

    try:
        payment_intent = event_object
        site_seller = Seller.objects.filter(site=Site.objects.get_current(request)).first()
        try:
            account = event.account
        except Exception as e:
            logger.error(e)
        else:
            if account != site_seller.stripe_user_id:
                # relates to a different seller, just return and let the next webhook manage it
                logger.info("Mismatched seller account %s", account)
                return HttpResponse("Ignored: Mismatched seller account", status=200)
        try:  
            invoice = get_invoice_from_payment_intent(payment_intent, raise_immediately=True)
        except UnknownTransactionError as e:
            # This is a transaction from teamup; just log it and ignore
            logger.warning(e)
            return HttpResponse("Ignored: Unknown transaction", status=200)
        error = None
        if event.type == "payment_intent.succeeded":
            _process_completed_stripe_payment(payment_intent, invoice)
        elif event.type == "payment_intent.refunded":
            send_processed_refund_emails(invoice)
        elif event.type == "payment_intent.payment_failed":
            error = f"Failed payment intent id: {payment_intent.id}; invoice id {invoice.invoice_id}; " \
                    f"error {payment_intent.last_payment_error}"
        if error:
            logger.error(error)
            send_failed_payment_emails(error=error)
            return HttpResponse(error, status=200)
    except Exception as e:  # log anything else
        logger.error(e)
        send_failed_payment_emails(error=e)
        return HttpResponse(str(e), status=200)
    return HttpResponse(status=200)


class UserInvoiceListView(LoginRequiredMixin, ListView):
    paginate_by = 20
    model = Invoice
    context_object_name = "invoices"
    template_name = "payments/invoices.html"

    def get_queryset(self):
        return Invoice.objects.filter(paid=True, username=self.request.user.username)
