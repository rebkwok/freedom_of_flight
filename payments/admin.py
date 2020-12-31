from django.contrib import admin

from booking.admin import BlockInline, SubscriptionInline, GiftVoucherInline
from .models import Invoice, Seller, StripePaymentIntent


class InvoiceAdmin(admin.ModelAdmin):
    list_display = ["invoice_id", "username", "amount", "paid", "date_paid", "date_created", "item_count"]
    model = Invoice
    inlines = (BlockInline, SubscriptionInline, GiftVoucherInline)

    def item_count(self, obj):
        return obj.item_count()

admin.site.register(Invoice, InvoiceAdmin)
admin.site.register(Seller)
admin.site.register(StripePaymentIntent)
