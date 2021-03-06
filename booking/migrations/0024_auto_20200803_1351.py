# Generated by Django 3.0.7 on 2020-08-03 13:51

from django.db import migrations
import django_extensions.db.fields


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0023_auto_20200803_1328'),
    ]

    operations = [
        migrations.AlterField(
            model_name='course',
            name='slug',
            field=django_extensions.db.fields.AutoSlugField(blank=True, editable=False, max_length=40, populate_from=['name', 'event_type', 'number_of_events'], unique=True),
        ),
    ]
