from .ajax_views import (
    ajax_course_booking, ajax_toggle_booking, ajax_toggle_waiting_list,
    ajax_block_purchase, ajax_subscription_purchase, ajax_cart_item_delete
)

from .block_views import BlockListView, BlockDetailView
from .course_views import CourseListView
from .payment_option_views import event_purchase_view, course_purchase_view, purchase_view
from .subscription_views import SubscriptionListView, SubscriptionDetailView
from .booking_views import BookingListView, BookingHistoryListView
from .event_views import CourseEventsListView, EventDetailView, EventListView, home
from .misc_views import disclaimer_required, permission_denied, terms_and_conditions, covid19_policy
from .shopping_basket_views import shopping_basket, ajax_checkout