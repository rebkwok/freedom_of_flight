# Generated by Django 3.0.7 on 2020-09-20 11:40

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0006_invoice_stripe_payment_intent_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='date_created',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name='invoice',
            name='paid',
            field=models.BooleanField(default=False),
        ),
    ]
