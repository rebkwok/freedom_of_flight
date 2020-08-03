# Generated by Django 3.0.7 on 2020-08-03 13:28

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0022_auto_20200803_1250'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='coursetype',
            unique_together=None,
        ),
        migrations.RemoveField(
            model_name='coursetype',
            name='event_type',
        ),
        migrations.RemoveField(
            model_name='dropinblockconfig',
            name='baseblockconfig_ptr',
        ),
        migrations.RemoveField(
            model_name='dropinblockconfig',
            name='event_type',
        ),
        migrations.RemoveField(
            model_name='blockvoucher',
            name='course_block_configs',
        ),
        migrations.RemoveField(
            model_name='blockvoucher',
            name='dropin_block_configs',
        ),
        migrations.RemoveField(
            model_name='course',
            name='course_type',
        ),
        migrations.RemoveField(
            model_name='giftvouchertype',
            name='course_block_config',
        ),
        migrations.RemoveField(
            model_name='giftvouchertype',
            name='dropin_block_config',
        ),
        migrations.DeleteModel(
            name='CourseBlockConfig',
        ),
        migrations.DeleteModel(
            name='CourseType',
        ),
        migrations.DeleteModel(
            name='DropInBlockConfig',
        ),
    ]
