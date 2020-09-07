# -*- coding: utf-8 -*-

from django.contrib import messages
from django.contrib.auth.models import User
from django.db.models import Count
from django.shortcuts import HttpResponseRedirect
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.urls import reverse
from django.utils.safestring import mark_safe

from braces.views import LoginRequiredMixin

from common.utils import full_name
from booking.models import GiftVoucher, BlockVoucher
from ..forms import BlockVoucherStudioadminForm
from .utils import StaffUserMixin
from activitylog.models import ActivityLog


class VoucherListView(LoginRequiredMixin, StaffUserMixin, ListView):
    model = BlockVoucher
    template_name = 'studioadmin/vouchers.html'
    context_object_name = 'vouchers'
    queryset = BlockVoucher.objects.filter(is_gift_voucher=False).order_by('-start_date')
    paginate_by = 20


class GiftVoucherListView(VoucherListView):
    template_name = 'studioadmin/vouchers.html'
    context_object_name = 'vouchers'
    paginate_by = 20
    queryset = BlockVoucher.objects.filter(is_gift_voucher=True).order_by('-start_date')

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["gift_vouchers"] = True
        return context


class VoucherUpdateView(LoginRequiredMixin, StaffUserMixin, UpdateView):

    form_class = BlockVoucherStudioadminForm
    model = BlockVoucher
    template_name = 'studioadmin/voucher_create_update.html'
    context_object_name = 'voucher'

    def form_valid(self, form):
        if form.has_changed():
            voucher = form.save()
            msg = 'Voucher with code <strong>{}</strong> has been updated!'.format(
                voucher.code
            )
            messages.success(self.request, mark_safe(msg))
            ActivityLog.objects.create(
                log=f'Voucher code {voucher.code} (id {voucher.id}) updated by admin user {full_name(self.request.user)}'
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
    model = BlockVoucher
    template_name = 'studioadmin/voucher_create_update.html'
    context_object_name = 'voucher'

    def form_valid(self, form):
        voucher = form.save()
        msg = 'Voucher with code <strong>{}</strong> has been created!'.format(
            voucher.code
        )
        messages.success(self.request, mark_safe(msg))
        ActivityLog.objects.create(
            log=f'Voucher code {voucher.code} (id {voucher.id}) created by admin user {full_name(self.request.user)}'
        )
        return HttpResponseRedirect(self.get_success_url(voucher.id))

    def get_success_url(self, voucher_id):
        return reverse('studioadmin:edit_voucher', args=[voucher_id])


class VoucherDetailView(LoginRequiredMixin, StaffUserMixin, DetailView):
    model = BlockVoucher
    template_name = 'studioadmin/voucher_uses.html'
    context_object_name = 'voucher'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        voucher = context["voucher"]
        voucher_users = User.objects.filter(blocks__voucher=voucher, blocks__paid=True).annotate(num_uses=Count("blocks"))
        context['voucher_users'] = voucher_users
        return context

