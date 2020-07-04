
from django.conf import settings

from .models import Track, Block


def booking(request):
    return {
        'fof_email': settings.DEFAULT_STUDIO_EMAIL,
        'tracks': Track.objects.all(),
        # TODO this will need to include user's sub-user blocks too
        'cart_item_count': request.user.blocks.filter(paid=False).count()
    }

