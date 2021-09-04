from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count
from django.utils import timezone
from django.shortcuts import get_object_or_404, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.views.generic import CreateView, DetailView, ListView
from django.urls import reverse

from braces.views import LoginRequiredMixin

from activitylog.models import ActivityLog
from common.utils import start_of_day_in_utc, end_of_day_in_utc, end_of_day_in_local_time
from payments.models import Invoice
from booking.views.views_utils import DataPolicyAgreementRequiredMixin

from .forms import ProductPurchaseForm
from .models import Product, ProductPurchase, ProductCategory


class ProductListView(ListView):
    model = Product
    queryset = Product.objects.filter(active=True)
    template_name = "merchandise/product_list.html"
    context_object_name = "products"

    def dispatch(self, request, *args, **kwargs):
        # Cleanup purchases so user is looking at updated stock count
        ProductPurchase.cleanup_expired_purchases(use_cache=True)
        self.selected_category = None
        selected_category_id = self.request.GET.get("category")
        if selected_category_id is not None:
            try:
                self.selected_category = ProductCategory.objects.get(id=int(selected_category_id))
            except (ValueError, ProductCategory.DoesNotExist):
                self.selected_category = None
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.selected_category is not None:
            queryset = queryset.filter(category_id=self.selected_category.id)
        return queryset

    def get_context_data(self, **kwargs):
        context = super(ProductListView, self).get_context_data(**kwargs)
        context["categories"] = ProductCategory.objects.active()
        context["selected_category"] = self.selected_category
        context["selected_category_id"] = self.selected_category.id if self.selected_category else "all"
        return context


def product_purchase_view(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    template_name = "merchandise/product.html"

    if request.method == "POST":
        form = ProductPurchaseForm(request.POST, product=product)
        if form.is_valid():
            variant = form.cleaned_data["option"]
            purchase = ProductPurchase.objects.create(
                product=product, user=request.user, size=variant.size, cost=variant.cost
            )
            size_str = f" - {purchase.size}" if purchase.size else ''
            ActivityLog.objects.create(
                log=f"Purchase id {purchase.id} "
                    f"({purchase.product}{size_str}) added to cart by user {request.user}"
            )

            messages.success(request, f"{product.name} added to cart")
            return HttpResponseRedirect(reverse("merchandise:product", args=(product.id,)))
    else:
        # Cleanup purchases so user is looking at updated stock count
        ProductPurchase.cleanup_expired_purchases(use_cache=True)
        form = ProductPurchaseForm(product=product)

    context = {"product": product, "form": form}
    return TemplateResponse(request, template_name, context)
