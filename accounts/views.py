from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.contrib import messages
from django.forms.widgets import TextInput
from django.shortcuts import render, HttpResponseRedirect, get_object_or_404
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import UpdateView, CreateView, FormView
from django.views.generic.edit import FormMixin
from django.contrib.auth.models import User
from django.utils.decorators import method_decorator
from django.urls import reverse
from django.template.loader import get_template

from allauth.account.views import EmailView, LoginView, SignupView

from braces.views import LoginRequiredMixin
from shortuuid import ShortUUID

from common.utils import full_name
from .forms import DisclaimerForm, DataPrivacyAgreementForm, NonRegisteredDisclaimerForm, \
    ProfileForm, DisclaimerContactUpdateForm, RegisterChildUserForm, ManagedProfileForm
from .models import CookiePolicy, DataPrivacyPolicy, SignedDataPrivacy, UserProfile, OnlineDisclaimer, \
    has_active_data_privacy_agreement, has_active_disclaimer, has_expired_disclaimer, ChildUserProfile, DisclaimerContent
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

    def dispatch(self, request, *args, **kwargs):
        self.account_user = request.user
        return super(ProfileUpdateView, self).dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["user"] = self.account_user
        return form_kwargs

    def get_object(self):
        return get_object_or_404(UserProfile, user=self.account_user)

    def form_valid(self, form):
        form.save()
        form_data = form.cleaned_data
        # update the user with first and last name that are on the User model
        self.account_user.first_name = form_data['first_name']
        self.account_user.last_name = form_data['last_name']
        self.account_user.save()
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('accounts:profile')


