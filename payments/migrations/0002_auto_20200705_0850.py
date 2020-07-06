# Generated by Django 3.0.7 on 2020-07-05 08:50

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='amount',
            field=models.DecimalField(decimal_places=2, default=1, max_digits=8),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='invoice',
            name='username',
            field=models.CharField(default='test', max_length=255),
            preserve_default=False,
        ),
    ]