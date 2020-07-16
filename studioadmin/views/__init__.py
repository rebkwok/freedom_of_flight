from.course_views import (
    CourseAdminListView, course_create_choice_view, CourseCreateView, CourseUpdateView,
    ajax_toggle_course_visible, cancel_course_view
)
from .event_views import (
    EventAdminListView, ajax_toggle_event_visible, cancel_event_view, EventCreateView,
    event_create_choice_view, EventUpdateView, clone_event
)
from .register_views import RegisterListView, register_view, ajax_add_register_booking, ajax_toggle_attended
from .waiting_list import ajax_remove_from_waiting_list, event_waiting_list_view
