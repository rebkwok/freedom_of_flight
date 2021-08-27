from django.urls import path
from django.views.generic import RedirectView

from merchandise.views import ProductListView, product_purchase_view

app_name = 'merchandise'

urlpatterns = [
    path('products/', ProductListView.as_view(), name='products'),
    path('product/<int:product_id>/', product_purchase_view, name='product'),
    path('', RedirectView.as_view(url='/merchandise/products/', permanent=True)),
]
