# Generated by Django 3.0.10 on 2021-04-14 21:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0013_userprofile_seller'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userprofile',
            name='student',
            field=models.BooleanField(default=False),
        ),
    ]
