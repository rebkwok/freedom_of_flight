from datetime import timedelta

from django.utils import timezone

from model_bakery.recipe import Recipe

from booking.models import Event, Block

now = timezone.now()
past = now - timedelta(30)
future = now + timedelta(30)


future_event = Recipe(Event, start=future, show_on_site=True)
past_event = Recipe(Event, start=past, show_on_site=True)

dropin_block = Recipe(Block)
course_block = Recipe(Block, block_config__course=True)