class ManagedProfileUpdateView(ProfileUpdateView):

    model = ChildUserProfile
    form_class = ManagedProfileForm

    def dispatch(self, request, *args, **kwargs):
        self.account_user = get_object_or_404(User, pk=kwargs.get("user_id"))
        if self.account_user not in request.user.managed_users:
            return HttpResponseRedirect(reverse("accounts:profile"))
        return super(ProfileUpdateView, self).dispatch(request, *args, **kwargs)

    def get_object(self):
        return get_object_or_404(ChildUserProfile, user=self.account_user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["managed_user"] = True
        return context

    def form_valid(self, form):
        # Delete user_id from session so it can be set to the child user if applicable
        if "user_id" in self.request.session:
            del self.request.session["user_id"]
        return super().form_valid(form)


class ChildUserCreateView(LoginRequiredMixin, CreateView):

    model = ChildUserProfile
    template_name = 'accounts/register_child_user.html'
    form_class = RegisterChildUserForm

    @method_decorator(sensitive_post_parameters())
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["parent_user_profile"] = self.request.user.userprofile
        return form_kwargs

    def form_valid(self, form):
        child_profile = form.save(commit=False)

        # generate a random username; this use won't log in
        username = ShortUUID().random(length=10)
        while User.objects.filter(username=username).exists():
            username = ShortUUID().random(length=10)
        child_user = User.objects.create(
            first_name=form.cleaned_data["first_name"],
            last_name=form.cleaned_data["last_name"],
            username=username
        )
        child_user.set_unusable_password()
        child_profile.user = child_user
        child_profile.parent_user_profile = self.request.user.userprofile
        child_profile.save()
        if not self.request.user.is_manager:
            self.request.user.userprofile.manager = True
            self.request.user.userprofile.save()
        ActivityLog.objects.create(
            log=f"Managed user account created for {child_user.first_name} {child_user.last_name} by {self.request.user.first_name} { self.request.user.last_name}"
        )

        # Delete user_id from session so it can be set to the child user if applicable
        if "user_id" in self.request.session:
            del self.request.session["user_id"]
        return HttpResponseRedirect(self.get_success_url(child_user.id))

    def get_success_url(self, child_user_id):
        return reverse('accounts:disclaimer_form', args=(child_user_id,))


class DisclaimerContactUpdateView(LoginRequiredMixin, UpdateView):

    model = OnlineDisclaimer
    template_name = 'accounts/update_emergency_contact.html'
    form_class = DisclaimerContactUpdateForm

    @method_decorator(sensitive_post_parameters())
    def dispatch(self, request, *args, **kwargs):
        self.disclaimer_user = get_object_or_404(User, pk=kwargs["user_id"])
        if not has_active_disclaimer(self.disclaimer_user):
            return HttpResponseRedirect(reverse("accounts:disclaimer_form", args=(self.disclaimer_user.id,)))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context["disclaimer_user"] = self.disclaimer_user
        return context

    def get_object(self, *args, **kwargs):
        return OnlineDisclaimer.objects.filter(user=self.disclaimer_user).latest("id")

    def form_valid(self, form):
        return super().form_valid(form)

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


class DynamicDisclaimerFormMixin(FormMixin):

    def get_form(self, *args, **kwargs):
        form = super().get_form(*args, **kwargs)

        # # Form should already have the correct disclaimer content added, use it to get the form
        json_data = form.disclaimer_content.form
        # Add fields in JSON to dynamic form rendering field.
        form.fields["health_questionnaire_responses"].add_fields(json_data)
        if has_expired_disclaimer(self.disclaimer_user):
            updating_disclaimer = OnlineDisclaimer.objects.filter(user=self.disclaimer_user).last()
        else:
            updating_disclaimer = None

        for field in form.fields["health_questionnaire_responses"].fields:
            if updating_disclaimer and field.label in updating_disclaimer.health_questionnaire_responses.keys():
                previous_response = updating_disclaimer.health_questionnaire_responses[field.label]
                # check that previous choices are still valid
                if hasattr(field.widget, "choices") and isinstance(previous_response, list):
                    if set(previous_response) - {choice[0] for choice in field.widget.choices} == set():
                        field.initial = previous_response
                else:
                    # if the question type changed and the response type is now invalid, the initial
                    # will either get ignored or validated by the form, so it should be safe to use the
                    # previous response and let the form handle any errors
                    field.initial = previous_response
            if isinstance(field.widget, TextInput) and not field.initial:
                # prevent Chrome's wonky autofill
                field.initial = "-"
        return form

    def form_pre_commit(self, form):
        pre_saved_disclaimer = form.save(commit=False)
        pre_saved_disclaimer.version = form.disclaimer_content.version
        return pre_saved_disclaimer


class DisclaimerCreateView(LoginRequiredMixin, DynamicDisclaimerFormMixin, CreateView):

    form_class = DisclaimerForm
    template_name = 'accounts/disclaimer_form.html'

    @method_decorator(sensitive_post_parameters())
    def dispatch(self, request, *args, **kwargs):
        if not DisclaimerContent.objects.exists():
            return render(request, "accounts/no_disclaimers.html")
        self.disclaimer_user = get_object_or_404(User, pk=kwargs["user_id"])
        if has_active_disclaimer(self.disclaimer_user):
            messages.info(self.request, f"{full_name(self.disclaimer_user)} has a completed disclaimer")
            return HttpResponseRedirect(reverse("accounts:profile"))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["disclaimer_user"] = self.disclaimer_user
        context['disclaimer'] = has_active_disclaimer(self.disclaimer_user)
        context['expired_disclaimer'] = has_expired_disclaimer(self.disclaimer_user)
        return context

    def get_form_kwargs(self, **kwargs):
        form_kwargs = super().get_form_kwargs(**kwargs)
        form_kwargs["disclaimer_user"] = self.disclaimer_user
        form_kwargs["request_user"] = self.request.user
        return form_kwargs

    def form_valid(self, form):
        disclaimer = self.form_pre_commit(form)
        disclaimer.user = self.disclaimer_user
        disclaimer.save()
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('accounts:profile')


class NonRegisteredDisclaimerCreateView(CreateView):

    form_class = NonRegisteredDisclaimerForm
    template_name = 'accounts/nonregistered_disclaimer_form.html'

    @method_decorator(sensitive_post_parameters())
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        # email user
        disclaimer = form.save(commit=False)
        disclaimer.version = form.disclaimer_content.version
        email = disclaimer.email
        host = 'https://{}'.format(self.request.META.get('HTTP_HOST'))
        ctx = {
            'host': host,
            'contact_email': settings.DEFAULT_STUDIO_EMAIL,
            "site_code": settings.SITE_CODE,
            "site_title": settings.SITE_TITLE,
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
                self.request.GET.get('next', reverse('booking:schedule'))
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
