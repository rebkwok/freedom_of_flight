
from django.conf import settings


def fof_email(request):
    return {'fof_email': settings.DEFAULT_STUDIO_EMAIL}


