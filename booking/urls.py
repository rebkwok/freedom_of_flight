from django.urls import path
from django.views.generic import RedirectView
from booking.views import (
    ajax_cart_item_delete, ajax_course_booking, ajax_toggle_booking, ajax_toggle_waiting_list,
    CourseEventsListView, BookingListView, BlockListView, BookingHistoryListView,
    disclaimer_required, home, terms_and_conditions, covid19_policy,
    EventListView, EventDetailView,
    permission_denied, event_purchase_view,
    course_purchase_view, purchase_view,
    ajax_block_purchase, shopping_basket, ajax_checkout, BlockDetailView,
    SubscriptionListView, SubscriptionDetailView,
    ajax_subscription_purchase,
    CourseListView,
    stripe_checkout, check_total,
    GiftVoucherPurchaseView, GiftVoucherUpdateView, GiftVoucherDetailView, voucher_details,
    gift_voucher_delete, guest_shopping_basket
)


app_name = 'booking'

urlpatterns = [
    path('schedule/', home, name="schedule"),

    # MISC
    path('disclaimer-required/<int:user_id>/', disclaimer_required, name='disclaimer_required'),
    path('not-available/', permission_denied, name='permission_denied'),
    path('terms-and-conditions/', terms_and_conditions, name="terms_and_conditions"),
    path('covid19-policy/', covid19_policy, name="covid19_policy"),

    # EVENTS
    path('event/<slug>', EventDetailView.as_view(), name='event'),
    path('ajax-toggle-booking/<int:event_id>/', ajax_toggle_booking, name='ajax_toggle_booking'),
    path('ajax-toggle-waiting-list/<int:event_id>/', ajax_toggle_waiting_list, name='toggle_waiting_list'),

    # COURSES
    path('<slug:track>/courses/', CourseListView.as_view(), name='courses'),
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
    path("stripe-checkout/", stripe_checkout, name="stripe_checkout"),
    path('ajax-cart-item-delete/', ajax_cart_item_delete, name='ajax_cart_item_delete'),
    path('check-total/', check_total, name="check_total"),
    path("guest-shopping-cart/", guest_shopping_basket, name="guest_shopping_basket"),

    # GIFT VOUCHERS
    path('gift-vouchers/', GiftVoucherPurchaseView.as_view(), name='buy_gift_voucher'),
    path('gift-vouchers/<slug:slug>/update', GiftVoucherUpdateView.as_view(), name='gift_voucher_update'),
    path('gift-vouchers/<slug:slug>', GiftVoucherDetailView.as_view(), name='gift_voucher_details'),
    path('vouchers/<str:voucher_code>', voucher_details, name='voucher_details'),
    path('gift-vouchers/<slug:slug>/delete', gift_voucher_delete, name='gift_voucher_delete'),

    # EVENTS LIST: needs to go last, catches everything else
    path('<slug:track>/', EventListView.as_view(), name='events'),

    path('', RedirectView.as_view(url='/schedule/', permanent=True)),
]
