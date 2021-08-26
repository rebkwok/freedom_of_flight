from django.urls import path
from django.views.generic import RedirectView

from merchandise.views import ProductListView, ProductDetailView

app_name = 'merchandise'

urlpatterns = [
    path('products/', ProductListView.as_view(), name='products'),
    path('product/<int:pk>/', ProductDetailView.as_view(), name='product'),
    path('', RedirectView.as_view(url='/merchandise/products/', permanent=True)),
]
