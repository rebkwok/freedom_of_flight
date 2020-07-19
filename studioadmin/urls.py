from django.urls import path, re_path
from django.views.generic import RedirectView
from django.views.i18n import JavaScriptCatalog
from studioadmin.views import (
    EventAdminListView, ajax_toggle_event_visible, RegisterListView, register_view,
    ajax_add_register_booking, ajax_toggle_attended,
    ajax_remove_from_waiting_list, event_waiting_list_view, cancel_event_view,
    event_create_choice_view, EventCreateView, EventUpdateView, clone_event,
    CourseAdminListView, course_create_choice_view, CourseCreateView, CourseUpdateView,
    ajax_toggle_course_visible, cancel_course_view,
    TimetableSessionListView, ajax_timetable_session_delete, timetable_session_create_choice_view,
    TimetableSessionCreateView, TimetableSessionUpdateView, clone_timetable_session_view,
    upload_timetable_view
)

app_name = 'studioadmin'


urlpatterns = [
    path('events/', EventAdminListView.as_view(), name='events'),
    path('event/<slug>/cancel/', cancel_event_view, name='cancel_event'),
    path('ajax-toggle-event-visible/<int:event_id>/', ajax_toggle_event_visible, name="ajax_toggle_event_visible"),
    path('event/create/', event_create_choice_view, name="choose_event_type_to_create"),
    path('event/<slug:event_slug>/clone/', clone_event, name="clone_event"),
    path('event/<int:event_type_id>/create/', EventCreateView.as_view(), name="create_event"),
    path('event/<slug>/update/', EventUpdateView.as_view(), name="update_event"),

    path('timetable/', TimetableSessionListView.as_view(), name='timetable'),
    path('timetable/session/<int:timetable_session_id>/delete/', ajax_timetable_session_delete, name="ajax_timetable_session_delete"),
    path('timetable/session/create/', timetable_session_create_choice_view, name="choose_event_type_timetable_session_to_create"),
    path('timetable/session/<int:event_type_id>/create/', TimetableSessionCreateView.as_view(), name="create_timetable_session"),
    path('timetable/session/<int:pk>/update/', TimetableSessionUpdateView.as_view(), name="update_timetable_session"),
    path('timetable/session/<int:session_id>/clone/', clone_timetable_session_view, name="clone_timetable_session"),
    path('timetable/upload/', upload_timetable_view, name="upload_timetable"),

    path('courses/', CourseAdminListView.as_view(), name='courses'),
    path('course/<slug>/cancel/', cancel_course_view, name='cancel_course'),
    path('ajax-toggle-course-visible/<int:course_id>/', ajax_toggle_course_visible, name="ajax_toggle_course_visible"),
    path('course/create/', course_create_choice_view, name="choose_course_type_to_create"),
    path('course/<int:course_type_id>/create/', CourseCreateView.as_view(), name="create_course"),
    path('course/<slug>/update/', CourseUpdateView.as_view(), name="update_course"),

    path('registers/', RegisterListView.as_view(), name='registers'),
    path('registers/<int:event_id>', register_view, name='register'),
    path('registers/<int:event_id>/ajax-add-booking/', ajax_add_register_booking, name='bookingregisteradd'),
    path('register/<int:booking_id>/ajax-toggle-attended/', ajax_toggle_attended, name='ajax_toggle_attended'),

    path('waiting-list/<int:event_id>/', event_waiting_list_view, name="event_waiting_list"),
    path('waiting-list/remove/', ajax_remove_from_waiting_list, name="ajax_remove_from_waiting_list"),

    # path('jsi18n/', JavaScriptCatalog.as_view(), name='jsi18n'),
    path('', RedirectView.as_view(url='/studioadmin/registers/', permanent=True)),
]
