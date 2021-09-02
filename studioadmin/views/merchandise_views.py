# -*- coding: utf-8 -*-
from collections import Counter

from django.contrib import messages
from django.contrib.auth.models import User
from django.db.models import Count
from django import forms
from django.core.exceptions import ValidationError
from django.forms.models import formset_factory
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import HttpResponseRedirect, get_object_or_404, render
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.views.decorators.http import require_http_methods
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.urls import reverse
from django.utils.safestring import mark_safe

from braces.views import LoginRequiredMixin

from common.utils import full_name
from merchandise.models import Product, ProductCategory, ProductPurchase, ProductStock, ProductVariant
from payments.models import Invoice
from ..forms.merchandise_forms import ProductCategoryCreateUpdateForm, ProductCreateUpdateForm, \
    ProductVariantForm, ProductPurchaseCreateUpdateForm, BaseProductVariantFormset
from .utils import StaffUserMixin, staff_required
from activitylog.models import ActivityLog


class ProductCategoryListView(LoginRequiredMixin, StaffUserMixin, ListView):
    model = ProductCategory
    template_name = 'studioadmin/product_category_list.html'
    context_object_name = 'categories'


class ProductCategoryMixin(LoginRequiredMixin, StaffUserMixin):
    model = ProductCategory
    template_name = 'studioadmin/product_category_create_update.html'
    context_object_name = 'category'
    form_class = ProductCategoryCreateUpdateForm

    def form_valid(self, form):
        category = form.save()
        if form.changed_data:
            self.success_log(category)
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("studioadmin:product_categories")


class ProductCategoryCreateView(ProductCategoryMixin, CreateView):
    def success_log(self, category):
        ActivityLog.objects.create(
            log=f"Product category {category.name} (id {category.id}) "
                f"created by admin user {full_name(self.request.user)}"
        )


class ProductCategoryUpdateView(ProductCategoryMixin, UpdateView):

    def success_log(self, category):
        ActivityLog.objects.create(
            log=f"Product category {category.name} (id {category.id}) "
                f"updated by admin user {full_name(self.request.user)}"
        )


class ProductListView(LoginRequiredMixin, StaffUserMixin, ListView):
    model = Product
    template_name = 'studioadmin/product_list.html'
    context_object_name = 'products'
    paginate_by = 10


class ProductMixin(LoginRequiredMixin, StaffUserMixin):
    model = Product
    form_class = ProductCreateUpdateForm
    template_name = 'studioadmin/product_create_update.html'
    context_object_name = 'product'

    def form_invalid(self, form):
        context = self.get_context_data(form=form)
        context["product_variant_formset"] = formset_factory(
            ProductVariantForm, formset=BaseProductVariantFormset, extra=1, can_delete=True
        )(self.request.POST)
        return self.render_to_response(context)

    def form_valid(self, form):
        product = form.save(commit=False)
        formset = formset_factory(
            ProductVariantForm, extra=1, can_delete=True, formset=BaseProductVariantFormset
        )(self.request.POST)
        if formset.is_valid():
            product.save()
            seen = []
            for variant_form in formset.forms:
                if variant_form.is_valid():
                    if "cost" not in variant_form.cleaned_data and "quantity_in_stock" not in variant_form.cleaned_data:
                        continue

                    if not variant_form.cleaned_data["DELETE"]:
                        variant, _ = ProductVariant.objects.get_or_create(
                            product=product, size=variant_form.cleaned_data["size"],
                            defaults={"cost": variant_form.cleaned_data["cost"]}
                        )
                        variant.cost = variant_form.cleaned_data["cost"]
                        variant.save()
                        seen.append(variant.size)
                        stock, _ = ProductStock.objects.get_or_create(product_variant=variant)
                        stock.quantity = variant_form.cleaned_data["quantity_in_stock"]
                        stock.save()
                    else:
                        # if we've seen this size already in this formset, we've already
                        # updated it and we don't want to delete. Just ignore this form.
                        if variant_form.cleaned_data["size"] not in seen:
                            try:
                                variant = ProductVariant.objects.get(
                                    product=product, size=variant_form.cleaned_data["size"],
                                )
                                variant.delete()
                            except ProductVariant.DoesNotExist:
                                ...
        else:
            context = self.get_context_data(form=form)
            context["product_variant_formset"] = formset
            return self.render_to_response(context)
        self.log_success(product)
        messages.success(self.request, "Product saved")
        return HttpResponseRedirect(self.get_success_url(product.id))

    def get_success_url(self, product_id):
        return reverse("studioadmin:edit_product", args=(product_id,))


class ProductCreateView(ProductMixin, CreateView):

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["creating"] = True
        context["product_variant_formset"] = formset_factory(ProductVariantForm, extra=6, can_delete=True)()
        return context

    def get_form_kwargs(self):
        form_kwargs = super().get_form_kwargs()
        category = self.request.GET.get("category")
        if category:
            try:
                category = ProductCategory.objects.get(id=int(category))
                form_kwargs["category_id"] = category.id
            except (ValueError, ProductCategory.DoesNotExist):
                ...
        return form_kwargs

    def log_success(self, product):
        ActivityLog.objects.create(
            log=f"Product {product.name} (id {product.id}) "
                f"created by admin user {full_name(self.request.user)}"
        )


