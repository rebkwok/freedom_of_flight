# Generated by Django 3.0.7 on 2020-07-23 07:30

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0018_auto_20200721_2302'),
    ]

    operations = [
        migrations.AddField(
            model_name='eventtype',
            name='plural_suffix',
            field=models.CharField(default='es', help_text="A suffix to pluralize the label. E.g. 'es' for class -> classes.  If the label does not pluralise with a simple suffix, enter single and plural suffixes separated by a comma, e.g. 'y,ies' for party -> parties", max_length=10),
        ),
    ]
