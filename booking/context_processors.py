from datetime import timedelta
from django.conf import settings
from django.utils import timezone

from .models import Block, Track, Event
from .utils import get_view_as_user
from .views.views_utils import total_unpaid_item_count


def booking(request):
    # Only show tracks that have upcoming events (that are visible and not cancelled)
    tracks_with_events = Event.objects.filter(
        start__gt=timezone.now() - timedelta(minutes=15), show_on_site=True, cancelled=False
    ).order_by().distinct("event_type__track").values_list("event_type__track_id")
    tracks = Track.objects.filter(id__in=tracks_with_events)
    if not tracks:
        tracks = Track.objects.filter(default=True)

    if request.user.is_authenticated:
        available_users = request.user.managed_student_users
        cart_item_count = total_unpaid_item_count(request.user)
        view_as_user = get_view_as_user(request)
    else:
        available_users = []
        cart_item_count = None
        view_as_user = request.user

    return {
        'use_cdn': not settings.DEBUG or settings.USE_CDN,
        'studio_email': settings.DEFAULT_STUDIO_EMAIL,
        'tracks': tracks,
        'available_users': available_users,
        'cart_item_count': cart_item_count,
        'view_as_user': view_as_user,
        'checkout_method': settings.CHECKOUT_METHOD,
    }

