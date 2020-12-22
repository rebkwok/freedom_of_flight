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


class VoucherListView(LoginRequiredMixin, StaffUserMixin, ListView):
    model = BaseVoucher
    template_name = 'studioadmin/vouchers.html'
    context_object_name = 'vouchers'
    queryset = BaseVoucher.objects.filter(is_gift_voucher=False).order_by('-start_date')
    paginate_by = 20


class GiftVoucherListView(VoucherListView):
    template_name = 'studioadmin/vouchers.html'
    context_object_name = 'vouchers'
    paginate_by = 20
    queryset = BaseVoucher.objects.filter(is_gift_voucher=True).order_by('-start_date')

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["gift_vouchers"] = True
        return context


class VoucherUpdateView(LoginRequiredMixin, StaffUserMixin, UpdateView):

    form_class = BlockVoucherStudioadminForm
    model = BaseVoucher
    template_name = 'studioadmin/voucher_create_update.html'
    context_object_name = 'voucher'

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

    def get_success_url(self, is_gift_voucher):
        if is_gift_voucher:
            return reverse('studioadmin:gift_vouchers')
        return reverse('studioadmin:vouchers')


class VoucherCreateView(LoginRequiredMixin, StaffUserMixin, CreateView):

    form_class = BlockVoucherStudioadminForm
    model = BaseVoucher
    template_name = 'studioadmin/voucher_create_update.html'
    context_object_name = 'voucher'

    def form_valid(self, form):
        voucher = form.save()
        msg = 'Voucher with code <strong>{}</strong> has been created!'.format(
            voucher.code
        )
        messages.success(self.request, mark_safe(msg))
        discount = f"£{voucher.discount_amount}" if voucher.discount_amount else f"{voucher.discount} %"

        ActivityLog.objects.create(
            log=f'Voucher code {voucher.code} (id {voucher.id}, discount {discount}) created by admin user {full_name(self.request.user)}'
        )
        return HttpResponseRedirect(self.get_success_url(voucher.id))

    def get_success_url(self, voucher_id):
        return reverse('studioadmin:edit_voucher', args=[voucher_id])


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

