# Generated by Django 3.0.7 on 2020-07-03 12:40

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0007_auto_20200703_1324'),
    ]

    operations = [
        migrations.RenameField(
            model_name='blockvoucher',
            old_name='course_types',
            new_name='course_block_configs',
        ),
        migrations.RenameField(
            model_name='blockvoucher',
            old_name='block_types',
            new_name='dropin_block_configs',
        ),
    ]
