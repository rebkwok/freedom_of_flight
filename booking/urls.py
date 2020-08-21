from django.urls import path
from django.views.generic import RedirectView
from booking.views import (
    ajax_cart_item_delete, ajax_course_booking, ajax_toggle_booking, ajax_toggle_waiting_list,
    CourseEventsListView, BookingListView, BlockListView, BookingHistoryListView,
    disclaimer_required, home,
    EventListView, EventDetailView,
    permission_denied, event_purchase_view,
    course_purchase_view, purchase_view,
    ajax_block_purchase, shopping_basket, ajax_checkout, BlockDetailView,
    SubscriptionListView, SubscriptionDetailView,
    ajax_subscription_purchase,
)


app_name = 'booking'

urlpatterns = [
    path('schedule/', home, name="schedule"),

    # MISC
    path('disclaimer-required/<int:user_id>/', disclaimer_required, name='disclaimer_required'),
    path('not-available/', permission_denied, name='permission_denied'),

    # EVENTS
    path('event/<slug>', EventDetailView.as_view(), name='event'),
    path('ajax-toggle-booking/<int:event_id>/', ajax_toggle_booking, name='ajax_toggle_booking'),
    path('ajax-toggle-waiting-list/<int:event_id>/', ajax_toggle_waiting_list, name='toggle_waiting_list'),

    # COURSES
    path('course/<slug:course_slug>', CourseEventsListView.as_view(), name='course_events'),
    path('ajax-course-booking/<int:course_id>/', ajax_course_booking, name='ajax_course_booking'),

    # BOOKINGS
    path('bookings/', BookingListView.as_view(), name="bookings"),
    path('bookings/past/', BookingHistoryListView.as_view(), name="past_bookings"),

    # BLOCKS
    path('blocks/', BlockListView.as_view(), name="blocks"),
    path('block/<pk>/', BlockDetailView.as_view(), name="block_detail"),
    path('ajax-block-purchase/<int:block_config_id>/', ajax_block_purchase, name='ajax_block_purchase'),

    # SUBSCRIPTIONS
    path('subscriptions/', SubscriptionListView.as_view(), name="subscriptions"),
    path('subscription/<pk>/', SubscriptionDetailView.as_view(), name="subscription_detail"),
    path('ajax-subscription-purchase/<int:subscription_config_id>/', ajax_subscription_purchase, name='ajax_subscription_purchase'),

    # PAYMENT OPTIONS
    path("purchase-options/dropin-event/<slug:event_slug>/", event_purchase_view, name="event_purchase_options"),
    path("purchase-options/course/<slug:course_slug>/", course_purchase_view,  name="course_purchase_options"),
    path("purchase-options/", purchase_view, name="purchase_options"),

    # SHOPPING BASKET
    path("shopping-cart/", shopping_basket, name="shopping_basket"),
    path("ajax-checkout/", ajax_checkout, name="ajax_checkout"),
    path('ajax-cart-item-delete/', ajax_cart_item_delete, name='ajax_cart_item_delete'),

    # EVENTS LIST: needs to go last
    path('<slug:track>/', EventListView.as_view(), name='events'),

    # path('gift-vouchers/', GiftVoucherPurchaseView.as_view(), name='buy_gift_voucher'),
    # path('gift-voucher/<voucher_code>', gift_voucher_details, name='gift_voucher_details'),
    # path('gift-voucher/<voucher_code>/update', GiftVoucherPurchaseView.as_view(), name='gift_voucher_update'),
    # path('gift-voucher/<voucher_code>/delete', gift_voucher_delete, name='gift_voucher_delete'),
    path('', RedirectView.as_view(url='/schedule/', permanent=True)),
]
