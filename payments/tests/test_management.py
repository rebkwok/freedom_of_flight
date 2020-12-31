from model_bakery import baker

from django.core import management
from django.test import TestCase

from booking.models import Block, Subscription, GiftVoucher
from ..models import Invoice, StripePaymentIntent
from activitylog.models import ActivityLog


class DeleteUnusedInvoicesTests(TestCase):

    def setUp(self):
        # unpaid invoice with block
        self.invoice1 = baker.make(Invoice, blocks=baker.make(Block, paid=False, _quantity=1), paid=False)
        # unpaid invoice with subscription
        self.invoice2 = baker.make(Invoice, subscriptions=baker.make(Subscription, paid=False, _quantity=1), paid=False)
        # unpaid invoice with gift vouchers
        self.invoice3 = baker.make(
            Invoice,
            gift_vouchers=baker.make(GiftVoucher, gift_voucher_config__discount_amount=10, paid=False, _quantity=1), paid=False
        )
        # paid invoice, no block, subscription or gift vouchers
        self.invoice4 = baker.make(Invoice, paid=True)
        baker.make(StripePaymentIntent, invoice=self.invoice1)
        baker.make(StripePaymentIntent, invoice=self.invoice2)
        baker.make(StripePaymentIntent, invoice=self.invoice3)
        baker.make(StripePaymentIntent, invoice=self.invoice4)

    def test_delete_unpaid_unused_invoices(self):
        # unpaid invoice, no block or subscription or gift vouchers
        invoice5 = baker.make(Invoice, paid=False)
        baker.make(StripePaymentIntent, invoice=invoice5)
        assert Invoice.objects.count() == 5
        assert StripePaymentIntent.objects.count() == 5
        management.call_command('delete_unused_invoices')
        activitylog = ActivityLog.objects.latest("id")
        assert activitylog.log == f'1 unpaid unused invoice(s) deleted: invoice_ids {invoice5.invoice_id}'
        assert Invoice.objects.count() == 4
        assert StripePaymentIntent.objects.count() == 4

    def test_delete_unpaid_unused_invoice_no_payment_intent(self):
        # unpaid invoice, no block or subscription, no associated payment intent
        baker.make(Invoice, paid=False)
        assert Invoice.objects.count() == 5
        assert StripePaymentIntent.objects.count() == 4
        management.call_command('delete_unused_invoices')
        assert Invoice.objects.count() == 4
        assert StripePaymentIntent.objects.count() == 4

    def test_no_invoices_to_delete(self):
        assert Invoice.objects.count() == 4
        management.call_command('delete_unused_invoices')
        assert Invoice.objects.count() == 4
