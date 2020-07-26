from django.utils import timezone


class TimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Maybe sometime later we'll let users set a timezone in their profile, for now it's always UK time
        tzname = "Europe/London"
        timezone.activate(tzname)
        return self.get_response(request)
