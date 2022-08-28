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
        if used_voucher_blocks.count() >= (voucher.max_vouchers * voucher.item_count):
            raise VoucherValidationError(
                f'Voucher code {voucher.code} has limited number of total uses and expired before it could be used for all applicable blocks')


def validate_total_voucher_max_total(voucher):
    if voucher.max_vouchers is not None:
        used_voucher_invoices = Invoice.objects.filter(total_voucher_code=voucher.code, paid=True)
        # exclude any uses associated with unpaid invoices
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
        # validate max vouchers by checking paid blocks/invoices only
        if isinstance(voucher, BlockVoucher):
            validate_voucher_max_total_uses(voucher, paid_only=True)
        else:
            validate_total_voucher_max_total(voucher)


def validate_unpaid_voucher_max_total_uses(user, voucher, exclude_block_id=None):
    if voucher.max_vouchers is not None:
        validate_voucher_max_total_uses(voucher, user=user, paid_only=False, exclude_block_id=exclude_block_id)


def validate_voucher_for_user(voucher, user, check_voucher_properties=True):
    # Only check blocks that haven't already had this code applied
    if check_voucher_properties:
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
    valid_blocks_in_cart = sum([1 if voucher.check_block_config(block.block_config) else 0 for block in cart_unpaid_blocks])
    if valid_blocks_in_cart == 0:
        raise VoucherValidationError(f"Code '{voucher.code}' is not valid for any blocks in your cart")
    if valid_blocks_in_cart < voucher.item_count:
        # voucher must be used for multiple items at the same time, check that there are at least
        # that many blocks in the cart
        raise VoucherValidationError(
            f"Code '{voucher.code}' can only be used for purchases of {voucher.item_count} valid blocks")


def validate_voucher_for_unpaid_block(block, voucher=None, check_voucher_properties=True):
    voucher = voucher or block.voucher
    if check_voucher_properties:
        # raise exceptions for all the voucher-related things
        validate_voucher_properties(voucher)
    validate_unpaid_voucher_max_total_uses(block.user, voucher, exclude_block_id=block.id)
    # raise exception if voucher not valid specifically for this user
    if voucher.max_per_user is not None:
        users_used_vouchers_excluding_this_one = voucher.blocks.filter(user=block.user).exclude(id=block.id).count()
        if users_used_vouchers_excluding_this_one >= (voucher.max_per_user * voucher.item_count):
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
    if voucher.item_count:
        # we can only apply a voucher with an item count to a multiple of that item count
        # i.e. if a voucher applies to 2 items bought at the same time, and we have
        # 5 in the basket, it can only be applied to 4 of them
        blocks_to_apply = (len(unpaid_blocks) // voucher.item_count) * voucher.item_count
    else:
        blocks_to_apply = len(unpaid_blocks)
    for relevant_block in unpaid_blocks[:blocks_to_apply]:
        relevant_block.voucher = voucher
        relevant_block.save()


def _verify_block_vouchers(unpaid_blocks):
    # verify any existing vouchers on blocks
    for block in unpaid_blocks:
        if block.voucher:
            try:
                validate_voucher_properties(block.voucher)
                # check the voucher is valid for this block_config (returns bool)
                if not block.voucher.check_block_config(block.block_config):
                    raise VoucherValidationError("voucher on block not valid")
                validate_voucher_for_user(block.voucher, block.user, check_voucher_properties=False)
                validate_voucher_for_unpaid_block(block, block.voucher, check_voucher_properties=False)
                # make sure we've got the enough blocks in the cart for any vouchers with item_counts
                validate_voucher_for_block_configs_in_cart(block.voucher, unpaid_blocks)
            except VoucherValidationError:
                block.voucher = None
                block.save()
    # Make sure item_count voucher have been applied to the right number of blocks
    item_count_vouchers = {block.voucher for block in unpaid_blocks if block.voucher and block.voucher.item_count > 1}
    for voucher in item_count_vouchers:
        applied_vouchers = sum([1 for block in unpaid_blocks if block.voucher == voucher])
        missing_vouchers = voucher.item_count - applied_vouchers
        if missing_vouchers > 0:
            unvouchered_blocks = [block for block in unpaid_blocks if block.voucher is None]
            if len(unvouchered_blocks) >= missing_vouchers:
                for block in unvouchered_blocks[:missing_vouchers]:
                    block.voucher = voucher
                    block.save()


def _get_and_verify_total_vouchers(request):
    total_voucher_code = request.session.get("total_voucher_code")
    if total_voucher_code:
        total_voucher = TotalVoucher.objects.get(code=total_voucher_code)
        try:
            validate_total_voucher_for_checkout_user(total_voucher, request.user)
            return total_voucher
        except VoucherValidationError:
            del request.session["total_voucher_code"]
