# Generated by Django 3.0.10 on 2020-11-09 16:14

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0009_invoice_voucher_code'),
    ]

    operations = [
        migrations.RenameField(
            model_name='invoice',
            old_name='voucher_code',
            new_name='total_voucher_code',
        ),
    ]
