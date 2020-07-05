import logging

from django.views.decorators.http import require_GET
from django.shortcuts import render

from paypal.standard.pdt.views import process_pdt

from .exceptions import PayPalProcessingError
from .models import Invoice
from .utils import check_paypal_data, retrieve_invoice_from_paypal_data

logger = logging.getLogger(__name__)


@require_GET
def paypal_return(request):
    pdt_obj, failed = process_pdt(request)
    context = {"failed": failed, "pdt_obj": pdt_obj}
    if not failed:
        if not pdt_obj.invoice:
            # sometimes paypal doesn't send back the invoice id - try to retrieve it from the custom field
            invoice = retrieve_invoice_from_paypal_data(pdt_obj)
            if invoice is None:
                logging.error("Error processing paypal PDT %s; could not find invoice", pdt_obj.id)
                # Don't raise the exception here; leave it for the IPN signal to raise and emails will be sent to admins
                failed = True

        invoice = Invoice.objects.get(invoice_id=pdt_obj.invoice)
        if invoice.transaction_id is None:
            # not already processed by IPN, do it now
            # Check expected invoice details and receiver email
            try:
                check_paypal_data(pdt_obj, invoice)
            except PayPalProcessingError as e:
                logging.error("Error processing paypal PDT %s", e)
                failed = True
            else:
                # Everything is OK
                for block in invoice.blocks.all():
                    block.paid = True
                    block.save()
                invoice.transaction_id = pdt_obj.txn_id
                invoice.save()
                # TODO send emails
        else:
            logger.info("PDT signal received for invoice %s; already processed", invoice.invoice_id)

    if not failed:
        return render(request, 'payments/valid_payment.html', context)
    return render(request, 'payments/non_valid_payment.html', context)


def paypal_cancel_return(request):
    return render(request, 'payments/cancelled_payment.html')


