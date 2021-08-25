# -*- coding: utf-8 -*-
from collections import Counter

from django.contrib import messages
from django.contrib.auth.models import User
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import HttpResponseRedirect, get_object_or_404, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.urls import reverse
from django.utils.safestring import mark_safe

from braces.views import LoginRequiredMixin

from common.utils import full_name
from booking.models import GiftVoucherConfig, BaseVoucher, BlockVoucher, TotalVoucher
from payments.models import Invoice
from ..forms.voucher_forms import BlockVoucherStudioadminForm, GiftVoucherConfigForm
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
            else BlockVoucher.objects.get(id=voucher.id) for voucher in self._queryset()
        ]
        return vouchers


class VoucherListView(LoginRequiredMixin, StaffUserMixin, VoucherListMixin, ListView):

    def _queryset(self):
        return BaseVoucher.objects.filter(is_gift_voucher=False).order_by('-start_date')


class GiftVoucherListView(LoginRequiredMixin, StaffUserMixin, VoucherListMixin, ListView):

    def _queryset(self):
        return BaseVoucher.objects.filter(is_gift_voucher=True).order_by('-start_date')

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
        voucher_users = []
        try:
            voucher = BlockVoucher.objects.get(id=voucher.id)
            block_voucher_users = User.objects.filter(blocks__voucher=voucher, blocks__paid=True).annotate(
                num_uses=Count("blocks")
            )
            voucher_users = [
                {"full_name": full_name(user), "email": user.email, "num_uses": user.num_uses}
                for user in block_voucher_users
            ]
        except BlockVoucher.DoesNotExist:
            voucher = TotalVoucher.objects.get(id=voucher.id)
            # A block voucher will always be associated with a user, but in future a total voucher could be
            # used by a non-logged in user (to buy gift vouchers or merchandise), so don't build the uses list
            # based on registered users
            invoice_usernames = Counter(Invoice.objects.filter(total_voucher_code=voucher.code, paid=True).values_list("username", flat=True))
            for username in invoice_usernames:
                matching_users = User.objects.filter(username__in=invoice_usernames)
                voucher_users.append(
                    {
                        "email": username,
                        "num_uses": invoice_usernames[username],
                        "full_name": full_name(matching_users[0]) if matching_users.exists() else None
                    }
                )
        context['voucher_users'] = voucher_users
        return context


class GiftVoucherConfigListView(LoginRequiredMixin, StaffUserMixin, ListView):
    model = GiftVoucherConfig
    context_object_name = "gift_voucher_configs"
    template_name = 'studioadmin/gift_voucher_configs.html'
    paginate_by = 20
    queryset = GiftVoucherConfig.objects.order_by("-active", "block_config", "discount_amount")


class GiftVoucherConfigMixin:
    model = GiftVoucherConfig
    template_name = 'studioadmin/gift_voucher_config_create_update.html'
    form_class = GiftVoucherConfigForm

    def get_success_url(self):
        return reverse("studioadmin:gift_voucher_configs")


class GiftVoucherConfigCreateView(LoginRequiredMixin, StaffUserMixin, GiftVoucherConfigMixin, CreateView):

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["new"] = True
        return context


class GiftVoucherConfigUpdateView(LoginRequiredMixin, StaffUserMixin, GiftVoucherConfigMixin, UpdateView):
    ...


@require_http_methods(['POST'])
def ajax_toggle_gift_voucher_config_active(request):
    config_id = request.POST["config_id"]
    config = get_object_or_404(GiftVoucherConfig, pk=config_id)
    config.active = not config.active
    config.save()
    ActivityLog.objects.create(
        log=f"Gift Voucher purchase option '{config.name}' "
            f"set to {'active' if config.active else 'not active'} by admin user {full_name(request.user)}"
    )
    html = render_to_string("studioadmin/includes/ajax_toggle_gift_voucher_config_active_btn.html", {"config": config}, request)
    return JsonResponse({"html": html, "active": config.active})
