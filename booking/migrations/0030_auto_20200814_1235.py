# Generated by Django 3.0.7 on 2020-08-14 12:35

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0029_auto_20200813_1553'),
    ]

    operations = [
        migrations.RenameField(
            model_name='subscriptionconfig',
            old_name='recurrence',
            new_name='recurring',
        ),
    ]
