from datetime import datetime, timezone
from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand
from django.utils import timezone
import stripe

from activitylog.models import ActivityLog
from payments.models import Invoice, StripePaymentIntent, Seller


def _block_item_name(block, use_bookings=True):
    if use_bookings and block.bookings.exists():
        if block.block_config.course:
            return str(block.bookings.first().event.course.name)
        else:
            event = block.bookings.first().event
            return event.name_and_date
    return f"Credit block: {block.block_config.name}"


class Command(BaseCommand):
    help = "Fix bad stripe metadata"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action="store_true")

    def handle(self, *args, **options):
        dry_run = options.get('dry_run')
        invoices = Invoice.objects.filter(paid=True)
        invoices_to_update = 0
        payment_intents_to_update = 0

        if not dry_run:
            stripe.api_key = settings.STRIPE_SECRET_KEY
            seller = Seller.objects.filter(site=Site.objects.get_current()).first()
            stripe_account = seller.stripe_user_id
        else:
            stripe_account = None

        for invoice in invoices:
            if invoice.date_paid > datetime(2022, 10, 22, 13, 0, tzinfo=timezone.utc):
                final_metadata = invoice.get_final_metadata()
            else: 
                purchased_items = invoice.get_final_metadata()
                for block in invoice.blocks.all():
                    purchased_items[f"block-{block.id}"]["name"] = f"Credit block: {block.block_config.name}"
                final_metadata = purchased_items
            
            if final_metadata != invoice.final_metadata:
                invoices_to_update += 1
                if not dry_run:
                    invoice.final_metadata = final_metadata
                    invoice.save()

                payment_intent = StripePaymentIntent.objects.filter(payment_intent_id=invoice.stripe_payment_intent_id).first()
                # PI metadata should contain the items in the invoice items_dict PLUS invoice id and signature
                # We only want to update the PI and stripe if we definitely don't have the right number of
                # items in metadata
                if payment_intent is not None and len(payment_intent.metadata) < (len(invoice.items_dict()) + 2):
                    payment_intents_to_update += 1
                    metadata = payment_intent.metadata.copy()
                    invoice_metadata = {k: v for k, v in metadata.items() if k in ["invoice_id", "invoice_signature"]}
                    delete_metadata = {key: "" for key in metadata if key not in invoice_metadata}

                    stripe_metadata = invoice.items_metadata()
                    if invoice.date_paid < datetime(2022, 10, 22, 13, 0, tzinfo=timezone.utc):
                        for block in invoice.blocks.all():
                            if _block_item_name(block) != _block_item_name(block, use_bookings=False):
                                key = f"#{block.id} {_block_item_name(block)}"[:40]
                                new_key = f"#{block.id} {_block_item_name(block, use_bookings=False)}"[:40]
                                stripe_metadata[new_key] = stripe_metadata[key]
                                del stripe_metadata[key]
                    update_metadata = {**invoice_metadata, **stripe_metadata}
                    if dry_run:
                        self.stdout.write(f"DRY RUN: update stripe metadata from {payment_intent.metadata} to {update_metadata}")
                    else:
                        stripe.PaymentIntent.modify(
                            payment_intent.payment_intent_id, metadata=delete_metadata, stripe_account=stripe_account
                        )
                        # now update it with all the new payment intent data
                        stripe.PaymentIntent.modify(
                            payment_intent.payment_intent_id, metadata=update_metadata, stripe_account=stripe_account
                        )
                        payment_intent.metadata = update_metadata
                        payment_intent.save()
                        self.stdout.write(f"Updated stripe metadata for PI {payment_intent.payment_intent_id}, invoice {invoice.invoice_id}")

        self.stdout.write(f"Updated {invoices_to_update} invoices")
        self.stdout.write(f"Updated {payment_intents_to_update} payment intents")
