import pytest

from model_bakery import baker

from django.core.management import call_command

from booking.models import Block, Booking


@pytest.mark.django_db
@pytest.mark.freeze_time('2017-05-21 10:00')
def test_cleanup_expired_blocks_unpaid_only(client, freezer):
    # another user's block, with booking
    unpaid = baker.make(Block)
    baker.make(Booking, block=unpaid)

    paid = baker.make(Block, paid=True)
    baker.make(Booking, block=paid)

    assert Block.objects.count() == 2
    
    freezer.move_to('2017-05-21 10:30')
    call_command("cleanup_expired_blocks")
    assert Block.objects.count() == 1
    assert Block.objects.first() == paid