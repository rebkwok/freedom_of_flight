from django.urls import path, re_path
from django.views.generic import RedirectView
from django.views.i18n import JavaScriptCatalog
from studioadmin.views import (
    help,
    EventAdminListView, ajax_toggle_event_visible, RegisterListView, register_view,
    ajax_add_register_booking, ajax_toggle_attended,
    ajax_remove_from_waiting_list, event_waiting_list_view, cancel_event_view,
    event_create_choice_view, EventCreateView, EventUpdateView, clone_event, PastEventAdminListView,
    CourseAdminListView, course_create_choice_view, CourseCreateView, CourseUpdateView, PastCourseAdminListView,
    ajax_toggle_course_visible, cancel_course_view, clone_course_view, NotStartedYetCourseAdminListView,
    TimetableSessionListView, ajax_timetable_session_delete, timetable_session_create_choice_view,
    TimetableSessionCreateView, TimetableSessionUpdateView, clone_timetable_session_view,
    upload_timetable_view, email_event_users_view, email_course_users_view,
    TrackCreateView, TrackListView, TrackUpdateView, EventTypeListView, toggle_track_default,
    choose_track_for_event_type, EventTypeCreateView, EventTypeUpdateView, event_type_delete_view,
    block_config_list_view, ajax_toggle_block_config_active, block_config_delete_view, choose_block_config_type,
    BlockConfigCreateView, BlockConfigUpdateView,
    subscription_config_list_view, ajax_toggle_subscription_config_active, subscription_config_delete_view,
    choose_subscription_config_type, SubscriptionConfigCreateView, SubscriptionConfigUpdateView, clone_subscription_config_view,
    SubscriptionListView,
    CookiePolicyListView, DataPrivacyPolicyListView, DisclaimerContentListView,
    CookiePolicyDetailView, DataPrivacyPolicyDetailView, DisclaimerContentDetailView,
    DisclaimerContentCreateView, DisclaimerContentUpdateView, CookiePolicyCreateView, DataPrivacyPolicyCreateView,
    UserListView, UserDetailView, UserBookingsListView, BookingAddView, BookingEditView,
    UserBookingsHistoryListView,
    UserBlocksListView, BlockAddView, BlockEditView, ajax_block_delete,
    email_subscription_users_view,
    UserSubscriptionsListView, SubscriptionAddView, SubscriptionEditView, ajax_subscription_delete,
    course_booking_add_view, course_block_change_view, export_users,
    ajax_toggle_course_partial_booking, email_waiting_list_view, users_with_unused_blocks,
    StripeAuthorizeView, connect_stripe_view, StripeAuthorizeCallbackView, InvoiceListView,
    VoucherDetailView, VoucherUpdateView, VoucherCreateView, VoucherListView, GiftVoucherListView,
)

app_name = 'studioadmin'


