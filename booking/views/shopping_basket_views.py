# -*- coding: utf-8 -*-
from decimal import Decimal
import logging

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from ..models import Block, BlockVoucher
from .views_utils import data_privacy_required, disclaimer_required

logger = logging.getLogger(__name__)


class VoucherValidationError(Exception):
    pass


def validate_voucher(voucher, exclude_block_id=None):
    if voucher.has_expired:
        raise VoucherValidationError("Voucher has expired")
    elif voucher.max_vouchers is not None:
        if exclude_block_id is not None:
            used_vouchers = voucher.blocks.exclude(id=exclude_block_id).count()
        else:
            used_vouchers = voucher.blocks.count()
        if used_vouchers >= voucher.max_vouchers:
            raise VoucherValidationError('Voucher has limited number of uses and has now expired')
    elif not voucher.activated:
        raise VoucherValidationError('Voucher has not been activated yet')
    elif not voucher.has_started:
        raise VoucherValidationError(f'Voucher code is not valid until {voucher.start_date.strftime("%d %b %y")}')


def validate_voucher_for_user(voucher, user, user_unpaid_blocks):
    # Only check blocks that haven't already had this code applied
    validate_voucher(voucher)
    if voucher.max_per_user is not None and user.blocks.filter(voucher=voucher).count() >= voucher.max_per_user:
        raise VoucherValidationError(f'You have already used this voucher the maximum number of times ({voucher.max_per_user})')

    if not any(voucher.check_block_config(block.block_config) for block in user_unpaid_blocks):
        raise VoucherValidationError('Code is not valid for any of the blocks in your cart')


def validate_voucher_for_unpaid_block(block):
    voucher = block.voucher
    # raise exceptions for all the voucher-related things
    validate_voucher(voucher)
    # raise exception if voucher not valid specifically for this user
    if voucher.max_per_user is not None:
        users_used_vouchers_excluding_this_one = voucher.blocks.filter(user=block.user).exclude(id=block.id).count()
        if users_used_vouchers_excluding_this_one >= voucher.max_per_user:
            raise VoucherValidationError(f'Voucher code has already been used the maximum number of times ({voucher.max_per_user})')
    return


def block_cost_with_voucher(block):
    percentage_to_pay = (100 - block.voucher.discount) / 100
    return Decimal(float(block.block_config.cost) * percentage_to_pay).quantize(Decimal('.05'))


def get_valid_applied_voucher_info(block):
    """
    Validate codes already applied to unpaid blocks and return info
    """
    if block.voucher:
        try:
            validate_voucher_for_unpaid_block(block)
            return {"code": block.voucher.code, "discounted_cost": block_cost_with_voucher(block)}
        except VoucherValidationError as voucher_error:
            block.voucher = None
            block.save()
            logger.error(
                "Previously applied voucher (code %s) for block id %s, user %s is now invalid and removed: %s",
                voucher.code, block.id, user.username, voucher_error
            )
    return {"code": None, "discounted_cost": None}


def apply_voucher_to_unpaid_blocks(voucher, unpaid_blocks):
    # We only do this AFTER checking the voucher is generally valid, so we don't
    # need to do that again
    relevant_blocks = [unpaid_block for unpaid_block in unpaid_blocks if voucher.check_block_config(unpaid_block.block_config)]
    # no need to check counts etc, since the shopping cart view will re-validate all the applied vouchers
    for relevant_block in relevant_blocks:
        relevant_block.voucher = voucher
        relevant_block.save()


@disclaimer_required
@data_privacy_required
@login_required
def shopping_basket(request):
    user = request.user
    template_name = 'booking/shopping_basket.html'

    context = {}
    unpaid_blocks = user.blocks.filter(paid=False)
    unpaid_block_ids = unpaid_blocks.values_list("id", flat=True)

    if request.method == "POST":
        code = request.POST.get("code")
        # remove any extraneous whitespace
        code = code.replace(" ", "")
        if "add_voucher_code" in request.POST:
            # verify voucher is active and available to use (not specific to blocks)
            # report error if voucher not valid
            # find unpaid blocks that don't have a code yet
            # if valid, apply this code to as many blocks as we can
            # report if not valid for use with any unpaid blocks

            try:
                voucher = BlockVoucher.objects.get(code=code)
            except BlockVoucher.DoesNotExist:
                context["voucher_add_error"] = f'"{code}" is not a valid code'
            else:
                try:
                    validate_voucher(voucher)
                    validate_voucher_for_user(voucher, user, unpaid_blocks)
                    # Passed all validation checks; apply it to blocks
                    apply_voucher_to_unpaid_blocks(voucher, unpaid_blocks)
                except VoucherValidationError as voucher_error:
                    context["voucher_add_error"] = voucher_error
        elif "remove_voucher_code" in request.POST:
            # Delete any used_vouchers for unpaid blocks
            for block in unpaid_blocks:
                if block.voucher and block.voucher.code == code:
                    block.voucher = None
                    block.save()

    voucher_applied_costs = {
        unpaid_block.id: get_valid_applied_voucher_info(unpaid_block) for unpaid_block in unpaid_blocks
    }

    # calculate the unpaid block costs after making any new updates and adding new used_vouchers
    unpaid_block_info = [
        {
            "block": block,
            "original_cost": block.block_config.cost,
            "voucher_applied": voucher_applied_costs[block.id],
        }
        for block in unpaid_blocks
    ]
    # We do this AFTER generating the voucher applied costs, as that may have modified some used vouchers if they weren't valid
    applied_voucher_codes_and_discount = user.blocks.filter(id__in=unpaid_block_ids, voucher__isnull=False)\
        .order_by("voucher__code").distinct("voucher__code").values_list("voucher__code", "voucher__discount")
    def _cost(block_info):
        if block_info["voucher_applied"]["discounted_cost"] is not None:
            return block_info["voucher_applied"]["discounted_cost"]
        return block_info["original_cost"]

    context.update({
        "unpaid_block_info": unpaid_block_info,
        "applied_voucher_codes_and_discount": applied_voucher_codes_and_discount,
        "total_cost": sum(_cost(block_info) for block_info in unpaid_block_info)
    })

    return TemplateResponse(
        request,
        template_name,
        context
    )


@login_required
@require_http_methods(['POST'])
def ajax_checkout(request):
    """
    Called when clicking on checkout from the shopping basket page
    Re-check the voucher codes and the total
    """
    total = request.POST.get("cart_total")
    user = get_object_or_404(User, pk=request.POST.get("user_id"))
    alert_message = {}
    context = {
        "checkout_clicked": True,
    }
    return render(request, "booking/includes/payment_button.txt", context)

