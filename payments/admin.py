from django.contrib import admin

from booking.admin import BlockInline, SubscriptionInline
from .models import Invoice


class InvoiceAdmin(admin.ModelAdmin):
    model = Invoice
    inlines = (BlockInline, SubscriptionInline)


admin.site.register(Invoice, InvoiceAdmin)