urlpatterns = [
    path('events/', EventAdminListView.as_view(), name='events'),
    path('events/past/', PastEventAdminListView.as_view(), name='past_events'),
    path('event/<slug>/cancel/', cancel_event_view, name='cancel_event'),
    path('ajax-toggle-event-visible/<int:event_id>/', ajax_toggle_event_visible, name="ajax_toggle_event_visible"),
    path('event/create/', event_create_choice_view, name="choose_event_type_to_create"),
    path('event/<slug:event_slug>/clone/', clone_event, name="clone_event"),
    path('event/<int:event_type_id>/create/', EventCreateView.as_view(), name="create_event"),
    path('event/<slug>/update/', EventUpdateView.as_view(), name="update_event"),
    path('event/<event_slug>/email-students/', email_event_users_view, name="email_event_users"),

    path('timetable/', TimetableSessionListView.as_view(), name='timetable'),
    path('timetable/session/<int:timetable_session_id>/delete/', ajax_timetable_session_delete, name="ajax_timetable_session_delete"),
    path('timetable/session/create/', timetable_session_create_choice_view, name="choose_event_type_timetable_session_to_create"),
    path('timetable/session/<int:event_type_id>/create/', TimetableSessionCreateView.as_view(), name="create_timetable_session"),
    path('timetable/session/<int:pk>/update/', TimetableSessionUpdateView.as_view(), name="update_timetable_session"),
    path('timetable/session/<int:session_id>/clone/', clone_timetable_session_view, name="clone_timetable_session"),
    path('timetable/upload/', upload_timetable_view, name="upload_timetable"),

    path('courses/', CourseAdminListView.as_view(), name='courses'),
    path('courses/past/', PastCourseAdminListView.as_view(), name='past_courses'),
    path('courses/not-started/', NotStartedYetCourseAdminListView.as_view(), name='not_started_courses'),
    path('course/<slug>/cancel/', cancel_course_view, name='cancel_course'),
    path('ajax-toggle-course-visible/<int:course_id>/', ajax_toggle_course_visible, name="ajax_toggle_course_visible"),
    path(
        'ajax-toggle-course-allow-partial-booking/<int:course_id>/',
        ajax_toggle_course_partial_booking, name="ajax_toggle_course_allow_partial_booking"
    ),
    path('course/create/', course_create_choice_view, name="choose_course_type_to_create"),
    path('course/<int:event_type_id>/create/', CourseCreateView.as_view(), name="create_course"),
    path('course/<slug>/update/', CourseUpdateView.as_view(), name="update_course"),
    path('course/<course_slug>/email-students/', email_course_users_view, name="email_course_users"),
    path('course/<course_id>/clone/', clone_course_view, name="clone_course"),

    path('registers/', RegisterListView.as_view(), name='registers'),
    path('registers/<int:event_id>', register_view, name='register'),
    path('registers/<int:event_id>/ajax-add-booking/', ajax_add_register_booking, name='bookingregisteradd'),
    path('register/<int:booking_id>/ajax-toggle-attended/', ajax_toggle_attended, name='ajax_toggle_attended'),

    path('waiting-list/<int:event_id>/email-students/', email_waiting_list_view, name="email_waiting_list"),
    path('waiting-list/<int:event_id>/', event_waiting_list_view, name="event_waiting_list"),
    path('waiting-list/remove/', ajax_remove_from_waiting_list, name="ajax_remove_from_waiting_list"),

    # tracks
    path('site-config/tracks/', TrackListView.as_view(), name="tracks"),
    path('site-config/track/<int:track_id>/toggle-default/', toggle_track_default, name="toggle_track_default"),
    path('site-config/track/<slug>/edit/', TrackUpdateView.as_view(), name="edit_track"),
    path('site-config/track/add/', TrackCreateView.as_view(), name="add_track"),
    # event_types
    path('site-config/event-types/', EventTypeListView.as_view(), name="event_types"),
    path('site-config/event-type/add/', choose_track_for_event_type, name="choose_track_for_event_type"),
    path('site-config/event-type/<int:track_id>/add/', EventTypeCreateView.as_view(), name="add_event_type"),
    path('site-config/event-type/<int:pk>/update/', EventTypeUpdateView.as_view(), name="edit_event_type"),
    path('site-config/event-type/<int:event_type_id>/delete/', event_type_delete_view, name="delete_event_type"),
    # block configs
    path('site-config/credit-blocks/', block_config_list_view, name="block_configs"),
    path('site-config/ajax-toggle-credit-block-active/', ajax_toggle_block_config_active, name="ajax_toggle_block_config_active"),
    path('site-config/credit-block/<int:block_config_id>/delete/', block_config_delete_view, name="delete_block_config"),
    path('site-config/credit-block/create/', choose_block_config_type, name="choose_block_config_type"),
    path('site-config/credit-block/<block_config_type>/create/', BlockConfigCreateView.as_view(), name="add_block_config"),
    path('site-config/credit-block/<int:pk>/update/', BlockConfigUpdateView.as_view(), name="edit_block_config"),
    # subscription configs
    path('site-config/subscription-configs/', subscription_config_list_view, name="subscription_configs"),
    path('site-config/ajax-toggle-subscription-config-active/', ajax_toggle_subscription_config_active, name="ajax_toggle_subscription_config_active"),
    path('site-config/subscription-config/<int:subscription_config_id>/clone/', clone_subscription_config_view, name="clone_subscription_config"),
    path('site-config/subscription-config/<int:subscription_config_id>/delete/', subscription_config_delete_view, name="delete_subscription_config"),
    path('site-config/subscription-config/create/', choose_subscription_config_type, name="choose_subscription_config_type"),
    path('site-config/subscription-config/<subscription_config_type>/create/', SubscriptionConfigCreateView.as_view(), name="add_subscription_config"),
    path('site-config/<int:pk>/update/', SubscriptionConfigUpdateView.as_view(), name="edit_subscription_config"),
    path('site-config/subscription-config/<int:config_id>/subscriptions/', SubscriptionListView.as_view(),
         name="purchased_subscriptions"),
    path('site-config/subscription-config/<int:subscription_config_id>/email-students/', email_subscription_users_view, name="email_subscription_users"),

    # payments
    path("payments/connect/", connect_stripe_view, name="connect_stripe"),
    path("payments/authorize/", StripeAuthorizeView.as_view(), name="authorize_stripe"),
    path("payments/oauth/callback/", StripeAuthorizeCallbackView.as_view(), name="authorize_stripe_callback"),
    path("payment/transactions/", InvoiceListView.as_view(), name="invoices"),

    # policies
    path('policies/cookie-policies/', CookiePolicyListView.as_view(), name="cookie_policies"),
    path('policies/data-privacy-policies/', DataPrivacyPolicyListView.as_view(), name="data_privacy_policies"),
    path('policies/disclaimer-versions/', DisclaimerContentListView.as_view(), name="disclaimer_contents"),
    re_path('^policies/cookie-policy/(?P<version>\d+\.\d+)/$', CookiePolicyDetailView.as_view(), name="cookie_policy"),
    path('policies/cookie-policy/new/', CookiePolicyCreateView.as_view(), name='add_cookie_policy'),
    re_path('^policies/data-privacy-policy/(?P<version>\d+\.\d+)/$', DataPrivacyPolicyDetailView.as_view(), name="data_privacy_policy"),
    path('policies/data-privacy-policy/new/', DataPrivacyPolicyCreateView.as_view(), name='add_data_privacy_policy'),
    re_path('^policies/disclaimer-versions/(?P<version>\d+\.\d+)/$', DisclaimerContentDetailView.as_view(), name="disclaimer_content"),
    path(
        'policies/disclaimer-version/new/', DisclaimerContentCreateView.as_view(), name='add_disclaimer_content'
    ),
    re_path(
        r'^policies/disclaimer-version/edit/(?P<version>\d+\.\d+)/$', DisclaimerContentUpdateView.as_view(), name='edit_disclaimer_content'
    ),
    # users
    path('users/export/', export_users, name="export_users"),
    path('users/unused-blocks/', users_with_unused_blocks, name="unused_blocks"),
    path('users/', UserListView.as_view(), name="users"),
    path('user/<int:pk>/detail/', UserDetailView.as_view(), name="user_detail"),
    path('user/<int:user_id>/bookings/', UserBookingsListView.as_view(), name="user_bookings"),
    path('user/<int:user_id>/bookings/history/', UserBookingsHistoryListView.as_view(), name="past_user_bookings"),
    path('user/<int:user_id>/booking/add/', BookingAddView.as_view(), name="bookingadd"),
    path('user/<int:user_id>/course-booking/add/', course_booking_add_view, name="coursebookingadd"),
    path('user/booking/<int:pk>/edit/', BookingEditView.as_view(), name="bookingedit"),
    path('user/<int:user_id>/blocks/', UserBlocksListView.as_view(), name="user_blocks"),
    path('user/<int:user_id>/block/add/', BlockAddView.as_view(), name="blockadd"),
    path('user/block/<int:pk>/edit/', BlockEditView.as_view(), name="blockedit"),
    path('user/block/<int:block_id>/change-course/', course_block_change_view, name="courseblockchange"),
    path('user/block/<int:block_id>/delete/', ajax_block_delete, name="blockdelete"),
    path('user/<int:user_id>/subscriptions/', UserSubscriptionsListView.as_view(), name="user_subscriptions"),
    path('user/<int:user_id>/subscription/add/', SubscriptionAddView.as_view(), name="subscriptionadd"),
    path('user/subscription/<int:pk>/edit/', SubscriptionEditView.as_view(), name="subscriptionedit"),
    path('user/subscription/<int:subscription_id>/delete/', ajax_subscription_delete, name="subscriptiondelete"),

    # vouchers
    path('vouchers/', VoucherListView.as_view(), name="vouchers"),
    path('gift-vouchers/', GiftVoucherListView.as_view(), name="gift_vouchers"),
    path('vouchers/add/', VoucherCreateView.as_view(), name="add_voucher"),
    path('gift-vouchers/add/', VoucherCreateView.as_view(), {'gift_voucher': True}, name="add_gift_voucher"),
    path('vouchers/<int:pk>/edit/', VoucherUpdateView.as_view(), name="edit_voucher"),
    path('vouchers/<int:pk>/', VoucherDetailView.as_view(), name="voucher_uses"),

    # help
    path('help/', help, name="help"),

    # path('jsi18n/', JavaScriptCatalog.as_view(), name='jsi18n'),
    path('', RedirectView.as_view(url='/studioadmin/registers/', permanent=True)),
]
