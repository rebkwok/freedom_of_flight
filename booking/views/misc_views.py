from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, render


from accounts.models import has_expired_disclaimer

def disclaimer_required(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    return render(
        request,
        'booking/disclaimer_required.html',
        {'has_expired_disclaimer': has_expired_disclaimer(user), "disclaimer_user": user}
    )


def permission_denied(request):
    return render(request, 'booking/permission_denied.html')


def terms_and_conditions(request):
    return render(request, "booking/terms_and_conditions.html")


def covid19_policy(request):
    return render(request, "booking/covid19_policy.html")