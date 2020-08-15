# Generated by Django 3.0.7 on 2020-08-15 11:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0030_auto_20200814_1235'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscriptionconfig',
            name='include_no_shows_in_usage',
            field=models.BooleanField(default=False, help_text='For subscription with limits on bookings: count no-shows (i.e. cancellations after the cancellation period has passed) in subscription usage'),
        ),
    ]
