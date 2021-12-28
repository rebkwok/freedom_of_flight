import logging

from payments.models import Invoice
from common.utils import full_name
from ..models import BlockVoucher, TotalVoucher

logger = logging.getLogger(__name__)


class VoucherValidationError(Exception):
    pass


def validate_voucher_max_total_uses(voucher, paid_only=True, user=None, exclude_block_id=None):
    if voucher.max_vouchers is not None:
        used_voucher_blocks = voucher.blocks.all()
        if exclude_block_id:
            used_voucher_blocks = used_voucher_blocks.exclude(id=exclude_block_id)
        if paid_only:
            used_voucher_blocks = used_voucher_blocks.filter(paid=True)
        else:
            user_unpaid_voucher_blocks = used_voucher_blocks.filter(user=user, paid=False)
            used_voucher_blocks = used_voucher_blocks | user_unpaid_voucher_blocks
        if used_voucher_blocks.count() >= voucher.max_vouchers:
            raise VoucherValidationError(
                f'Voucher code {voucher.code} has limited number of total uses and expired before it could be used for all applicable blocks')


def validate_total_voucher_max_total_uses(voucher, paid_only=True, user=None):
    if voucher.max_vouchers is not None:
        used_voucher_invoices = Invoice.objects.filter(total_voucher_code=voucher.code)
        if paid_only:
            # exclude any associated with unpaid invoices
            used_voucher_invoices = used_voucher_invoices.filter(paid=True)
        else:
            # We're counting unpaid invoices, but still we need to
            # exclude unpaid invoices with voucher for this user
            used_voucher_invoices = used_voucher_invoices.exclude(paid=False, username=user.username)
        if used_voucher_invoices.count() >= voucher.max_vouchers:
            raise VoucherValidationError(
                f'Voucher code {voucher.code} has limited number of total uses and has expired')


def validate_voucher_properties(voucher):
    """Validate voucher properties that are not specific to number of uses"""
    if voucher.has_expired:
        raise VoucherValidationError("Voucher has expired")
    elif not voucher.activated:
        raise VoucherValidationError('Voucher has not been activated yet')
    elif not voucher.has_started:
        raise VoucherValidationError(f'Voucher code is not valid until {voucher.start_date.strftime("%d %b %y")}')
    elif voucher.max_vouchers is not None:
        # validate max vouchers for paid blocks only
        if isinstance(voucher, BlockVoucher):
            validate_voucher_max_total_uses(voucher, paid_only=True)
        else:
            validate_total_voucher_max_total_uses(voucher, paid_only=True)


def validate_unpaid_voucher_max_total_uses(user, voucher, exclude_block_id=None):
    if voucher.max_vouchers is not None:
        validate_voucher_max_total_uses(voucher, user=user, paid_only=False, exclude_block_id=exclude_block_id)


def validate_voucher_for_user(voucher, user):
    # Only check blocks that haven't already had this code applied
    validate_voucher_properties(voucher)
    if voucher.max_per_user is not None and user.blocks.filter(paid=True, voucher=voucher).count() >= voucher.max_per_user:
        raise VoucherValidationError(f'{full_name(user)} has already used voucher code {voucher.code} the maximum number of times ({voucher.max_per_user})')


def validate_total_voucher_for_checkout_user(voucher, user):
    validate_voucher_properties(voucher)
    if voucher.max_per_user is not None \
            and Invoice.objects.filter(username=user.username, paid=True, total_voucher_code=voucher.code).count() >= voucher.max_per_user:
        raise VoucherValidationError(
            f'You have already used voucher code {voucher.code} the maximum number of times ({voucher.max_per_user})')


def validate_voucher_for_block_configs_in_cart(voucher, cart_unpaid_blocks):
    if not any(voucher.check_block_config(block.block_config) for block in cart_unpaid_blocks):
        raise VoucherValidationError(f"Code {voucher.code} is not valid for any blocks in your cart")


def validate_voucher_for_unpaid_block(block, voucher=None):
    voucher = voucher or block.voucher
    # raise exceptions for all the voucher-related things
    validate_voucher_properties(voucher)
    validate_unpaid_voucher_max_total_uses(block.user, voucher, exclude_block_id=block.id)
    # raise exception if voucher not valid specifically for this user
    if voucher.max_per_user is not None:
        users_used_vouchers_excluding_this_one = voucher.blocks.filter(user=block.user).exclude(id=block.id).count()
        if users_used_vouchers_excluding_this_one >= voucher.max_per_user:
            raise VoucherValidationError(f'Voucher code {voucher.code} already used max number of times by {full_name(block.user)} (limited to {voucher.max_per_user} per user)')
    return


def get_valid_applied_voucher_info(block):
    """
    Validate codes already applied to unpaid blocks and return info
    """
    if block.voucher:
        try:
            validate_voucher_for_unpaid_block(block)
            return {"code": block.voucher.code, "discounted_cost": block.cost_with_voucher}
        except VoucherValidationError as voucher_error:
            logger.error(
                "Previously applied voucher (code %s) for block id %s, user %s is now invalid and removed: %s",
                block.voucher.code, block.id, block.user.username, voucher_error
            )
            block.voucher = None
            block.save()
    return {"code": None, "discounted_cost": None}


def apply_voucher_to_unpaid_blocks(voucher, unpaid_blocks):
    # We only do this AFTER checking the voucher is generally valid, so we don't
    # need to do that again    # no need to check counts etc, since the shopping cart view will re-validate all the applied vouchers
    for relevant_block in unpaid_blocks:
        relevant_block.voucher = voucher
        relevant_block.save()


def _verify_block_vouchers(unpaid_blocks):
    # verify any vouchers on blocks
    for block in unpaid_blocks:
        if block.voucher:
            try:
                validate_voucher_properties(block.voucher)
                validate_voucher_for_block_configs_in_cart(block.voucher, [block])
                validate_voucher_for_user(block.voucher, block.user)
                if block.voucher.check_block_config(block.block_config):
                    validate_voucher_for_unpaid_block(block, block.voucher)
                else:
                    raise VoucherValidationError("voucher on block not valid")
            except VoucherValidationError:
                block.voucher = None
                block.save()


def _get_and_verify_total_vouchers(request):
    total_voucher_code = request.session.get("total_voucher_code")
    if total_voucher_code:
        total_voucher = TotalVoucher.objects.get(code=total_voucher_code)
        try:
            validate_voucher_properties(total_voucher)
            validate_total_voucher_for_checkout_user(total_voucher, request.user)
            return total_voucher
        except VoucherValidationError:
            del request.session["total_voucher_code"]
