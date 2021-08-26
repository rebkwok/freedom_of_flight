from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.forms.models import formset_factory
from django.shortcuts import get_object_or_404, render, HttpResponseRedirect
from django.views.decorators.http import require_http_methods
from django.views.generic import ListView, CreateView, UpdateView
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from braces.views import LoginRequiredMixin

from openpyxl import Workbook
from openpyxl.writer.excel import save_virtual_workbook
from openpyxl.cell.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font

from activitylog.models import ActivityLog
from booking.models import EventType, BlockConfig, SubscriptionConfig, Subscription, Block
from common.utils import full_name

from ..forms import BlockConfigForm, SubscriptionConfigForm, BookableEventTypesForm
from .utils import staff_required, StaffUserMixin


@login_required
@staff_required
def block_config_list_view(request):
    block_configs = BlockConfig.objects.all().order_by("-active")
    context = {
        "block_config_groups": {
            "Drop-in Credit Blocks": block_configs.exclude(course=True),
            "Course Credit Blocks": block_configs.filter(course=True),
        }
    }
    return render(request, "studioadmin/credit_blocks.html", context)


class BlockPurchaseList(LoginRequiredMixin, StaffUserMixin, ListView):

    model = Block
    template_name = "studioadmin/credit_block_purchases.html"
    context_object_name = "purchased_blocks"
    paginate_by = 30

    def dispatch(self, request, *args, **kwargs):
        self.block_config = get_object_or_404(BlockConfig, pk=kwargs["block_config_id"])
        return super(BlockPurchaseList, self).dispatch(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(block_config=self.block_config, paid=True).order_by("-purchase_date")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["block_config"] = self.block_config
        return context


@login_required
@staff_required
def download_block_config_purchases(request, block_config_id):
    block_config = get_object_or_404(BlockConfig, pk=block_config_id)
    purchased_blocks = Block.objects.filter(block_config=block_config, paid=True).order_by("-purchase_date")

    filename = f"{slugify(block_config.name)}_purchases_{timezone.now().isoformat()}.xlsx"

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename={filename}'

    header_font = Font(name='Calibri', size=12, bold=True)
    cell_font = Font(name='Calibri', size=11, bold=False)
    alignment = Alignment(wrap_text=True)

    wb = Workbook()
    sheet = wb.active

    def _write_row(data, is_header=False):
        font = header_font if is_header else cell_font
        row = []
        for cell in data:
            cell = WriteOnlyCell(sheet, cell)
            cell.font = font
            cell.alignment = alignment
            row.append(cell)
        sheet.append(row)

    header = [
        "User", "Purchase Date", "Cost", "Discount Code", "Invoice #"
    ]
    col_widths = [20, 16, 10, 16, 24]

    _write_row(header, is_header=True)

    for block in purchased_blocks:
        row = [
            full_name(block.user),
            block.purchase_date.strftime("%d-%b-%Y"),
            block.cost_with_voucher,
            block.voucher.code if block.voucher else "",
            block.invoice.invoice_id if block.invoice else ""
        ]

        _write_row(row)

    for i, column_cells in enumerate(sheet.columns):
        sheet.column_dimensions[column_cells[0].column_letter].width = col_widths[i]

    workbook = save_virtual_workbook(wb)
    container = [response.make_bytes(workbook)]
    response.content = b''.join(container)
    return response


@require_http_methods(['POST'])
def ajax_toggle_block_config_active(request):
    block_config_id = request.POST["block_config_id"]
    block_config = get_object_or_404(BlockConfig, pk=block_config_id)
    block_config.active = not block_config.active
    block_config.save()
    ActivityLog.objects.create(
        log=f"Credit block '{block_config.name}' "
            f"set to {'active' if block_config.active else 'not active'} by admin user {full_name(request.user)}"
    )
    return render(request, "studioadmin/includes/ajax_toggle_block_config_active_btn.html", {"block_config": block_config})


@login_required
@staff_required
def block_config_delete_view(request, block_config_id):
    block_config = get_object_or_404(BlockConfig, pk=block_config_id)
    if block_config.block_set.filter(paid=True).exists():
        return HttpResponseBadRequest("Cannot delete credit block; blocks have already been purchased")
    ActivityLog.objects.create(
        log=f"Credit block {block_config.name} (id {block_config_id}) deleted by admin user {full_name(request.user)}"
    )
    block_config.delete()
    return JsonResponse({"deleted": True, "alert_msg": "Credit block deleted"})


@login_required
@staff_required
def choose_block_config_type(request):
    if request.method == "POST":
        if "dropin" in request.POST:
            return HttpResponseRedirect(reverse("studioadmin:add_block_config", args=("dropin",)))
        elif "course" in request.POST:
            return HttpResponseRedirect(reverse("studioadmin:add_block_config", args=("course",)))
    return render(request, "studioadmin/includes/block-config-add-modal.html")


class BlockConfigCreateView(LoginRequiredMixin, StaffUserMixin, CreateView):
    model = BlockConfig
    template_name = "studioadmin/block_config_create_update.html"
    form_class = BlockConfigForm

    def dispatch(self, request, *args, **kwargs):
        self.block_config_type = kwargs["block_config_type"]
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["is_course"] = True if self.block_config_type == "course" else False
        return form_kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["creating"] = True
        context["block_config_type"] = "Course" if self.block_config_type == "course" else "Drop-in"
        return context

    def get_success_url(self):
        return reverse("studioadmin:block_configs")


class BlockConfigUpdateView(LoginRequiredMixin, StaffUserMixin, UpdateView):
    model = BlockConfig
    form_class = BlockConfigForm
    template_name = "studioadmin/block_config_create_update.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["block_config_type"] = "Course" if self.object.course else "Drop-In"
        return context

    def get_form_kwargs(self):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["is_course"] = True if self.object.course else False
        return form_kwargs

    def form_valid(self, form):
        form.save()
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("studioadmin:block_configs")


@login_required
@staff_required
def subscription_config_list_view(request):
    subscription_configs = SubscriptionConfig.objects.all().order_by("-active")
    context = {"subscription_configs": subscription_configs}
    return render(request, "studioadmin/subscription_configs.html", context)


@require_http_methods(['POST'])
def ajax_toggle_subscription_config_active(request):
    subscription_config_id = request.POST["subscription_config_id"]
    subscription_config = get_object_or_404(SubscriptionConfig, pk=subscription_config_id)
    subscription_config.active = not subscription_config.active
    subscription_config.save()
    ActivityLog.objects.create(
        log=f"Subscription config '{subscription_config.name}' "
            f"set to {'active' if subscription_config.active else 'not active'} by admin user {full_name(request.user)}"
    )
    return render(
        request, "studioadmin/includes/ajax_toggle_subscription_config_active_btn.html",
      {"subscription_config": subscription_config}
    )


@login_required
@staff_required
def subscription_config_delete_view(request, subscription_config_id):
    subscription_config = get_object_or_404(SubscriptionConfig, pk=subscription_config_id)
    if subscription_config.subscription_set.filter(paid=True).exists():
        return HttpResponseBadRequest("Subscription has already been purchased, cannot delete")
    ActivityLog.objects.create(
        log=f"Subscription config {subscription_config.name} (id {subscription_config_id}) deleted by admin user {full_name(request.user)}"
    )
    subscription_config.delete()
    return JsonResponse({"deleted": True, "alert_msg": "Subscription deleted"})


@login_required
@staff_required
def choose_subscription_config_type(request):
    if request.method == "POST":
        if "one_off" in request.POST:
            subscription_type = "one_off"
        elif "recurring" in request.POST:
            subscription_type = "recurring"
        return HttpResponseRedirect(reverse("studioadmin:add_subscription_config", args=(subscription_type,)))
    return render(request, "studioadmin/includes/subscription-config-add-modal.html")


class SubscriptionConfigMixin(LoginRequiredMixin, StaffUserMixin):
    model = SubscriptionConfig
    template_name = "studioadmin/subscription_config_create_update.html"
    form_class = SubscriptionConfigForm

    def get_form_kwargs(self):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["recurring"] = self.recurring
        return form_kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["config_type"] = "recurring" if self.recurring else "one-off"
        return context

    def form_invalid(self, form):
        context = self.get_context_data(form=form)
        context["bookable_event_types_formset"] = formset_factory(BookableEventTypesForm, extra=1, can_delete=True)(self.request.POST)
        return self.render_to_response(context)

    def form_valid(self, form):
        subscription_config = form.save(commit=False)
        total_formset_forms = int(form.data['form-TOTAL_FORMS'])
        bookable_event_types = {}
        for i in range(total_formset_forms):
            event_type = form.data[f"form-{i}-event_type"]
            deleting = form.data.get(f"form-{i}-DELETE")
            if event_type and not deleting:
                allowed_number = form.data[f"form-{i}-allowed_number"]
                if allowed_number:
                    allowed_number = int(allowed_number)
                allowed_unit = form.data[f"form-{i}-allowed_unit"]
                bookable_event_types[event_type] = {"allowed_number": allowed_number, "allowed_unit": allowed_unit}
        subscription_config.bookable_event_types = bookable_event_types
        subscription_config.save()
        self.log_success(subscription_config)
        messages.success(self.request, "Subscription saved")
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("studioadmin:subscription_configs")


class SubscriptionConfigCreateView(SubscriptionConfigMixin, CreateView):

    def dispatch(self, request, *args, **kwargs):
        self.recurring = kwargs["subscription_config_type"] == "recurring"
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["creating"] = True
        total_event_types = EventType.objects.count()
        context["bookable_event_types_formset"] = formset_factory(BookableEventTypesForm, extra=min(4, total_event_types))()
        return context

    def log_success(self, subscription_config):
        ActivityLog.objects.create(
            log=f"Subscription config {subscription_config.name} (id {subscription_config.id}) "
                f"created by admin user {full_name(self.request.user)}"
        )


class SubscriptionConfigUpdateView(SubscriptionConfigMixin, UpdateView):

    def dispatch(self, request, *args, **kwargs):
        self.recurring = self.get_object().recurring
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        config = self.get_object()
        total_event_types = EventType.objects.count()
        if config.bookable_event_types:
            initial = [
                {"event_type": key, "allowed_number": usuage["allowed_number"], "allowed_unit": usuage["allowed_unit"]}
                for key, usuage in config.bookable_event_types.items()
            ]
            formset = formset_factory(BookableEventTypesForm, extra=min(4, total_event_types-len(initial)), can_delete=True)(initial=initial)
        else:
            formset = formset_factory(BookableEventTypesForm, extra=min(4, total_event_types))()
        context["bookable_event_types_formset"] = formset
        return context

    def log_success(self, subscription_config):
        ActivityLog.objects.create(
            log=f"Subscription config {subscription_config.name} (id {subscription_config.id}) "
                f"updated by admin user {full_name(self.request.user)}"
        )


@login_required
@staff_required
def clone_subscription_config_view(request, subscription_config_id):
    config_to_clone = get_object_or_404(SubscriptionConfig, id=subscription_config_id)
    config_to_clone.id = None
    cloned_name = f"Copy of {config_to_clone.name}"
    config_to_clone.active = False
    while SubscriptionConfig.objects.filter(name=cloned_name).exists():
        cloned_name = f"Copy of {cloned_name}"
    config_to_clone.name = cloned_name
    config_to_clone.save()
    messages.success(request, f"Subscription cloned with name {cloned_name}")
    ActivityLog.objects.create(
        log=f"Subscription config {config_to_clone.name} (id {config_to_clone.id}) created by admin user {full_name(request.user)}"
    )
    return HttpResponseRedirect(reverse("studioadmin:subscription_configs"))


class SubscriptionListView(LoginRequiredMixin, StaffUserMixin, ListView):

    model = Subscription
    template_name = "studioadmin/purchased_subscriptions.html"
    context_object_name = "subscriptions"
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.GET.get("show-all"):
            return queryset.filter(
                paid=True, config_id=self.kwargs["config_id"]
            ).order_by("-expiry_date", "-start_date", "-purchase_date")
        return queryset.filter(
            paid=True, config_id=self.kwargs["config_id"], expiry_date__gte=timezone.now()
        ).order_by("-expiry_date", "-start_date", "-purchase_date")

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["subscription_config"] = SubscriptionConfig.objects.get(id=self.kwargs["config_id"])
        if self.request.GET.get("show-all"):
            context["show_all"] = True
        return context