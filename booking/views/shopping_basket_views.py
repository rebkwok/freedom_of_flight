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
    get_unpaid_user_managed_subscriptions, get_unpaid_user_gift_vouchers, \
    get_unpaid_user_merchandise, redirect_to_voucher_cart, get_unpaid_gift_vouchers_from_session
from .voucher_basket_utils import validate_voucher_for_user, validate_total_voucher_for_checkout_user, \
    validate_voucher_for_unpaid_block, validate_voucher_for_block_configs_in_cart, \
    validate_voucher_properties, apply_voucher_to_unpaid_blocks, get_valid_applied_voucher_info, \
    _verify_block_vouchers, _get_and_verify_total_vouchers, VoucherValidationError


logger = logging.getLogger(__name__)


def guest_shopping_basket(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse("booking:shopping_basket"))

    template_name = 'booking/shopping_basket.html'
    gift_vouchers = get_unpaid_gift_vouchers_from_session(request)
    unpaid_gift_voucher_info = [
        {
            "gift_voucher": gift_voucher,
            "cost": gift_voucher.gift_voucher_config.cost,
        } for gift_voucher in gift_vouchers
    ]
    total = calculate_user_cart_total(unpaid_gift_vouchers=gift_vouchers)

    context = {
        "unpaid_items": bool(unpaid_gift_voucher_info),
        "unpaid_block_info": [],
        "applied_voucher_codes_and_discount": [],
        "unpaid_subscription_info": [],
        "unpaid_gift_voucher_info": unpaid_gift_voucher_info,
        "unpaid_merchandise": [],
        "total_cost_without_total_voucher": total,
        "total_cost": total
    }

    return TemplateResponse(
        request,
        template_name,
        context
    )


@data_privacy_required
@redirect_to_voucher_cart
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

    unpaid_merchandise = get_unpaid_user_merchandise(request.user)

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

            def _add_voucher_error_to_list(error):
                if str(error) not in voucher_errors:
                    voucher_errors.append(str(error))

            try:
                voucher = BlockVoucher.objects.get(code=code)
            except BlockVoucher.DoesNotExist:
                try:
                    voucher = TotalVoucher.objects.get(code=code)
                    voucher_type = "total"
                except TotalVoucher.DoesNotExist:
                    _add_voucher_error_to_list(f'"{code}" is not a valid code')
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
                                            _add_voucher_error_to_list(user_voucher_error)
                                # Passed all validation checks; apply it to blocks
                                apply_voucher_to_unpaid_blocks(voucher, blocks_to_apply)
                            except VoucherValidationError as user_voucher_error:
                                _add_voucher_error_to_list(user_voucher_error)
                    else:
                        try:
                            validate_total_voucher_for_checkout_user(voucher, request.user)
                            request.session["total_voucher_code"] = voucher.code
                        except VoucherValidationError as user_voucher_error:
                            _add_voucher_error_to_list(user_voucher_error)
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
        "unpaid_items": unpaid_block_info or unpaid_subscription_info or unpaid_gift_voucher_info or unpaid_merchandise,
        "unpaid_block_info": unpaid_block_info,
        "applied_voucher_codes_and_discount": applied_voucher_codes_and_discount,
        "unpaid_subscription_info": unpaid_subscription_info,
        "unpaid_gift_voucher_info": unpaid_gift_voucher_info,
        "unpaid_merchandise": unpaid_merchandise,
        "total_cost_without_total_voucher": calculate_user_cart_total(unpaid_blocks, unpaid_subscriptions, unpaid_gift_vouchers, unpaid_merchandise),
        "total_cost": calculate_user_cart_total(unpaid_blocks, unpaid_subscriptions, unpaid_gift_vouchers, unpaid_merchandise, total_voucher)
    })

    return TemplateResponse(
        request,
        template_name,
        context
    )


