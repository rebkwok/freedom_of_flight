import logging

from paypal.standard.models import ST_PP_COMPLETED, ST_PP_REFUNDED
from paypal.standard.ipn.signals import valid_ipn_received, invalid_ipn_received

from .exceptions import PayPalProcessingError
from .models import Invoice
from .utils import check_paypal_data, retrieve_invoice_from_paypal_data


logger = logging.getLogger(__name__)


def process_ipn(sender, **kwargs):
    ipn_obj = sender
    # NOTE THIS IS BACK UP - WE HOPE TO PROCESS EVERYTHING IN THE RETURN VIEW VIA PDT
    invoice = Invoice.objects.get(invoice_id=ipn_obj.invoice)

    if ipn_obj.payment_status == ST_PP_COMPLETED:
        if not ipn_obj.invoice:
            # sometimes paypal doesn't send back the invoice id - try to retrieve it from the custom field
            invoice = retrieve_invoice_from_paypal_data(ipn_obj)
            if invoice is None:
                logging.error("Error processing paypal IPN %s; could not find invoice", ipn_obj.id)
                raise PayPalProcessingError("Error processing paypal IPN %s; could not find invoice", ipn_obj.id)

        if invoice.transaction_id is None:
           # not already processed by IPN, do it now
            # Check expected invoice details and receiver email
            try:
                check_paypal_data(ipn_obj, invoice)
            except PayPalProcessingError as e:
                logging.error("Error processing paypal PDT %s", e)
                raise e
            else:
                # Everything is OK
                for block in invoice.blocks.all():
                    block.paid = True
                    block.save()
                invoice.transaction_id = ipn_obj.txn_id
                invoice.save()
                # TODO send emails
        else:
            logger.info("IPN signal received for invoice %s; already processed", invoice.invoice_id)
    elif ipn_obj.payment_status == ST_PP_REFUNDED:
        logger.info("IPN signal received for refunded invoice %s; transaction id %s", invoice.invoice_id, invoice.transaction_id)
    else:
        raise PayPalProcessingError("Error processing paypal: %s", ipn_obj.flag)


def process_invalid_ipn(sender, **kwargs):
    ipn_obj = sender
    logger.info("Invalid IPN %s; invoice %s, flag_info %s", ipn_obj.id, ipn_obj.invoice, ipn_obj.flag_info)
    raise PayPalProcessingError(f"Invalid IPN: {ipn_obj.id}; invoice {ipn_obj.invoice}; flag {ipn_obj.flag_info}")


valid_ipn_received.connect(process_ipn)
invalid_ipn_received.connect(process_invalid_ipn)