class ProductUpdateView(ProductMixin, UpdateView):
    model = Product
    form_class = ProductCreateUpdateForm
    template_name = 'studioadmin/product_create_update.html'
    context_object_name = 'product'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product = self.get_object()
        if product.variants.exists():
            initial = []
            for variant in product.variants.all():
                stock, _ = ProductStock.objects.get_or_create(product_variant=variant)
                initial.append({"cost": variant.cost, "size": variant.size, "quantity_in_stock": stock.quantity})
            formset = formset_factory(ProductVariantForm, extra=1, can_delete=True)(initial=initial)
        else:
            formset = formset_factory(ProductVariantForm, extra=6)()
        context["product_variant_formset"] = formset
        return context

    def log_success(self, product):
        ActivityLog.objects.create(
            log=f"Product {product.name} (id {product.id}) "
                f"updated by admin user {full_name(self.request.user)}"
        )


class PurchaseListView(LoginRequiredMixin, StaffUserMixin, ListView):
    template_name = 'studioadmin/product_purchases.html'
    model = ProductPurchase
    context_object_name = 'purchases'
    paginate_by = 30

    def dispatch(self, request, *args, **kwargs):
        self.product = get_object_or_404(Product, pk=self.kwargs["product_id"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["product"] = self.product
        return context

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(product=self.product).order_by("-created_at")


class PurchaseMixin(LoginRequiredMixin, StaffUserMixin):
    template_name = 'studioadmin/product_purchase_create.html'
    model = ProductPurchase
    context_object_name = 'purchase'
    form_class = ProductPurchaseCreateUpdateForm

    def dispatch(self, request, *args, **kwargs):
        self.product = get_object_or_404(Product, pk=self.kwargs["product_id"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["product"] = self.product
        return context

    def get_form_kwargs(self):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["product"] = self.product
        return form_kwargs

    def form_valid(self, form):
        purchase = form.save(commit=False)
        if "option" in form.cleaned_data:
            variant = form.cleaned_data["option"]
            purchase.size = variant.size
            purchase.cost = variant.cost
        try:
            purchase.check_stock()
        except ValidationError:
            context = self.get_context_data()
            form.add_error("option", "Out of stock")
            context["form"] = form
            return TemplateResponse(self.request, self.template_name, context)

        purchase.save()
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("studioadmin:product_purchases", args=(self.product.id,))


class PurchaseCreateView(PurchaseMixin, CreateView):

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["creating"] = True
        return context


class PurchaseUpdateView(PurchaseMixin, UpdateView):

    ...



@require_http_methods(['POST'])
def ajax_toggle_product_active(request):
    product_id = request.POST["product_id"]
    product = get_object_or_404(Product, pk=product_id)
    product.active = not product.active
    product.save()

    ActivityLog.objects.create(
        log=f"Product {product} "
            f"set to {'active' if product.active else 'not active'} by admin user {full_name(request.user)}"
    )
    html = render_to_string("studioadmin/includes/ajax_toggle_product_active_btn.html", {"product": product}, request)
    return JsonResponse({"html": html, "active": product.active})


@require_http_methods(['POST'])
def ajax_toggle_purchase_paid(request):
    purchase_id = request.POST["purchase_id"]
    purchase = get_object_or_404(ProductPurchase, pk=purchase_id)
    purchase.paid = not purchase.paid
    purchase.save()

    ActivityLog.objects.create(
        log=f"Product {purchase} "
            f"set to {'paid' if purchase.paid else 'not paid'} by admin user {full_name(request.user)}"
    )
    html = render_to_string(
        "studioadmin/includes/ajax_toggle_purchase_paid_btn.html", {"purchase": purchase}, request
    )
    return JsonResponse(
        {"html": html, "date_paid": purchase.date_paid.strftime("%d %b %Y") if purchase.date_paid else None}
    )


@require_http_methods(['POST'])
def ajax_toggle_purchase_received(request):
    purchase_id = request.POST["purchase_id"]
    purchase = get_object_or_404(ProductPurchase, pk=purchase_id)
    purchase.received = not purchase.received
    purchase.save()

    ActivityLog.objects.create(
        log=f"Product {purchase} "
            f"set to {'received' if purchase.received else 'not received'} by admin user {full_name(request.user)}"
    )
    html = render_to_string(
        "studioadmin/includes/ajax_toggle_purchase_received_btn.html",
        {"purchase": purchase}, request
    )
    return JsonResponse(
        {"html": html, "date_received": purchase.date_received.strftime("%d %b %Y") if purchase.date_received else None}
    )


def purchases_for_collection(request):
    purchases = ProductPurchase.objects.filter(paid=True, received=False).order_by("-date_paid")
    return TemplateResponse(
        request, "studioadmin/purchases_for_collection.html", {"purchases": purchases}
    )
