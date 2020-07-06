from django.urls import path
from django.views.generic import RedirectView
from booking.views import (
    ajax_block_delete, ajax_course_booking, ajax_toggle_booking, ajax_toggle_waiting_list,
    CourseEventsListView, BookingListView, BlockListView,
    disclaimer_required, home,
    EventListView, EventDetailView, placeholder,
    permission_denied, dropin_block_purchase_view,
    course_block_purchase_view, block_purchase_view, ajax_course_block_purchase,
    ajax_dropin_block_purchase, shopping_basket, ajax_checkout
)


app_name = 'booking'

urlpatterns = [
    path('schedule/', home),

    # MISC
    path('disclaimer-required/', disclaimer_required, name='disclaimer_required'),
    path('not-available/', permission_denied, name='permission_denied'),

    path('placeholder/', placeholder, name='placeholder'),

    # EVENTS
    path('event/<slug>', EventDetailView.as_view(), name='event'),
    path('ajax-toggle-booking/<int:event_id>/', ajax_toggle_booking, name='ajax_toggle_booking'),
    path('ajax-toggle-waiting-list/<int:event_id>/', ajax_toggle_waiting_list, name='toggle_waiting_list'),

    # COURSES
    path('course/<slug:course_slug>', CourseEventsListView.as_view(), name='course_events'),
    path('ajax-course-booking/<int:course_id>/', ajax_course_booking, name='ajax_course_booking'),

    # BOOKINGS
    path('bookings/', BookingListView.as_view(), name="bookings"),

    # BLOCKS
    path('blocks/active/', BlockListView.as_view(), name="blocks"),
    path("blocks/purchase-options/dropin/<slug:event_slug>/", dropin_block_purchase_view, name="dropin_block_purchase"),
    path("blocks/purchase-options/course/<slug:course_slug>/", course_block_purchase_view, name="course_block_purchase"),
    path("blocks/purchase-options/", block_purchase_view, name="block_purchase"),
    path('ajax-block-purchase/course/<int:block_config_id>/', ajax_course_block_purchase, name='ajax_block_purchase'),
    path('ajax-block-purchase/dropin/<int:block_config_id>/', ajax_dropin_block_purchase, name='ajax_block_purchase'),

    # SHOPPING BASKET
    path("shopping-cart/", shopping_basket, name="shopping_basket"),
    path("ajax-checkout/", ajax_checkout, name="ajax_checkout"),
    path('ajax-block-delete/<int:block_id>/', ajax_block_delete, name='ajax_block_delete'),


    # EVENTS LIST: needs to go last
    path('<slug:track>/', EventListView.as_view(), name='events'),
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
