
from django.core.management.base import BaseCommand

from merchandise.models import ProductPurchase


class Command(BaseCommand):
    help = "Delete product purchases that have expired"

    def handle(self, *args, **options):
        ProductPurchase.cleanup_expired_purchases()
