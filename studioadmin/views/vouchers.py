# -*- coding: utf-8 -*-
from collections import Counter

from django.contrib import messages
from django.contrib.auth.models import User
from django.db.models import Count
from django.shortcuts import HttpResponseRedirect
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.urls import reverse
from django.utils.safestring import mark_safe

from braces.views import LoginRequiredMixin

from common.utils import full_name
from booking.models import GiftVoucher, BaseVoucher, BlockVoucher, TotalVoucher
from payments.models import Invoice
from ..forms import BlockVoucherStudioadminForm
from .utils import StaffUserMixin
from activitylog.models import ActivityLog


class VoucherListMixin:
    model = BaseVoucher
    template_name = 'studioadmin/vouchers.html'
    context_object_name = 'vouchers'
    paginate_by = 20

    def get_queryset(self):
        vouchers = [
            TotalVoucher.objects.get(id=voucher.id) if TotalVoucher.objects.filter(id=voucher.id).exists()
            else BlockVoucher.objects.get(id=voucher.id) for voucher in self.queryset
        ]
        return vouchers


class VoucherListView(LoginRequiredMixin, StaffUserMixin, VoucherListMixin, ListView):
    queryset = BaseVoucher.objects.filter(is_gift_voucher=False).order_by('-start_date')


class GiftVoucherListView(LoginRequiredMixin, StaffUserMixin, VoucherListMixin, ListView):
    queryset = BaseVoucher.objects.filter(is_gift_voucher=True).order_by('-start_date')

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["gift_vouchers"] = True
        return context


class VoucherCreateUpdateMixin:
    form_class = BlockVoucherStudioadminForm
    model = BaseVoucher
    template_name = 'studioadmin/voucher_create_update.html'
    context_object_name = 'voucher'

    def get_success_url(self, is_gift_voucher):
        if is_gift_voucher:
            return reverse('studioadmin:gift_vouchers')
        return reverse('studioadmin:vouchers')


class VoucherUpdateView(LoginRequiredMixin, StaffUserMixin, VoucherCreateUpdateMixin, UpdateView):

    def form_valid(self, form):
        voucher = form.save()
        if form.has_changed():
            discount = f"£{voucher.discount_amount}" if voucher.discount_amount else f"{voucher.discount} %"
            msg = f'Voucher with code <strong>{voucher.code}</strong> has been updated!'
            messages.success(self.request, mark_safe(msg))
            ActivityLog.objects.create(
                log=f'Voucher code {voucher.code} (id {voucher.id}, discount {discount}) updated by admin user {full_name(self.request.user)}'
            )
        else:
            messages.info(self.request, 'No changes made')
        return HttpResponseRedirect(self.get_success_url(is_gift_voucher=voucher.is_gift_voucher))


class VoucherCreateView(LoginRequiredMixin, StaffUserMixin, VoucherCreateUpdateMixin, CreateView):

    def get_form_kwargs(self):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["is_gift_voucher"] = self.kwargs.get("gift_voucher", False)
        return form_kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_gift_voucher"] = self.kwargs.get("gift_voucher", False)
        return context

    def form_valid(self, form):
        voucher = form.save()
        if self.kwargs.get("gift_voucher"):
            voucher.is_gift_voucher = True
            voucher.save()
        msg = '{} with code <strong>{}</strong> has been created!'.format(
            "Gift voucher" if voucher.is_gift_voucher else "Voucher",
            voucher.code
        )
        messages.success(self.request, mark_safe(msg))
        discount = f"£{voucher.discount_amount}" if voucher.discount_amount else f"{voucher.discount} %"

        ActivityLog.objects.create(
            log=f'Voucher code {voucher.code} (id {voucher.id}, discount {discount}) created by admin user {full_name(self.request.user)}'
        )
        return HttpResponseRedirect(self.get_success_url(is_gift_voucher=voucher.is_gift_voucher))


class VoucherDetailView(LoginRequiredMixin, StaffUserMixin, DetailView):
    model = BaseVoucher
    template_name = 'studioadmin/voucher_uses.html'
    context_object_name = 'voucher'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        voucher = context["voucher"]
        try:
            voucher = BlockVoucher.objects.get(id=voucher.id)
            voucher_users = User.objects.filter(blocks__voucher=voucher, blocks__paid=True).annotate(
                num_uses=Count("blocks"))
        except BlockVoucher.DoesNotExist:
            voucher = TotalVoucher.objects.get(id=voucher.id)
            invoice_usernames = Counter(Invoice.objects.filter(total_voucher_code=voucher.code, paid=True).values_list("username", flat=True))
            voucher_users = User.objects.filter(username__in=invoice_usernames)
            for user in voucher_users:
                user.num_uses = invoice_usernames[user.username]
        context['voucher_users'] = voucher_users
        return context

