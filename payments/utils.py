from typing import NamedTuple

from django.conf import settings
from django.urls import reverse

from .exceptions import PayPalProcessingError
from .forms import PayPalPaymentsFormWithId
from .models import Invoice


def get_paypal_form(request, invoice):
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
    # TODO products - for later
    for i, block in enumerate(blocks):
        if block.voucher:
            amount = block.cost_with_voucher
        else:
            amount = block.block_config.cost
        item_name = str(block.block_config)
        paypal_dict.update(
            {
                'item_name_{}'.format(i + 1): item_name,
                'amount_{}'.format(i + 1): amount,
                'quantity_{}'.format(i + 1): 1,
            }
        )

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
        raise PayPalProcessingError(f"Unexpected currency {pdt_obj.mc_currency}")


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

