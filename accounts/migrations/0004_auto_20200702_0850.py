# Generated by Django 3.0.7 on 2020-07-02 07:50

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_auto_20200628_1758'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='userprofile',
            name='emergency_contact_name',
        ),
        migrations.RemoveField(
            model_name='userprofile',
            name='emergency_contact_phone',
        ),
        migrations.RemoveField(
            model_name='userprofile',
            name='emergency_contact_relationship',
        ),
        migrations.AddField(
            model_name='archiveddisclaimer',
            name='emergency_contact_name',
            field=models.CharField(default='test', max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='archiveddisclaimer',
            name='emergency_contact_phone',
            field=models.CharField(default=1, max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='archiveddisclaimer',
            name='emergency_contact_relationship',
            field=models.CharField(default='test', max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='onlinedisclaimer',
            name='emergency_contact_name',
            field=models.CharField(default='test', max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='onlinedisclaimer',
            name='emergency_contact_phone',
            field=models.CharField(default=1, max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='onlinedisclaimer',
            name='emergency_contact_relationship',
            field=models.CharField(default='test', max_length=255),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='nonregistereddisclaimer',
            name='emergency_contact_name',
            field=models.CharField(max_length=255),
        ),
        migrations.AlterField(
            model_name='nonregistereddisclaimer',
            name='emergency_contact_phone',
            field=models.CharField(max_length=255),
        ),
        migrations.AlterField(
            model_name='nonregistereddisclaimer',
            name='emergency_contact_relationship',
            field=models.CharField(max_length=255),
        ),
    ]