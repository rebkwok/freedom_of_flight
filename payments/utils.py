import logging
from django.urls import reverse

from .exceptions import PayPalProcessingError, StripeProcessingError
from .forms import PayPalPaymentsFormWithId, PayPalPaymentsForm
from .models import Invoice


logger = logging.getLogger(__name__)


def get_paypal_form(request, invoice, paypal_test=False):
    # What you want the button to do.
    paypal_dict = {
        "cmd": "_cart",
        "upload": 1,
        "currency_code": "GBP",
        "business": invoice.business_email,
        "invoice": invoice.invoice_id,
        "notify_url": request.build_absolute_uri(reverse('paypal-ipn')),
        "return": request.build_absolute_uri(reverse('payments:paypal_return')),
        "cancel_return": request.build_absolute_uri(reverse('payments:paypal_cancel')),
        "custom": f"{invoice.id}_{invoice.signature()}",
    }

    blocks = invoice.blocks.all()
    subscriptions = invoice.subscriptions.all()
    # TODO products - for later
    for i, block in enumerate(blocks, start=1):
        if block.voucher:
            amount = block.cost_with_voucher
        else:
            amount = block.block_config.cost
        item_name = str(block.block_config)
        paypal_dict.update(
            {
                'item_name_{}'.format(i): item_name,
                'amount_{}'.format(i): amount,
                'quantity_{}'.format(i): 1,
            }
        )
    for i, subscription in enumerate(subscriptions, start=len(blocks) + 1):
        invoiced_amount = subscription.cost_as_of_today()
        # save the invoiced amount to the Subscription instance.  This will get updated if necessary if the
        # payment isn't processed immediately, but means we can track if a subscription was charged at a
        # partial cost
        subscription.invoiced_amount = invoiced_amount
        subscription.save()
        paypal_dict.update(
            {
                'item_name_{}'.format(i): f"{subscription.config.name} (subscription)",
                'amount_{}'.format(i): invoiced_amount,
                'quantity_{}'.format(i): 1,
            }
        )

    if paypal_test:
        assert not invoice.blocks.exists()
        assert not invoice.subscriptions.exists()
        paypal_dict.update(
            {
                'item_name_1': "paypal_test",
                'amount_1': invoice.amount,
                'quantity_1': 1,
            }
        )
        # Create the instance.
        form = PayPalPaymentsForm(initial=paypal_dict)
    else:
        # Create the instance.
        form = PayPalPaymentsFormWithId(initial=paypal_dict)


    return form


def check_paypal_data(ipn_or_pdt, invoice):
    if ipn_or_pdt.receiver_email != invoice.business_email:
        raise PayPalProcessingError("Receiver email does not match invoice business email")

    invoice_id, signature = ipn_or_pdt.custom.split("_", 1)
    if signature != invoice.signature():
        raise PayPalProcessingError("Could not verify invoice signature")

    if ipn_or_pdt.mc_gross != invoice.amount:
        raise PayPalProcessingError("Invoice amount is not correct")

    if ipn_or_pdt.mc_currency != 'GBP':
        raise PayPalProcessingError(f"Unexpected currency {ipn_or_pdt.mc_currency}")


def get_invoice_from_ipn_or_pdt(ipn_or_pdt, paypal_obj_type, raise_immediately=False):
    # For PDTs, we don't raise the exception here so we don't expose it to the user; leave it for
    # the IPN signal to raise and emails will be sent to admins
    if not ipn_or_pdt.invoice:
        # sometimes paypal doesn't send back the invoice id - try to retrieve it from the custom field
        invoice = retrieve_invoice_from_paypal_data(ipn_or_pdt)
        if invoice is None:
            logger.error("Error processing paypal %s %s; could not find invoice", paypal_obj_type, ipn_or_pdt.id)
            if raise_immediately:
                raise PayPalProcessingError(f"Error processing paypal {paypal_obj_type} {ipn_or_pdt.id}; could not find invoice")
            return None
        # set the retrieved invoice on the paypal obj
        ipn_or_pdt.invoice = invoice.invoice_id
        ipn_or_pdt.save()
    try:
        return Invoice.objects.get(invoice_id=ipn_or_pdt.invoice)
    except Invoice.DoesNotExist:
        logger.error("Error processing paypal %s %s; could not find invoice", paypal_obj_type, ipn_or_pdt.id)
        if raise_immediately:
            raise PayPalProcessingError(f"Error processing paypal {paypal_obj_type} {ipn_or_pdt.id}; could not find invoice")
        return None


def retrieve_invoice_from_paypal_data(ipn_or_pdt):
    invoice_id_and_signature = ipn_or_pdt.custom.split("_", 1)
    if len(invoice_id_and_signature) != 2:
        return None
    else:
        invoice_id = invoice_id_and_signature[0]
        try:
            return Invoice.objects.get(id=int(invoice_id))
        except (Invoice.DoesNotExist, ValueError):
            return None


def get_invoice_from_payment_intent(payment_intent, raise_immediately=False):
    # Don't raise the exception here so we don't expose it to the user; leave it for the webhook
    invoice_id = payment_intent.metadata.get("invoice_id")
    if not invoice_id:
        if raise_immediately:
            raise StripeProcessingError(f"Error processing stripe payment intent {payment_intent.id}; no invoice id")
        return None
    try:
        return Invoice.objects.get(invoice_id=invoice_id)
    except Invoice.DoesNotExist:
        logger.error("Error processing stripe payment intent %s; could not find invoice", payment_intent.id)
        if raise_immediately:
            raise StripeProcessingError(f"Error processing stripe payment intent {payment_intent.id}; could not find invoice")
        return None


def check_stripe_data(payment_intent, invoice):
    signature = payment_intent.metadata.get("invoice_signature")
    if signature != invoice.signature():
        raise StripeProcessingError(
            f"Could not verify invoice signature: payment intent {payment_intent.id}; invoice id {invoice.invoice_id}")

    if payment_intent.amount != int(invoice.amount * 100):
        raise StripeProcessingError(
            f"Invoice amount is not correct: payment intent {payment_intent.id} ({payment_intent.amount/100}); "
            f"invoice id {invoice.invoice_id} ({invoice.amount})"
        )
