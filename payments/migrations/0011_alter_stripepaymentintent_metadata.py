# Generated by Django 3.2.6 on 2021-08-27 15:59

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0010_auto_20201109_1614'),
    ]

    operations = [
        migrations.AlterField(
            model_name='stripepaymentintent',
            name='metadata',
            field=models.JSONField(),
        ),
    ]