def _check_items_and_get_updated_invoice(request):
    total = Decimal(request.POST.get("cart_total"))

    checked = {
        "total": total,
        "invoice": None,
        "redirect": False,
        "redirect_url": None
    }

    if request.user.is_authenticated:
        unpaid_blocks = get_unpaid_user_managed_blocks(request.user)
        unpaid_subscriptions = get_unpaid_user_managed_subscriptions(request.user)
        unpaid_gift_vouchers = get_unpaid_user_gift_vouchers(request.user)
        unpaid_merchandise = get_unpaid_user_merchandise(request.user)
        for pp in unpaid_merchandise:
            pp.mark_checked()

        if not (unpaid_blocks or unpaid_subscriptions or unpaid_gift_vouchers or unpaid_merchandise):
            messages.warning(request, "Your cart is empty")
            checked.update({"redirect": True, "redirect_url": reverse("booking:shopping_basket")})
            return checked

        _verify_block_vouchers(unpaid_blocks)
        total_voucher = _get_and_verify_total_vouchers(request)

    else:
        # guest checkout
        unpaid_blocks = unpaid_subscriptions = unpaid_merchandise = []
        total_voucher = None
        unpaid_gift_vouchers = get_unpaid_gift_vouchers_from_session(request)
        if not unpaid_gift_vouchers:
            messages.warning(request, "Your cart is empty")
            checked.update({"redirect": True, "redirect_url": reverse("booking:guest_shopping_basket")})
            return checked

    checked_total = calculate_user_cart_total(
        unpaid_blocks=unpaid_blocks,
        unpaid_subscriptions=unpaid_subscriptions,
        unpaid_gift_vouchers=unpaid_gift_vouchers,
        unpaid_merchandise=unpaid_merchandise,
        total_voucher=total_voucher
    )

    if total != checked_total:
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
    unpaid_merchandise_ids = {product_purchase.id for product_purchase in unpaid_merchandise}
    def _get_matching_invoice(invoices):
        for invoice in invoices:
            if {block.id for block in invoice.blocks.all()} == unpaid_block_ids \
                    and {subscription.id for subscription in invoice.subscriptions.all()} == unpaid_subscription_ids \
                    and {gift_voucher.id for gift_voucher in invoice.gift_vouchers.all()} == unpaid_gift_voucher_ids\
                    and {product_purchase.id for product_purchase in invoice.product_purchases.all()} == unpaid_merchandise_ids:
                return invoice

    if request.user.is_authenticated:
        username = request.user.username
    else:
        username = ""
    # check for an existing unpaid invoice for this user
    invoices = Invoice.objects.filter(username=username, paid=False)
    # if any exist, check for one where the items are the same
    invoice = _get_matching_invoice(invoices)

    if invoice is None:
        invoice = Invoice.objects.create(
            invoice_id=Invoice.generate_invoice_id(), amount=Decimal(total), username=username,
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
        for product_purchase in unpaid_merchandise:
            product_purchase.invoice = invoice
            product_purchase.save()
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
        for product_purchase in unpaid_merchandise:
            product_purchase.paid = True
            product_purchase.save()
        invoice.paid = True
        invoice.save()
        msg = []
        if unpaid_blocks or unpaid_subscriptions:
            msg.append("Payment plan(s) now ready to use.")
        if unpaid_gift_vouchers:
            msg.append("Your gift vouchers have been emailed to you.")
        if unpaid_merchandise:
            msg.append("Your merchandise purchase will be ready to collect shortly.")

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
            "description": f"{full_name(request.user) if request.user.is_authenticated else ''}-invoice#{invoice.invoice_id}",
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


def check_total(request):
    if request.user.is_authenticated:
        unpaid_blocks = get_unpaid_user_managed_blocks(request.user)
        unpaid_subscriptions = get_unpaid_user_managed_subscriptions(request.user)
        unpaid_gift_vouchers = get_unpaid_user_gift_vouchers(request.user)
        unpaid_merchandise = get_unpaid_user_merchandise(request.user)
        total_voucher = _get_and_verify_total_vouchers(request)
        _verify_block_vouchers(unpaid_blocks)
    else:
        unpaid_blocks = unpaid_subscriptions = unpaid_merchandise = []
        total_voucher = None
        unpaid_gift_vouchers = get_unpaid_gift_vouchers_from_session(request)

    checked = calculate_user_cart_total(
        unpaid_blocks=unpaid_blocks,
        unpaid_subscriptions=unpaid_subscriptions,
        unpaid_gift_vouchers=unpaid_gift_vouchers,
        unpaid_merchandise=unpaid_merchandise,
        total_voucher=total_voucher
    )
    return JsonResponse({"total": checked})
