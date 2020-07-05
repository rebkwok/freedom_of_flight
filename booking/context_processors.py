from datetime import timedelta
from django.conf import settings
from django.utils import timezone

from .models import Track, Event


def booking(request):
    # Only show tracks that have upcoming events (that are visible and not cancelled)
    tracks_with_events = Event.objects.filter(
        start__gt=timezone.now() - timedelta(minutes=15), show_on_site=True, cancelled=False
    ).order_by().distinct("event_type__track").values_list("event_type__track_id")
    tracks = Track.objects.filter(id__in=tracks_with_events)
    if not tracks:
        tracks = Track.objects.filter(default=True)

    student_users = [child_profile.user for child_profile in request.user.profile.managed_profiles.all()]
    if request.user.profile.student:
        student_users.insert(0, request.user)

    return {
        'studio_email': settings.DEFAULT_STUDIO_EMAIL,
        'tracks': tracks,
        'student_users': student_users,
        'cart_item_count': request.user.is_authenticated and request.user.blocks.filter(paid=False).count()
    }

