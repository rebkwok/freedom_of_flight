# Generated by Django 4.1.2 on 2023-01-18 15:45

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("booking", "0056_blockconfig_disabled"),
    ]

    operations = [
        migrations.CreateModel(
            name="DisabledBlockConfig",
            fields=[],
            options={
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("booking.blockconfig",),
        ),
    ]
