from django.contrib import admin

from booking.admin import BlockInline, SubscriptionInline
from .models import Invoice, Seller


class InvoiceAdmin(admin.ModelAdmin):
    list_display = ["invoice_id", "username", "amount", "paid", "date_paid", "date_created", "item_count"]
    model = Invoice
    inlines = (BlockInline, SubscriptionInline)

    def item_count(self, obj):
        return obj.item_count()

admin.site.register(Invoice, InvoiceAdmin)
admin.site.register(Seller)
