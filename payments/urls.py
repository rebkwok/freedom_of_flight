from django.urls import path
from payments.views import paypal_return, paypal_cancel_return


app_name = 'payments'

urlpatterns = [
    path('paypal-return/', paypal_return, name="paypal_return"),
    path('cancel/', paypal_cancel_return, name='paypal_cancel'),
]