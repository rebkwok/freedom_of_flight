from os import environ

from django.conf import settings
from django.db import models

from hashlib import sha512
from shortuuid import ShortUUID


class Invoice(models.Model):
    # username rather than FK; in case we delete the user later, we want to keep financial info
    username = models.CharField(max_length=255)
    invoice_id = models.CharField(max_length=255)
    transaction_id = models.CharField(max_length=255, null=True, blank=True)
    amount = models.DecimalField(decimal_places=2, max_digits=8)
    business_email = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"{self.invoice_id} - {self.username} - £{self.amount}{' (paid)' if self.transaction_id else ''}"

    @classmethod
    def generate_invoice_id(cls):
        invoice_id = ShortUUID().random(length=22)
        while Invoice.objects.filter(invoice_id=invoice_id).exists():
            invoice_id = ShortUUID().random(length=22)
        return invoice_id

    def signature(self):
        return sha512((self.invoice_id + environ["INVOICE_KEY"]).encode("utf-8")).hexdigest()

    def save(self, *args, **kwargs):
        # set the default email on save, so Django doesn't think the model has changed when we're
        # testing
        if not self.business_email:
            self.business_email = settings.DEFAULT_PAYPAL_EMAIL
        super().save()