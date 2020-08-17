from .cloning_views import clone_event, clone_timetable_session_view
from .course_views import (
    CourseAdminListView, course_create_choice_view, CourseCreateView, CourseUpdateView,
    ajax_toggle_course_visible, cancel_course_view, PastCourseAdminListView,
)
from .event_views import (
    EventAdminListView, ajax_toggle_event_visible, cancel_event_view, EventCreateView,
    event_create_choice_view, EventUpdateView, PastEventAdminListView
)
from .policy_views import (
    CookiePolicyListView, DataPrivacyPolicyListView, DisclaimerContentListView,
    CookiePolicyDetailView, DataPrivacyPolicyDetailView, DisclaimerContentDetailView,
    DisclaimerContentCreateView, DisclaimerContentUpdateView, CookiePolicyCreateView, DataPrivacyPolicyCreateView
)
from .site_config_views import (
    TrackCreateView, TrackListView, TrackUpdateView, EventTypeListView, toggle_track_default, help,
    choose_track_for_event_type, EventTypeCreateView, EventTypeUpdateView, event_type_delete_view,
    block_config_list_view, ajax_toggle_block_config_active, block_config_delete_view, choose_block_config_type,
    BlockConfigCreateView, BlockConfigUpdateView,
    subscription_config_list_view, ajax_toggle_subscription_config_active, subscription_config_delete_view,
    choose_subscription_config_type, SubscriptionConfigCreateView, SubscriptionConfigUpdateView, clone_subscription_config_view,
    SubscriptionListView,
)
from .register_views import RegisterListView, register_view, ajax_add_register_booking, ajax_toggle_attended
from .timetable_views import (
    TimetableSessionListView, ajax_timetable_session_delete, TimetableSessionCreateView, TimetableSessionUpdateView,
    timetable_session_create_choice_view, upload_timetable_view
)
from .user_views import (
    email_event_users_view, email_course_users_view, UserListView, UserDetailView, UserBookingsListView,
    UserBookingsHistoryListView, BookingAddView, BookingEditView,
    UserBlocksListView, BlockAddView, BlockEditView, ajax_block_delete,
    email_subscription_users_view,
    UserSubscriptionsListView, SubscriptionAddView, SubscriptionEditView, ajax_subscription_delete,
)

from .waiting_list import ajax_remove_from_waiting_list, event_waiting_list_view
