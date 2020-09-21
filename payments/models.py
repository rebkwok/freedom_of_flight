from os import environ

from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.conf import settings
from django.db import models
from django.utils import timezone

from hashlib import sha512
from shortuuid import ShortUUID


class Invoice(models.Model):
    # username rather than FK; in case we delete the user later, we want to keep financial info
    username = models.CharField(max_length=255)
    invoice_id = models.CharField(max_length=255)
    transaction_id = models.CharField(max_length=255, null=True, blank=True)
    amount = models.DecimalField(decimal_places=2, max_digits=8)
    business_email = models.CharField(max_length=255, null=True, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=255, null=True, blank=True)
    # register date created so we can periodically delete any unpaid ones that were created by a user going to the
    # checkout and changing their mind
    date_created = models.DateTimeField(default=timezone.now)
    paid = models.BooleanField(default=False)
    date_paid = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-date_paid",)

    def __str__(self):
        return f"{self.invoice_id} - {self.username} - £{self.amount}{' (paid)' if self.paid else ''}"

    @classmethod
    def generate_invoice_id(cls):
        invoice_id = ShortUUID().random(length=22)
        while Invoice.objects.filter(invoice_id=invoice_id).exists():
            invoice_id = ShortUUID().random(length=22)
        return invoice_id

    def signature(self):
        return sha512((self.invoice_id + environ["INVOICE_KEY"]).encode("utf-8")).hexdigest()

    def items_dict(self):
        def _block_cost_str(block):
            if block.voucher:
                return f"£{block.cost_with_voucher} (voucher applied: {block.voucher.code})"
            return f"£{block.block_config.cost}"
        blocks = {
            f"block-{item.id}": {
                "name": item.block_config.name, "cost": _block_cost_str(item), "user": item.user
            } for item in self.blocks.all()
        }
        subscriptions = {
            f"subscription-{item.id}": {
                "name": item.config.name, "cost": f"£{item.cost_as_of_today()}", "user": item.user
            } for item in self.subscriptions.all()
        }
        return {**blocks, **subscriptions}

    def items_metadata(self):
        # This is used for the payment intent metadata, which is limited to 40 chars keys and string values
        items = self.items_dict()
        return {
            item["name"][:40]: item["cost"] for item in items.values()
        }

    def save(self, *args, **kwargs):
        # set the default email on save, so Django doesn't think the model has changed when we're
        # testing
        if not self.business_email:
            self.business_email = settings.DEFAULT_PAYPAL_EMAIL
        if self.transaction_id:
            # If it has a paypal transaction ID, it's paid
            self.paid = True
        if self.paid and not self.date_paid:
            self.date_paid = timezone.now()
        super().save()


class Seller(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    site = models.OneToOneField(Site, on_delete=models.CASCADE, null=True, blank=True)
    stripe_user_id = models.CharField(max_length=255, blank=True)
    stripe_access_token = models.CharField(max_length=255, blank=True)
    stripe_refresh_token = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.user.email
