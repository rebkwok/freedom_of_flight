# Generated by Django 3.0.10 on 2020-09-27 13:52

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0037_course_allow_partial_booking'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='notes',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]