# Generated by Django 3.0.7 on 2020-08-03 11:53

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_auto_20200708_0657'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='cookiepolicy',
            options={'ordering': ('-version',), 'verbose_name_plural': 'Cookie Policies'},
        ),
        migrations.AlterModelOptions(
            name='dataprivacypolicy',
            options={'ordering': ('-version',), 'verbose_name_plural': 'Data Privacy Policies'},
        ),
        migrations.AlterModelOptions(
            name='disclaimercontent',
            options={'ordering': ('-version',)},
        ),
    ]
