from datetime import timedelta

from django.utils import timezone

from model_bakery.recipe import Recipe

from booking.models import Event, Block, GiftVoucher

now = timezone.now()
past = now - timedelta(30)
future = now + timedelta(30)


future_event = Recipe(Event, start=future, show_on_site=True)
past_event = Recipe(Event, start=past, show_on_site=True)

dropin_block = Recipe(Block, block_config__event_type__name="test")
course_block = Recipe(Block, block_config__course=True, block_config__event_type__name="test")

gift_voucher_10 = Recipe(
    GiftVoucher,
    gift_voucher_config__discount_amount=10,
    total_voucher__discount_amount=10
)
