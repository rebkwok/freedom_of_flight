
from django.core.management.base import BaseCommand

from booking.models import Block


class Command(BaseCommand):
    help = "Delete unpaid blocks with bookings that have expired"

    def handle(self, *args, **options):
        Block.cleanup_expired_blocks()
