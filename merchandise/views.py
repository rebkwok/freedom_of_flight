from django.core.paginator import Paginator
from django.db.models import Count
from django.utils import timezone
from django.shortcuts import get_object_or_404, HttpResponseRedirect
from django.views.generic import CreateView, DetailView, ListView
from django.urls import reverse

from braces.views import LoginRequiredMixin

from activitylog.models import ActivityLog
from common.utils import start_of_day_in_utc, end_of_day_in_utc, end_of_day_in_local_time
from payments.models import Invoice
from booking.views.views_utils import DataPolicyAgreementRequiredMixin

from .models import Product, ProductPurchase


class ProductListView(ListView):
    model = Product
    queryset = Product.objects.filter(active=True)
    template_name = "merchandise/product_list.html"
    context_object_name = "products"


class ProductDetailView(DetailView):
    model = Product
    template_name = "merchandise/product.html"
