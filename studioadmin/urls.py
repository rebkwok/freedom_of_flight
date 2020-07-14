from django.urls import path, re_path
from django.views.generic import RedirectView
from django.views.i18n import JavaScriptCatalog
from studioadmin.views import (
    EventAdminListView, ajax_toggle_event_visible, RegisterListView, register_view,
    ajax_add_register_booking, ajax_toggle_attended
)

app_name = 'studioadmin'


urlpatterns = [
    # path('events/<slug:slug>/edit', EventAdminUpdateView.as_view(),
    #     {'ev_type': 'event'}, name='edit_event'),
    path('events/', EventAdminListView.as_view(), name='events'),
    path('ajax-toggle-event-visible/<int:event_id>/', ajax_toggle_event_visible, name="ajax_toggle_event_visible"),
    # path('events/<slug:slug>/cancel', cancel_event_view, name='cancel_event'),

    path('registers/', RegisterListView.as_view(), name='registers'),
    path('registers/<int:event_id>', register_view, name='register'),
    path('registers/<int:event_id>/ajax-add-booking/', ajax_add_register_booking, name='bookingregisteradd'),
    path('register/<int:booking_id>/ajax-toggle-attended/', ajax_toggle_attended, name='ajax_toggle_attended'),

    # path('jsi18n/', JavaScriptCatalog.as_view(), name='jsi18n'),
    path('', RedirectView.as_view(url='/studioadmin/registers/', permanent=True)),
]
