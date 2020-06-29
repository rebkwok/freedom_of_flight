
from django.conf import settings

from .models import Track


def booking(request):
    return {
        'fof_email': settings.DEFAULT_STUDIO_EMAIL,
        'tracks': Track.objects.all()
    }

