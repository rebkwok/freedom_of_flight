# -*- coding: utf-8 -*-
from decimal import Decimal
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.sites.models import Site
from django.contrib import messages
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404, render, HttpResponseRedirect
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.urls import reverse

import stripe

from payments.models import Invoice, Seller
from payments.utils import get_paypal_form

from common.utils import full_name
from ..models import Block, BlockVoucher
from ..utils import calculate_user_cart_total
from .views_utils import data_privacy_required, get_unpaid_user_managed_blocks, get_unpaid_user_managed_subscriptions

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
        validate_voucher_max_total_uses(voucher, paid_only=True)


def validate_unpaid_voucher_max_total_uses(user, voucher, exclude_block_id=None):
    if voucher.max_vouchers is not None:
        validate_voucher_max_total_uses(voucher, user=user, paid_only=False, exclude_block_id=exclude_block_id)


def validate_voucher_for_user(voucher, user):
    # Only check blocks that haven't already had this code applied
    validate_voucher_properties(voucher)
    if voucher.max_per_user is not None and user.blocks.filter(paid=True, voucher=voucher).count() >= voucher.max_per_user:
        raise VoucherValidationError(f'{full_name(user)} has already used voucher code {voucher.code} the maximum number of times ({voucher.max_per_user})')


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


@data_privacy_required
@login_required
def shopping_basket(request):
    template_name = 'booking/shopping_basket.html'

    context = {}
    unpaid_blocks = get_unpaid_user_managed_blocks(request.user)
    unpaid_block_ids = unpaid_blocks.values_list("id", flat=True)
    unpaid_blocks_by_user = {}
    for block in unpaid_blocks:
        unpaid_blocks_by_user.setdefault(block.user, []).append(block)

    unpaid_subscriptions = get_unpaid_user_managed_subscriptions(request.user)

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
            voucher_errors = []
            try:
                voucher = BlockVoucher.objects.get(code=code)
            except BlockVoucher.DoesNotExist:
                voucher_errors.append(f'"{code}" is not a valid code')
            else:
                try:
                    # check overall user validation, not specific to the block user
                    validate_voucher_properties(voucher)
                    validate_voucher_for_block_configs_in_cart(voucher, unpaid_blocks)
                    # validate for each block user
                    for user, user_unpaid_blocks in unpaid_blocks_by_user.items():
                        try:
                            validate_voucher_for_user(voucher, user)
                            blocks_to_apply = []
                            for block in user_unpaid_blocks:
                                if voucher.check_block_config(block.block_config):
                                    try:
                                        validate_voucher_for_unpaid_block(block, voucher)
                                        blocks_to_apply.append(block)
                                    except VoucherValidationError as user_voucher_error:
                                        voucher_errors.append(str(user_voucher_error))
                            # Passed all validation checks; apply it to blocks
                            apply_voucher_to_unpaid_blocks(voucher, blocks_to_apply)
                        except VoucherValidationError as user_voucher_error:
                            voucher_errors.append(str(user_voucher_error))
                except VoucherValidationError as voucher_error:
                    voucher_errors.insert(0, str(voucher_error))
            context["voucher_add_error"] = voucher_errors
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
    applied_voucher_codes_and_discount = Block.objects.filter(id__in=unpaid_block_ids, voucher__isnull=False)\
        .order_by("voucher__code").distinct("voucher__code").values_list("voucher__code", "voucher__discount", "voucher__discount_amount")

    # calculate the unpaid subscription costs, including any partial reduced costs for current subscription periods
    unpaid_subscription_info = [
        {
            "subscription": subscription,
            "full_cost": subscription.config.cost,
            "cost": subscription.cost_as_of_today(),
        }
        for subscription in unpaid_subscriptions
    ]

    context.update({
        "unpaid_items": unpaid_block_info or unpaid_subscription_info,
        "unpaid_block_info": unpaid_block_info,
        "applied_voucher_codes_and_discount": applied_voucher_codes_and_discount,
        "unpaid_subscription_info": unpaid_subscription_info,
        "total_cost": calculate_user_cart_total(unpaid_blocks, unpaid_subscriptions)
    })

    return TemplateResponse(
        request,
        template_name,
        context
    )


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


