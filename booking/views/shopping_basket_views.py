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

from payments.models import Invoice, Seller, StripePaymentIntent
from payments.utils import get_paypal_form

from common.utils import full_name
from ..models import Block, BlockVoucher, TotalVoucher
from ..utils import calculate_user_cart_total
from .views_utils import data_privacy_required, get_unpaid_user_managed_blocks, \
    get_unpaid_user_managed_subscriptions, get_unpaid_user_gift_vouchers


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

    unpaid_gift_vouchers = get_unpaid_user_gift_vouchers(request.user)

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
            voucher_type = "block"
            try:
                voucher = BlockVoucher.objects.get(code=code)
            except BlockVoucher.DoesNotExist:
                try:
                    voucher = TotalVoucher.objects.get(code=code)
                    voucher_type = "total"
                except TotalVoucher.DoesNotExist:
                    voucher_errors.append(f'"{code}" is not a valid code')
            if not voucher_errors:
                try:
                    # check overall user validation, not specific to the block user
                    validate_voucher_properties(voucher)
                    if voucher_type == "block":
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
                    else:
                        try:
                            validate_total_voucher_for_checkout_user(voucher, request.user)
                            request.session["total_voucher_code"] = voucher.code
                        except VoucherValidationError as user_voucher_error:
                            voucher_errors.append(str(user_voucher_error))
                except VoucherValidationError as voucher_error:
                    voucher_errors.insert(0, str(voucher_error))
            context["voucher_add_error"] = voucher_errors
        elif "remove_voucher_code" in request.POST:
            try:
                # is it a total voucher code we're removing?
                TotalVoucher.objects.get(code=code)
                if "total_voucher_code" in request.session:
                    del request.session["total_voucher_code"]
            except TotalVoucher.DoesNotExist:
                # It's a block voucher
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
    applied_voucher_codes_and_discount = list(
        Block.objects.filter(id__in=unpaid_block_ids, voucher__isnull=False)
            .order_by("voucher__code")
            .distinct("voucher__code")
            .values_list("voucher__code", "voucher__discount", "voucher__discount_amount")
        )

    total_voucher_code = request.session.get("total_voucher_code")
    if total_voucher_code:
        total_voucher = TotalVoucher.objects.get(code=total_voucher_code)
        applied_voucher_codes_and_discount.append((total_voucher.code, total_voucher.discount, total_voucher.discount_amount))
    else:
        total_voucher = None
    # calculate the unpaid subscription costs, including any partial reduced costs for current subscription periods
    unpaid_subscription_info = [
        {
            "subscription": subscription,
            "full_cost": subscription.config.cost,
            "cost": subscription.cost_as_of_today(),
        }
        for subscription in unpaid_subscriptions
    ]

    unpaid_gift_voucher_info = [
        {
            "gift_voucher": gift_voucher,
            "cost": gift_voucher.gift_voucher_config.cost,
        }
        for gift_voucher in unpaid_gift_vouchers
    ]

    context.update({
        "unpaid_items": unpaid_block_info or unpaid_subscription_info or unpaid_gift_voucher_info,
        "unpaid_block_info": unpaid_block_info,
        "applied_voucher_codes_and_discount": applied_voucher_codes_and_discount,
        "unpaid_subscription_info": unpaid_subscription_info,
        "unpaid_gift_voucher_info": unpaid_gift_voucher_info,
        "total_cost_without_total_voucher": calculate_user_cart_total(unpaid_blocks, unpaid_subscriptions, unpaid_gift_vouchers),
        "total_cost": calculate_user_cart_total(unpaid_blocks, unpaid_subscriptions, unpaid_gift_vouchers, total_voucher)
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


def _check_items_and_get_updated_invoice(request):
    total = Decimal(request.POST.get("cart_total"))
    unpaid_blocks = get_unpaid_user_managed_blocks(request.user)
    unpaid_subscriptions = get_unpaid_user_managed_subscriptions(request.user)
    unpaid_gift_vouchers = get_unpaid_user_gift_vouchers(request.user)
    checked = {
        "total": total,
        "invoice": None,
        "redirect": False,
        "redirect_url": None
    }

    if not (unpaid_blocks or unpaid_subscriptions or unpaid_gift_vouchers):
        messages.warning(request, "Your cart is empty")
        checked.update({"redirect": True, "redirect_url": reverse("booking:shopping_basket")})
        return checked

    _verify_block_vouchers(unpaid_blocks)
    total_voucher = _get_and_verify_total_vouchers(request)

    check_total = calculate_user_cart_total(
        unpaid_blocks=unpaid_blocks, unpaid_subscriptions=unpaid_subscriptions,
        unpaid_gift_vouchers=unpaid_gift_vouchers, total_voucher=total_voucher
    )
    if total != check_total:
        messages.error(request, "Some cart items changed; please check and try again")
        checked.update({"redirect": True, "redirect_url": reverse("booking:shopping_basket")})
        return checked

    # Even if the total is 0, we still need to retrieve/create the invoice first.  If a total voucher code is applied
    # we can only tell it's uses from paid invoices, so we need to mark the invoice as paid

    # NOTE: invoice user will always be the request.user, not any attached sub-user
    # May be different to the user on the purchased blocks
    unpaid_block_ids = {block.id for block in unpaid_blocks}
    unpaid_subscription_ids = {subscription.id for subscription in unpaid_subscriptions}
    unpaid_gift_voucher_ids = {gift_voucher.id for gift_voucher in unpaid_gift_vouchers}
    def _get_matching_invoice(invoices):
        for invoice in invoices:
            if {block.id for block in invoice.blocks.all()} == unpaid_block_ids \
                    and {subscription.id for subscription in invoice.subscriptions.all()} == unpaid_subscription_ids \
                    and {gift_voucher.id for gift_voucher in invoice.gift_vouchers.all()} == unpaid_gift_voucher_ids:
                return invoice

    # check for an existing unpaid invoice for this user
    invoices = Invoice.objects.filter(username=request.user.username, paid=False)
    # if any exist, check for one where the blocks and subscriptions are the same
    invoice = _get_matching_invoice(invoices)

    if invoice is None:
        invoice = Invoice.objects.create(
            invoice_id=Invoice.generate_invoice_id(), amount=Decimal(total), username=request.user.username,
            total_voucher_code=total_voucher.code if total_voucher is not None else None
        )
        for block in unpaid_blocks:
            block.invoice = invoice
            block.save()
        for subscription in unpaid_subscriptions:
            subscription.invoice = invoice
            subscription.save()
        for gift_voucher in unpaid_gift_vouchers:
            gift_voucher.invoice = invoice
            gift_voucher.save()
    else:
        # If an invoice with the expected items is found, make sure its total is current and any total voucher
        # is updated
        invoice.amount = Decimal(total)
        invoice.total_voucher_code = total_voucher.code if total_voucher is not None else None
        invoice.save()

    checked.update({"invoice": invoice})

    if total == 0:
        # if the total in the cart is 0, then a voucher has been applied to all blocks/checkout total
        # and we can mark everything as paid now
        for block in unpaid_blocks:
            block.paid = True
            block.save()
        for subscription in unpaid_subscriptions:
            subscription.paid = True
            subscription.save()
        for gift_voucher in unpaid_gift_vouchers:
            gift_voucher.paid = True
            gift_voucher.save()
            gift_voucher.activate()
            gift_voucher.send_voucher_email()
        invoice.paid = True
        invoice.save()
        msg = []
        if unpaid_blocks or unpaid_subscriptions:
            msg.append("Payment plan(s) now ready to use.")
        elif unpaid_gift_vouchers:
            msg.append("Your gift vouchers have been emailed to you.")

        messages.success(request, f"Voucher applied successfully. {'; '.join(msg)}")
        checked.update({"redirect": True, "redirect_url": reverse("booking:schedule")})

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
    logger.info("Stripe checkout for invoice id %s", invoice.invoice_id)
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
                logger.error(
                    "Error processing checkout for invoice: %s, payment intent: %s (%s)", invoice.invoice_id, payment_intent.id, str(error)
                )
        # update/create the django model PaymentIntent - this isjust for records
        StripePaymentIntent.update_or_create_payment_intent_instance(payment_intent, invoice, seller)

        context.update({
            "client_secret": payment_intent.client_secret,
            "stripe_account": stripe_account,
            "stripe_api_key": settings.STRIPE_PUBLISHABLE_KEY,
            "cart_items": invoice.items_dict(),
            "cart_total": total,
         })
    return TemplateResponse(request, "booking/checkout.html", context)


@login_required
def check_total(request):
    unpaid_blocks = get_unpaid_user_managed_blocks(request.user)
    unpaid_subscriptions = get_unpaid_user_managed_subscriptions(request.user)
    unpaid_gift_vouchers = get_unpaid_user_gift_vouchers(request.user)
    total_voucher = _get_and_verify_total_vouchers(request)
    _verify_block_vouchers(unpaid_blocks)
    check_total = calculate_user_cart_total(
        unpaid_blocks=unpaid_blocks, unpaid_subscriptions=unpaid_subscriptions,
        unpaid_gift_vouchers=unpaid_gift_vouchers, total_voucher=total_voucher
    )
    return JsonResponse({"total": check_total})
