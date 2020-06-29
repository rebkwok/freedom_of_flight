from django.urls import path
from django.views.generic import RedirectView
from booking.views import home, EventListView, EventDetailView


app_name = 'booking'

urlpatterns = [
    path('schedule/', home),
    path('<slug:track>/', EventListView.as_view(), name='events'),
    path('event/<slug>', EventDetailView.as_view(), name='event'),
    # path(
    #     'disclaimer-required/', disclaimer_required,
    #     name='disclaimer_required'
    # ),
    # path(
    #     'bookings/shopping-basket/', shopping_basket,
    #     name='shopping_basket'
    # ),
    # path(
    #     'bookings/shopping-basket/submit-block/', submit_zero_block_payment,
    #     name='submit_zero_block_payment'
    # ),
    # path(
    #     'bookings/ajax-update-shopping-basket/',
    #     update_shopping_basket_count, name='update_shopping_basket_count'
    # ),
    # path(
    #     'bookings/ajax-update-booking-count/<int:event_id>/',
    #     update_booking_count, name='update_booking_count'
    # ),
    # path(
    #     'bookings/ajax-toggle-waiting-list/<int:event_id>/',
    #     toggle_waiting_list, name='toggle_waiting_list'
    # ),
    # path(
    #     'bookings/shopping-basket-total/blocks/',
    #     ajax_shopping_basket_blocks_total, name='ajax_shopping_basket_blocks_total'
    # ),
    # path(
    #     'blocks_modal/',
    #     blocks_modal, name='blocks_modal'
    # ),
    # path('gift-vouchers/', GiftVoucherPurchaseView.as_view(), name='buy_gift_voucher'),
    # path('gift-voucher/<voucher_code>', gift_voucher_details, name='gift_voucher_details'),
    # path('gift-voucher/<voucher_code>/update', GiftVoucherPurchaseView.as_view(), name='gift_voucher_update'),
    # path('gift-voucher/<voucher_code>/delete', gift_voucher_delete, name='gift_voucher_delete'),
    path('', RedirectView.as_view(url='/schedule/', permanent=True)),
]
