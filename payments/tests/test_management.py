from model_bakery import baker

from django.core import management
from django.test import TestCase

from booking.models import Block, Subscription
from ..models import Invoice
from activitylog.models import ActivityLog


class DeleteUnusedInvoicesTests(TestCase):

    def setUp(self):
        # unpaid invoice with block
        self.invoice1 = baker.make(Invoice, blocks=baker.make(Block, paid=False, _quantity=1), paid=False)
        # unpaid invoice with subscription
        self.invoice2 = baker.make(Invoice, subscriptions=baker.make(Subscription, paid=False, _quantity=1), paid=False)
        # paid invoice, no block or subscription
        self.invoice3 = baker.make(Invoice, paid=True)

    def test_delete_unpaid_unused_invoices(self):
        # unpaid invoice, no block or subscription
        invoice4 = baker.make(Invoice, paid=False)
        assert Invoice.objects.count() == 4
        management.call_command('delete_unused_invoices')
        activitylog = ActivityLog.objects.latest("id")
        assert activitylog.log == f'1 unpaid unused invoice(s) deleted: invoice_ids {invoice4.invoice_id}'
        assert Invoice.objects.count() == 3

    def test_no_invoices_to_delete(self):
        assert Invoice.objects.count() == 3
        management.call_command('delete_unused_invoices')
        assert Invoice.objects.count() == 3