def _check_items_and_get_updated_invoice(request):
    total = Decimal(request.POST.get("cart_total"))
    unpaid_blocks = get_unpaid_user_managed_blocks(request.user)
    unpaid_subscriptions = get_unpaid_user_managed_subscriptions(request.user)
    checked = {
        "total": total,
        "invoice": None,
        "redirect": False,
        "redirect_url": None
    }

    if not (unpaid_blocks or unpaid_subscriptions):
        messages.warning(request, "Your cart is empty")
        checked.update({"redirect": True, "redirect_url": reverse("booking:shopping_basket")})
        return checked

    _verify_block_vouchers(unpaid_blocks)
    check_total = calculate_user_cart_total(unpaid_blocks=unpaid_blocks, unpaid_subscriptions=unpaid_subscriptions)
    if total != check_total:
        messages.error(request, "Some cart items changed; please check and try again")
        checked.update({"redirect": True, "redirect_url": reverse("booking:shopping_basket")})
        return checked

    if unpaid_blocks and calculate_user_cart_total(unpaid_blocks=unpaid_blocks) == 0:
        # vouchers apply to blocks only; if we have blocks in the cart and the total for blocks only is 0, then a
        # voucher has been applied to all blocks and we can mark them as paid now
        for block in unpaid_blocks:
            block.paid = True
            block.save()
        messages.success(request, "Voucher applied successfully; block ready to use")
        checked.update({"redirect": True, "redirect_url": reverse("booking:blocks")})
        return checked

    # NOTE: invoice user will always be the request.user, not any attached sub-user
    # May be different to the user on the purchased blocks
    unpaid_block_ids = {block.id for block in unpaid_blocks}
    unpaid_subscription_ids = {subscription.id for subscription in unpaid_subscriptions}
    def _get_matching_invoice(invoices):
        for invoice in invoices:
            if {block.id for block in invoice.blocks.all()} == unpaid_block_ids \
                    and {subscription.id for subscription in invoice.subscriptions.all()} == unpaid_subscription_ids:
                return invoice

    # check for an existing unpaid invoice for this user
    invoices = Invoice.objects.filter(username=request.user.username, paid=False)
    # if any exist, check for one where the blocks and subscriptions are the same
    invoice = _get_matching_invoice(invoices)

    if invoice is None:
        invoice = Invoice.objects.create(
            invoice_id=Invoice.generate_invoice_id(), amount=Decimal(total), username=request.user.username
        )
        for block in unpaid_blocks:
            block.invoice = invoice
            block.save()
        for subscription in unpaid_subscriptions:
            subscription.invoice = invoice
            subscription.save()
    else:
        # If an invoice with the expected items is found, make sure it's total is current
        invoice.amount = Decimal(total)
        invoice.save()

    checked.update({"invoice": invoice})
    return checked


@login_required
@require_http_methods(['POST'])
def ajax_checkout(request):
    """
    Called when clicking on checkout from the shopping basket page
    Re-check the voucher codes and the total
    """
    checked_dict = _check_items_and_get_updated_invoice(request)
    if checked_dict["redirect"]:
        return JsonResponse({"redirect": True, "url": checked_dict["redirect_url"]})

    total = checked_dict["total"]
    invoice = checked_dict["invoice"]
    # encrypted custom field so we can verify it on return from paypal
    paypal_form = get_paypal_form(request, invoice)
    paypal_form_html = render(request, "payments/includes/paypal_button.html", {"form": paypal_form})
    return JsonResponse(
        {
            "paypal_form_html": paypal_form_html.content.decode("utf-8"),
        }
    )


@login_required
@require_http_methods(['POST'])
def stripe_checkout(request):
    """
    Called when clicking on checkout from the shopping basket page
    Re-check the voucher codes and the total
    """
    checked_dict = _check_items_and_get_updated_invoice(request)
    if checked_dict["redirect"]:
        return HttpResponseRedirect(checked_dict["redirect_url"])
    total = checked_dict["total"]
    invoice = checked_dict["invoice"]
    logging.info("invoice id %s", invoice.invoice_id)
    # Create the Stripe PaymentIntent
    stripe.api_key = settings.STRIPE_SECRET_KEY
    seller = Seller.objects.filter(site=Site.objects.get_current(request)).first()

    context = {}
    if seller is None:
        logger.error("No seller found on Stripe checkout attempt")
        context.update({"preprocessing_error": True})
    else:
        stripe_account = seller.stripe_user_id
        # Stripe requires the amount as an integer, in pence
        total_as_int = int(total * 100)

        payment_intent_data = {
            "payment_method_types": ['card'],
            "amount": total_as_int,
            "currency": 'gbp',
            "stripe_account": stripe_account,
            "description": f"{full_name(request.user)}-invoice#{invoice.invoice_id}",
            "metadata": {
                "invoice_id": invoice.invoice_id, "invoice_signature": invoice.signature(), **invoice.items_metadata()},
        }

        if not invoice.stripe_payment_intent_id:
            payment_intent = stripe.PaymentIntent.create(**payment_intent_data)
            invoice.stripe_payment_intent_id = payment_intent.id
            invoice.save()
        else:
            try:
                payment_intent = stripe.PaymentIntent.modify(
                    invoice.stripe_payment_intent_id, **payment_intent_data,
                )
            except stripe.error.InvalidRequestError as error:
                payment_intent = stripe.PaymentIntent.retrieve(
                    invoice.stripe_payment_intent_id, stripe_account=stripe_account
                )
                if payment_intent.status == "succeeded":
                    context.update({"preprocessing_error": True})
                    context.update({"already_paid": True})
                else:
                    context.update({"preprocessing_error": True})
                logging.error(
                    "Error processing checkout for invoice: %s, payment intent: %s (%s)", invoice.invoice_id, payment_intent.id, str(error)
                )
        context.update({
            "client_secret": payment_intent.client_secret,
            "stripe_account": stripe_account,
            "stripe_api_key": settings.STRIPE_PUBLISHABLE_KEY,
            "cart_items": invoice.items_dict(),
            "cart_total": total,
         })
    return TemplateResponse(request, "booking/checkout.html", context)


def check_total(request):
    unpaid_blocks = get_unpaid_user_managed_blocks(request.user)
    unpaid_subscriptions = get_unpaid_user_managed_subscriptions(request.user)
    _verify_block_vouchers(unpaid_blocks)
    check_total = calculate_user_cart_total(unpaid_blocks=unpaid_blocks, unpaid_subscriptions=unpaid_subscriptions)
    return JsonResponse({"total": check_total})
