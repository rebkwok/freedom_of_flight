from django.urls import path
from payments.views import (
    paypal_return, paypal_cancel_return, paypal_test, stripe_payment_complete, stripe_webhook, UserInvoiceListView
)


app_name = 'payments'

urlpatterns = [
    path('paypal-return/', paypal_return, name="paypal_return"),
    path('cancel/', paypal_cancel_return, name='paypal_cancel'),
    path('paypal-test/', paypal_test, name="paypal_test"),
    path('stripe-payment-complete/', stripe_payment_complete, name="stripe_payment_complete"),
    path('stripe/webhook/', stripe_webhook, name="stripe_webhook"),
    path('account-transactions/', UserInvoiceListView.as_view(), name="user_invoices")
]
