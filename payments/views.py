import logging

from django.views.decorators.http import require_GET
from django.shortcuts import render

from paypal.standard.pdt.views import process_pdt

from .emails import send_processed_payment_emails, send_failed_payment_emails
from .exceptions import PayPalProcessingError
from .utils import check_paypal_data, get_invoice_from_ipn_or_pdt

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
                    invoice.save()
                    # SEND EMAILS
                    send_processed_payment_emails(invoice)
            else:
                logger.info("PDT signal received for invoice %s; already processed", invoice.invoice_id)
        else:
            # No invoice retrieved, fail
            failed = True
            error = "No invoice on PDT on return from paypal"
    if not failed:
        return render(request, 'payments/valid_payment.html', context)

    error = error or "Failed status on PDT return from paypal"
    send_failed_payment_emails(pdt_obj, error=error)
    return render(request, 'payments/non_valid_payment.html', context)


def paypal_cancel_return(request):
    return render(request, 'payments/cancelled_payment.html')


