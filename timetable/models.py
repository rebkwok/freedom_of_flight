from django.conf import settings
from django.db import models

from booking.models import EventType


class TimetableSession(models.Model):
    DAY_CHOICES = (
        ("0", 'Monday'),
        ("1", 'Tuesday'),
        ("2", 'Wednesday'),
        ("3", 'Thursday'),
        ("4", 'Friday'),
        ("5", 'Saturday'),
        ("6", 'Sunday')
    )

    name = models.CharField(max_length=255)
    event_type = models.ForeignKey(EventType, null=True, on_delete=models.SET_NULL)
    day = models.CharField(max_length=1, choices=DAY_CHOICES)
    duration = models.PositiveIntegerField(help_text="Duration in minutes", default=90)
    time = models.TimeField()
    description = models.TextField(blank=True, default="")
    max_participants = models.PositiveIntegerField(default=10)

    def get_day_name(self):
        return dict(self.DAY_CHOICES)[self.day]

    def __str__(self):
        return f"{dict(self.DAY_CHOICES)[self.day]} - {self.time.strftime('%H:%M')} - {self.name}"
