from django.db import migrations


def update_date_paid(apps, schema_editor):
    Invoice = apps.get_model('payments', 'Invoice')
    PayPalIPN = apps.get_model('ipn', 'PayPalIPN')
    for invoice in Invoice.objects.all():
        if invoice.transaction_id:
            ipn = PayPalIPN.objects.filter(txn_id=invoice.transaction_id, payment_status='Completed').first()
            invoice.date_paid = ipn.payment_date
            invoice.paid = True
            invoice.save()


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0009_invoice_date_paid'),
    ]

    operations = [
        migrations.RunPython(
            update_date_paid, reverse_code=migrations.RunPython.noop
        )
    ]
