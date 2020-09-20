import logging

from paypal.standard.models import ST_PP_COMPLETED, ST_PP_REFUNDED, ST_PP_PENDING
from paypal.standard.ipn.signals import valid_ipn_received, invalid_ipn_received

from .exceptions import PayPalProcessingError
from .emails import send_processed_payment_emails, send_processed_refund_emails, send_failed_payment_emails
from .utils import check_paypal_data, get_invoice_from_ipn_or_pdt

from activitylog.models import ActivityLog


logger = logging.getLogger(__name__)


def process_ipn(sender, **kwargs):
    ipn_obj = sender
    # NOTE THIS IS BACKUP - WE HOPE TO PROCESS EVERYTHING IN THE RETURN VIEW VIA PDT
    try:
        invoice = get_invoice_from_ipn_or_pdt(ipn_obj, "IPN", raise_immediately=True)
        if ipn_obj.payment_status == ST_PP_COMPLETED:
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
                    for subscription in invoice.subscriptions.all():
                        subscription.paid = True
                        subscription.save()
                    invoice.transaction_id = ipn_obj.txn_id
                    invoice.paid = True
                    invoice.save()
                    # SEND EMAILS
                    send_processed_payment_emails(invoice)
                    ActivityLog.objects.create(
                        log=f"Invoice {invoice.invoice_id} (user {invoice.username}) paid by PayPal"
                    )
            else:
                logger.info("IPN signal received for invoice %s; already processed", invoice.invoice_id)
        elif ipn_obj.payment_status == ST_PP_REFUNDED:
            # DO NOTHING, JUST SEND EMAILS SO WE CAN CHECK MANUALLY
            logger.info("IPN signal received for refunded invoice %s; transaction id %s", ipn_obj.invoice, ipn_obj.txn_id)
            send_processed_refund_emails(invoice)
        else:
            # DO NOTHING, JUST SEND EMAILS SO WE CAN CHECK MANUALLY
            logger.info("IPN signal received with unexpecting status %s; invoice %s; transaction id %s", ipn_obj.payment_status, ipn_obj.invoice, ipn_obj.txn_id)
            send_failed_payment_emails(ipn_obj, error="IPN signal received with unexpecting status")
    except Exception as error:
        logger.error(error)
        # If anything else went wrong
        send_failed_payment_emails(ipn_obj, error=error)


def process_invalid_ipn(sender, **kwargs):
    ipn_obj = sender
    logger.info("Invalid IPN %s; invoice %s, flag_info %s", ipn_obj.id, ipn_obj.invoice, ipn_obj.flag_info)
    raise PayPalProcessingError(f"Invalid IPN: {ipn_obj.id}; invoice {ipn_obj.invoice}; flag {ipn_obj.flag_info}")


valid_ipn_received.connect(process_ipn)
invalid_ipn_received.connect(process_invalid_ipn)