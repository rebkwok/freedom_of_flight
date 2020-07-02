# -*- coding: utf-8 -*-

from django.contrib.auth.decorators import login_required
from django.template.response import TemplateResponse


from .views_utils import data_privacy_required, disclaimer_required


@disclaimer_required
@data_privacy_required
@login_required
def shopping_basket(request):
    template_name = 'booking/shopping_basket.html'

    # Make sure the cart items is up to date; it'll be repopulated if necessary
    if "cart_items" in request.session:
        del request.session["cart_items"]

    # unpaid status for both blocks
    context = {
        "unpaid_blocks": request.user.blocks.filter(paid=False)
    }

    # blocks
    # block_code = request.GET.get('block_code', None)
    # if "block_code" in request.GET and "remove_block_voucher" not in request.GET:
    #     block_code = request.GET['block_code'].strip()
    #     context = add_block_voucher_context(block_code, request.user, context)
    # if context['unpaid_blocks']:
    #     context['block_voucher_form'] = BlockVoucherForm(
    #         initial={'block_code': block_code}
    #     )
    #     context = add_total_blocks_and_paypal_context(request, context)
    return TemplateResponse(
        request,
        template_name,
        context
    )


# def apply_voucher_to_unpaid_blocks(voucher, blocks, times_used):
#     check_max_per_user = False
#     check_max_total = False
#     max_per_user_exceeded = False
#     max_total_exceeded = False
#
#     total_block_cost = 0
#     voucher_applied_blocks = []
#     invalid_block_types = []
#
#     if voucher.max_per_user:
#         check_max_per_user = True
#         uses_per_user_left = voucher.max_per_user - times_used
#
#     if voucher.max_vouchers:
#         check_max_total = True
#         max_voucher_uses_left = (
#             voucher.max_vouchers -
#             UsedBlockVoucher.objects.filter(voucher=voucher).count()
#         )
#     for block in blocks:
#         can_use = voucher.check_block_type(block.block_type)
#         if check_max_per_user and uses_per_user_left <= 0:
#             can_use = False
#             max_per_user_exceeded = True
#         if check_max_total and max_voucher_uses_left <= 0:
#             can_use = False
#             max_total_exceeded = True
#
#         if can_use:
#             total_block_cost += Decimal(
#                 float(block.block_type.cost) * ((100 - voucher.discount) / 100)
#             ).quantize(Decimal('.05'))
#             voucher_applied_blocks.append(block.id)
#             if check_max_per_user:
#                 uses_per_user_left -= 1
#             if check_max_total:
#                 max_voucher_uses_left -= 1
#         else:
#             total_block_cost += block.block_type.cost
#             # if we can't use the voucher but max_total and
#             # max_per_user are not exceeded, it must be an invalid
#             # event type
#             if not (max_total_exceeded or max_per_user_exceeded):
#                 invalid_block_types.append(str(block.block_type))
#
#     voucher_msg = []
#     if invalid_block_types:
#         voucher_msg.append(
#             'Voucher cannot be used for some block types '
#             '({})'.format(', '.join(set(invalid_block_types)))
#         )
#     # only return one of these messages; the most relevant to the user is max_per_user
#     # if voucher is invalid for that reason
#     if max_per_user_exceeded:
#         voucher_msg.append(
#             'Voucher not applied to some blocks; you can '
#             'only use this voucher a total of {} times.'.format(
#                 voucher.max_per_user
#             )
#         )
#     elif max_total_exceeded:
#         voucher_msg.append(
#             'Voucher not applied to some blocks; voucher '
#             'has limited number of total uses.'
#         )
#
#     return {
#         'voucher_applied_blocks': voucher_applied_blocks,
#         'total_unpaid_block_cost': total_block_cost,
#         'block_voucher_msg': voucher_msg
#     }

#
# @login_required
# def submit_zero_block_payment(request):
#     # 100% gift voucher used for block(s); this doesn't go through paypal, we
#     # just mark as paid here and create a UsedBlockVoucher
#     unpaid_block_ids = json.loads(request.POST.get('unpaid_block_ids'))
#     block_code = request.POST['block_code']
#     voucher = get_object_or_404(BlockVoucher, code=block_code)
#
#     unpaid_blocks = Block.objects.filter(id__in=unpaid_block_ids)
#     for block in unpaid_blocks:
#         block.paid = True
#         block.save()
#         UsedBlockVoucher.objects.create(
#             voucher=voucher, user=block.user, block_id=block.id
#         )
#
#     # Return to shopping basket if there are unpaid bookings, else return to blocks page
#     total_unpaid_booking_cost = request.POST.get('total_unpaid_booking_cost')
#     if total_unpaid_booking_cost:
#         url = reverse('booking:shopping_basket')
#         # don't include the used block gift voucher code in return params
#         params = {}
#         if 'booking_code' in request.POST:
#             params['booking_code'] = request.POST['booking_code']
#
#         if params:
#             url += '?{}'.format(urlencode(params))
#     else:
#         url = reverse('booking:block_list')
#     return HttpResponseRedirect(url)



# def ajax_shopping_basket_blocks_total(request):
#     """Called when a block is deleted/cancelled from the shopping basket page"""
#     block_code = request.GET.get('code', '').strip()
#     context = get_unpaid_block_context(request.user)
#     if block_code:
#         context = add_block_voucher_context(block_code, request.user, context)
#     context = add_total_blocks_and_paypal_context(request, context)
#     return render(
#         request, 'booking/includes/shopping_basket_blocks_total.html', context
#     )
