from django.urls import path
from accounts.views import cookie_policy, data_privacy_policy, profile, \
    ProfileUpdateView, DisclaimerCreateView, SignedDataPrivacyCreateView


app_name = "accounts"


urlpatterns = [
    path(
        'profile/update/', ProfileUpdateView.as_view(),
        name='update_profile'
    ),
    path(
        'waiver/', DisclaimerCreateView.as_view(),
        name='disclaimer_form'
    ),
    path(
        'data-privacy-review/', SignedDataPrivacyCreateView.as_view(),
         name='data_privacy_review'
    ),
    path(
        'data-privacy-policy/', data_privacy_policy, name='data_privacy_policy'
    ),
    path(
        'cookie-policy/', cookie_policy, name='cookie_policy'
    ),
    path('profile/', profile, name='profile'),
]
