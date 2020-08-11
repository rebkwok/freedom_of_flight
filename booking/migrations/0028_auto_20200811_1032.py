# Generated by Django 3.0.7 on 2020-08-11 10:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0027_eventtype_booking_restriction'),
    ]

    operations = [
        migrations.AlterField(
            model_name='eventtype',
            name='name',
            field=models.CharField(help_text='Name for this event type (lowercase)', max_length=255),
        ),
    ]
