from datetime import timedelta

from django.utils import timezone

from model_bakery.recipe import Recipe

from booking.models import Event

now = timezone.now()
past = now - timedelta(30)
future = now + timedelta(30)


future_event = Recipe(Event, start=future, show_on_site=True)
past_event = Recipe(Event, start=past, show_on_site=True)
