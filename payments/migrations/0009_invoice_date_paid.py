# Generated by Django 3.0.7 on 2020-09-21 13:23

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0008_data_migration_update_paid_invoices_20200920_1152'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='date_paid',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
