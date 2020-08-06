# Generated by Django 3.0.7 on 2020-08-03 11:53

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0020_auto_20200723_1722'),
    ]

    operations = [
        migrations.CreateModel(
            name='BlockConfig',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True, null=True)),
                ('cost', models.DecimalField(decimal_places=2, max_digits=8)),
                ('duration', models.PositiveIntegerField(blank=True, default=4, help_text='Number of weeks until block expires (from first use)', null=True)),
                ('size', models.PositiveIntegerField(help_text='Number of events in block. For a course block, the number of events in the course')),
                ('course', models.BooleanField(default=False)),
                ('active', models.BooleanField(default=False, help_text='Purchasable by users')),
                ('event_type', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='booking.EventType')),
            ],
        ),
        migrations.AddField(
            model_name='block',
            name='block_config',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='booking.BlockConfig'),
        ),
    ]