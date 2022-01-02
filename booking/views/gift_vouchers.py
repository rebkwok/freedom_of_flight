from django.contrib import messages
from django.shortcuts import HttpResponseRedirect, get_object_or_404
from django.urls import reverse
from django.template.response import TemplateResponse
from django.views.generic import CreateView, DetailView, UpdateView

from activitylog.models import ActivityLog
from ..forms import GiftVoucherForm
from ..models import BlockVoucher, TotalVoucher, GiftVoucher, GiftVoucherConfig


class GiftVoucherFormMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.user.is_authenticated:
            kwargs['user'] = self.request.user
        return kwargs


class GiftVoucherObjectMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["voucher"] = self.object.voucher
        return context


class GiftVoucherPurchaseView(GiftVoucherFormMixin, CreateView):
    template_name = 'booking/gift_voucher_purchase.html'
    form_class = GiftVoucherForm
    model = GiftVoucher

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["gift_voucher_configs"] = GiftVoucherConfig.objects.filter(active=True)
        return context

    def form_valid(self, form):
        messages.success(self.request, "Gift Voucher added to basket")
        gift_voucher = form.save()
        resp = super().form_valid(form)
        if not self.request.user.is_authenticated:
            purchases = self.request.session.get("purchases", {})
            gift_vouchers_on_session = set(purchases.get("gift_vouchers", []))
            gift_vouchers_on_session.add(gift_voucher.id)
            purchases["gift_vouchers"] = list(gift_vouchers_on_session)
            self.request.session["purchases"] = purchases
        return resp

    def get_success_url(self):
        if self.request.user.is_authenticated:
            return reverse("booking:shopping_basket")
        else:
            return reverse("booking:guest_shopping_basket")


class GiftVoucherUpdateView(GiftVoucherFormMixin, GiftVoucherObjectMixin, UpdateView):
    template_name = 'booking/gift_voucher_purchase.html'
    form_class = GiftVoucherForm
    model = GiftVoucher

    def form_valid(self, form):
        messages.success(self.request, "Gift Voucher updated")
        return super().form_valid(form)

    def get_success_url(self):
        if self.object.paid:
            return reverse("booking:gift_voucher_details", args=(self.kwargs["slug"],))
        else:
            if self.request.user.is_authenticated:
                return reverse("booking:shopping_basket")
            else:
                return reverse("booking:guest_shopping_basket")


class GiftVoucherDetailView(GiftVoucherObjectMixin, UpdateView):
    template_name = 'booking/gift_voucher_detail.html'
    form_class = GiftVoucherForm
    model = GiftVoucher
    context_object_name = "gift_voucher"


def get_voucher(voucher_code):
    try:
        voucher = BlockVoucher.objects.get(code=voucher_code)
    except BlockVoucher.DoesNotExist:
        voucher = TotalVoucher.objects.get(code=voucher_code)
    return voucher


def voucher_details(request, voucher_code):
    voucher = get_voucher(voucher_code)
    context = {"voucher": voucher}
    if voucher.gift_voucher.exists():
        return HttpResponseRedirect(reverse("booking:gift_voucher_details", args=(voucher.gift_voucher.first().slug,)))
    return TemplateResponse(request, template='booking/gift_voucher_detail.html', context=context)

