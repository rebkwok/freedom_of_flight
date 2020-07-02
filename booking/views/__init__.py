from .ajax_views import ajax_course_booking, ajax_toggle_booking, ajax_toggle_waiting_list, placeholder
from .block_views import (
    dropin_block_purchase_view, course_block_purchase_view, block_purchase_view,
    ajax_dropin_block_purchase, ajax_course_block_purchase
)
from .booking_views import BookingDeleteView, BookingCreateView
from .event_views import CourseEventsListView, EventDetailView, EventListView, home
from .misc_views import disclaimer_required, permission_denied
from .shopping_basket_views import shopping_basket