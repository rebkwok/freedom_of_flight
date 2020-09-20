from urllib.parse import urlencode

import requests

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.sites.models import Site
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import View

from braces.views import LoginRequiredMixin

from activitylog.models import ActivityLog
from booking.models import Track, EventType, BlockConfig, SubscriptionConfig, Subscription
from common.utils import full_name
from payments.models import Seller
from .utils import StaffUserMixin, staff_required


@login_required
@staff_required
def connect_stripe_view(request):
    return render(request, "studioadmin/connect_stripe.html")


class StripeAuthorizeView(LoginRequiredMixin, StaffUserMixin, View):

    def get(self, request):
        url = 'https://connect.stripe.com/oauth/authorize'
        params = {
            'response_type': 'code',
            'scope': 'read_write',
            'client_id': settings.STRIPE_CONNECT_CLIENT_ID,
            'redirect_uri': request.build_absolute_uri(reverse("studioadmin:authorize_stripe_callback")),
        }
        url = f'{url}?{urlencode(params)}'
        return redirect(url)


class StripeAuthorizeCallbackView(View):

    def get(self, request):
        code = request.GET.get('code')
        if code:
            data = {
                'client_secret': settings.STRIPE_SECRET_KEY,
                'grant_type': 'authorization_code',
                'client_id': settings.STRIPE_CONNECT_CLIENT_ID,
                'code': code
            }
            url = 'https://connect.stripe.com/oauth/token'
            resp = requests.post(url, params=data)
            # add stripe info to the seller
            resp_data = resp.json()
            stripe_user_id = resp_data['stripe_user_id']
            stripe_access_token = resp_data['access_token']
            stripe_refresh_token = resp_data['refresh_token']
            seller = Seller.objects.filter(user_id=self.request.user.id).first()
            seller.site = Site.objects.get_current(request)
            seller.stripe_access_token = stripe_access_token
            seller.stripe_refresh_token = stripe_refresh_token
            seller.stripe_user_id = stripe_user_id
            seller.save()

        return redirect(reverse('studioadmin:connect_stripe'))
