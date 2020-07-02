from django.shortcuts import render


from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.mail import send_mail
from django.shortcuts import render, HttpResponseRedirect, get_object_or_404
from django.views.generic import UpdateView, CreateView, FormView
from django.contrib.auth.models import User
from django.urls import reverse
from django.template.loader import get_template

from allauth.account.views import EmailView, LoginView, SignupView

from braces.views import LoginRequiredMixin

from .forms import DisclaimerForm, DataPrivacyAgreementForm, NonRegisteredDisclaimerForm, \
    ProfileForm, DisclaimerContactUpdateForm
from .models import CookiePolicy, DataPrivacyPolicy, SignedDataPrivacy, UserProfile, OnlineDisclaimer, \
    has_active_data_privacy_agreement, has_active_disclaimer, has_expired_disclaimer
from activitylog.models import ActivityLog


@login_required
def profile(request):
    has_disclaimer = has_active_disclaimer(request.user)
    has_exp_disclaimer = has_expired_disclaimer(request.user)
    latest_disclaimer = request.user.online_disclaimer.exists() and request.user.online_disclaimer.latest("id")

    return render(
        request, 'accounts/profile.html',
        {
            'has_disclaimer': has_disclaimer,
            'has_expired_disclaimer': has_exp_disclaimer,
            "latest_disclaimer": latest_disclaimer
        }
    )


class ProfileUpdateView(LoginRequiredMixin, UpdateView):

    model = UserProfile
    template_name = 'accounts/update_profile.html'
    form_class = ProfileForm

    def get_form_kwargs(self):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["user"] = self.request.user
        return form_kwargs

    def get_object(self):
        return get_object_or_404(
            UserProfile, user=self.request.user
        )

    def form_valid(self, form):
        form.save()
        form_data = form.cleaned_data.copy()
        # update the user with first and last name that are on the User model
        self.request.user.first_name = form_data['first_name']
        self.request.user.last_name = form_data['last_name']
        self.request.user.save()
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('accounts:profile')


class DisclaimerContactUpdateView(LoginRequiredMixin, UpdateView):

    model = OnlineDisclaimer
    template_name = 'accounts/update_emergency_contact.html'
    form_class = DisclaimerContactUpdateForm

    def dispatch(self, request, *args, **kwargs):
        self.user = get_object_or_404(User, pk=kwargs["user_id"])
        if not has_active_disclaimer(self.user):
            return HttpResponseRedirect(reverse("accounts:disclaimer_form"))
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, *args, **kwargs):
        return OnlineDisclaimer.objects.filter(user=self.user).latest("id")

    def get_success_url(self):
        return reverse('accounts:profile')


class CustomLoginView(LoginView):

    def get_success_url(self):
        super().get_success_url()
        ret = self.request.POST.get('next') or self.request.GET.get('next')
        if not ret or ret in [
            '/accounts/password/change/', '/accounts/password/set/'
        ]:
            ret = reverse('accounts:profile')

        return ret


class DisclaimerCreateView(LoginRequiredMixin, CreateView):

    form_class = DisclaimerForm
    template_name = 'accounts/disclaimer_form.html'

    def dispatch(self, request, *args, **kwargs):
        if request.method == 'POST' and not request.user.is_anonymous:
            if has_active_disclaimer(request.user):
                return HttpResponseRedirect(reverse('accounts:disclaimer_form'))
        return super().dispatch(
            request, *args, **kwargs
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['disclaimer'] = has_active_disclaimer(self.request.user)
        context['expired_disclaimer'] = has_expired_disclaimer(
            self.request.user
        )

        return context

    def get_form_kwargs(self, **kwargs):
        form_kwargs = super().get_form_kwargs(**kwargs)
        form_kwargs["user"] = self.request.user
        return form_kwargs

    def form_valid(self, form):
        disclaimer = form.save(commit=False)
        disclaimer.version = form.disclaimer_content.version
        password = form.cleaned_data['password']

        if self.request.user.check_password(password):
            disclaimer.user = self.request.user
            disclaimer.save()
        else:
            form = DisclaimerForm(form.data, user=self.request.user)
            return render(self.request, self.template_name, {'form':form, 'password_error': 'Invalid password entered'})

        return super().form_valid(form)

    def get_success_url(self):
        return reverse('accounts:profile')


class NonRegisteredDisclaimerCreateView(CreateView):

    form_class = NonRegisteredDisclaimerForm
    template_name = 'accounts/nonregistered_disclaimer_form.html'

    def form_valid(self, form):
        # email user
        disclaimer = form.save(commit=False)
        disclaimer.version = form.disclaimer_content.version
        email = disclaimer.email
        host = 'https://{}'.format(self.request.META.get('HTTP_HOST'))
        ctx = {
            'host': host,
            'contact_email': settings.DEFAULT_STUDIO_EMAIL
        }
        send_mail('{}Disclaimer recevied'.format(settings.ACCOUNT_EMAIL_SUBJECT_PREFIX),
            get_template('accounts/email/nonregistered_disclaimer_received.txt').render(ctx),
            settings.DEFAULT_FROM_EMAIL,
            [email],
            html_message=get_template(
                'accounts/email/nonregistered_disclaimer_received.html').render(ctx),
            fail_silently=False)

        return super().form_valid(form)

    def get_success_url(self):
        return reverse('accounts:nonregistered_disclaimer_submitted')


def nonregistered_disclaimer_submitted(request):
    return render(request, 'accounts/nonregistered_disclaimer_created.html')


class SignedDataPrivacyCreateView(LoginRequiredMixin, FormView):
    template_name = 'accounts/data_privacy_review.html'
    form_class = DataPrivacyAgreementForm

    def dispatch(self, *args, **kwargs):
        if self.request.user.is_authenticated and \
                has_active_data_privacy_agreement(self.request.user):
            return HttpResponseRedirect(
                self.request.GET.get('next', reverse('booking:lessons'))
            )
        return super().dispatch(*args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['next_url'] = self.request.GET.get('next')
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        update_needed = (
            SignedDataPrivacy.objects.filter(
                user=self.request.user,
                version__lt=DataPrivacyPolicy.current_version()
            ).exists() and not has_active_data_privacy_agreement(
                self.request.user)
        )

        context.update({
            'data_protection_policy': DataPrivacyPolicy.current(),
            'update_needed': update_needed
        })
        return context

    def form_valid(self, form):
        user = self.request.user
        SignedDataPrivacy.objects.create(
            user=user, version=form.data_privacy_policy.version
        )
        next_url = form.next_url or reverse('booking:schedule')
        return self.get_success_url(next_url)

    def get_success_url(self, next):
        return HttpResponseRedirect(next)


def data_privacy_policy(request):
    return render(
        request, 'accounts/data_privacy_policy.html',
        {'data_privacy_policy': DataPrivacyPolicy.current(),
         'cookie_policy': CookiePolicy.current()}
    )


def cookie_policy(request):
    return render(
        request, 'accounts/cookie_policy.html',
        {'cookie_policy': CookiePolicy.current()}
    )