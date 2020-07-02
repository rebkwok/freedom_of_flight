
from django.shortcuts import render


from accounts.models import has_expired_disclaimer

def disclaimer_required(request):

    return render(
        request,
        'booking/disclaimer_required.html',
        {'has_expired_disclaimer': has_expired_disclaimer(request.user)}
    )


def permission_denied(request):
    return render(request, 'booking/permission_denied.html')
