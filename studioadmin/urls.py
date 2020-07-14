from django.urls import path, re_path
from django.views.generic import RedirectView
from django.views.i18n import JavaScriptCatalog
from studioadmin.views import (
    EventAdminListView, ajax_toggle_event_visible, RegisterListView, register_view
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

    # path('jsi18n/', JavaScriptCatalog.as_view(), name='jsi18n'),
    path('', RedirectView.as_view(url='/studioadmin/registers/', permanent=True)),
]
