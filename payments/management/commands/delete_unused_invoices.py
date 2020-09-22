from django.core.management.base import BaseCommand

from activitylog.models import ActivityLog
from booking.models import Invoice


class Command(BaseCommand):
    help = "Delete unused invoices (no items and unpaid)"

    def handle(self, *args, **options):
        unused_invoices = [invoice for invoice in Invoice.objects.filter(paid=False) if invoice.item_count() == 0]
        if unused_invoices:
            log = f"{len(unused_invoices)} unpaid unused invoice(s) deleted: invoice_ids {','.join([invoice.invoice_id for invoice in unused_invoices])}"
            for invoice in unused_invoices:
                invoice.delete()
            ActivityLog.objects.create(log=log)
            self.stdout.write(log)
        else:
            self.stdout.write("No unpaid unused invoices to delete")
