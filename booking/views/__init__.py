from .ajax_views import (
    ajax_block_delete, ajax_course_booking, ajax_toggle_booking, ajax_toggle_waiting_list,
    ajax_block_purchase
)

from .block_views import (
    dropin_block_purchase_view, course_block_purchase_view, block_purchase_view,
    BlockListView, BlockDetailView
)
from .booking_views import BookingListView, BookingHistoryListView
from .event_views import CourseEventsListView, EventDetailView, EventListView, home
from .misc_views import disclaimer_required, permission_denied
from .shopping_basket_views import shopping_basket, ajax_checkout