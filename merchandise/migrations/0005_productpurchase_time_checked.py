# Generated by Django 3.2.6 on 2021-09-02 15:15

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('merchandise', '0004_alter_productpurchase_size'),
    ]

    operations = [
        migrations.AddField(
            model_name='productpurchase',
            name='time_checked',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]
