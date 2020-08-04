from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404, HttpResponseRedirect, render
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.urls import reverse

from braces.views import LoginRequiredMixin

from accounts.models import CookiePolicy, DataPrivacyPolicy, DisclaimerContent
from activitylog.models import ActivityLog
from common.utils import full_name


from ..forms import StudioadminDisclaimerContentForm, CookiePolicyAdminForm, DataPrivacyPolicyAdminForm
from .utils import StaffUserMixin, is_instructor_or_staff


class CookiePolicyListView(LoginRequiredMixin, StaffUserMixin, ListView):
    template_name = "studioadmin/cookie_policies.html"
    model = CookiePolicy
    context_object_name = "policies"


class CookiePolicyDetailView(LoginRequiredMixin, StaffUserMixin, DetailView):
    template_name = "studioadmin/cookie_policy.html"
    model = CookiePolicy
    context_object_name = "policy"

    def get_object(self):
        return get_object_or_404(CookiePolicy, version=self.kwargs['version'])


class DataPrivacyPolicyListView(LoginRequiredMixin, StaffUserMixin, ListView):
    template_name = "studioadmin/data_privacy_policies.html"
    model = DataPrivacyPolicy
    context_object_name = "policies"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_version"] = DataPrivacyPolicy.current_version()
        return context


class DataPrivacyPolicyDetailView(LoginRequiredMixin, StaffUserMixin, DetailView):
    template_name = "studioadmin/data_privacy_policy.html"
    model = DataPrivacyPolicy
    context_object_name = "policy"

    def get_object(self):
        return get_object_or_404(DataPrivacyPolicy, version=self.kwargs['version'])


class DisclaimerContentListView(LoginRequiredMixin, StaffUserMixin, ListView):
    template_name = "studioadmin/disclaimer_contents.html"
    model = DisclaimerContent
    context_object_name = "disclaimer_contents"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_version"] = DisclaimerContent.current_version()
        return context


class DisclaimerContentDetailView(LoginRequiredMixin, StaffUserMixin, DetailView):
    template_name = "studioadmin/disclaimer_content.html"
    model = DisclaimerContent
    context_object_name = "disclaimer_content"

    def get_object(self):
        return get_object_or_404(DisclaimerContent, version=self.kwargs['version'])


class DisclaimerContentCreateView(LoginRequiredMixin, StaffUserMixin, CreateView):

    model = DisclaimerContent
    template_name = 'studioadmin/disclaimer_content_create_update.html'
    form_class = StudioadminDisclaimerContentForm

    def dispatch(self, request, *args, **kwargs):
        try:
            draft = DisclaimerContent.objects.filter(is_draft=True).latest('id')
            return HttpResponseRedirect(reverse('studioadmin:edit_disclaimer_content', args=(draft.version,)))
        except DisclaimerContent.DoesNotExist:
            return super(DisclaimerContentCreateView, self).dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["same_as_published"] = True
        return form_kwargs

    def form_valid(self, form):
        new_content = form.save()
        if "save_draft" in self.request.POST:
            new_content.is_draft = True
        elif "publish" in self.request.POST:
            new_content.is_draft = False
        else:
            raise ValidationError("Action (save draft/publish) cannot be determined")
        new_content.save()
        ActivityLog.objects.create(
            log=f"New {new_content.status} disclaimer content "
                f"version {new_content.version} created by admin user {full_name(self.request.user)}"
        )
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('studioadmin:disclaimer_contents')


class DisclaimerContentUpdateView(LoginRequiredMixin, StaffUserMixin, UpdateView):

    model = DisclaimerContent
    context_object_name = 'disclaimer_content'
    template_name = 'studioadmin/disclaimer_content_create_update.html'
    form_class = StudioadminDisclaimerContentForm

    def get_form_kwargs(self):
        form_kwargs = super().get_form_kwargs()
        obj = self.get_object()
        current = DisclaimerContent.current()
        form_kwargs["same_as_published"] = (
                obj.disclaimer_terms == current.disclaimer_terms and
                obj.form == current.form
        )
        return form_kwargs

    def get_object(self):
        return get_object_or_404(DisclaimerContent, version=self.kwargs['version'])

    def form_valid(self, form):
        updated_content = form.save(commit=False)
        if "save_draft" in self.request.POST:
            updated_content.is_draft = True
        elif "publish" in self.request.POST:
            updated_content.is_draft = False
        elif "reset" in self.request.POST:
            current = DisclaimerContent.current()
            updated_content.disclaimer_terms = current.disclaimer_terms
            updated_content.form = current.form
        else:
            raise ValidationError("Action (save draft/publish/reset) cannot be determined")
        updated_content.save()
        ActivityLog.objects.create(
            log=f"Disclaimer content ({updated_content.status}) "
                f"version {updated_content.version} updated by admin user {full_name(self.request.user)}"
        )
        if "reset" in self.request.POST:
            messages.success(self.request, f"Content reset to Version {DisclaimerContent.current().version}")
            return HttpResponseRedirect(reverse('studioadmin:edit_disclaimer_content', args=(updated_content.version,)))
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form):
        # The formbuilder doesn't display properly if we simply return the POST data in the form. Mostly we'll
        # get here if we made an error with the version or tried to save with no changes, so just instantiate a
        # new form and add the errors manually to the context
        current = DisclaimerContent.current()
        same_as_published = (
                form.instance.disclaimer_terms == current.disclaimer_terms and
                form.instance.form == current.form
        )
        context = self.get_context_data()
        context["form_errors"] = form.errors
        context["form"] = StudioadminDisclaimerContentForm(same_as_published=same_as_published)
        return TemplateResponse(self.request, self.template_name, context)

    def get_success_url(self):
        return reverse('studioadmin:disclaimer_contents')


class CookiePolicyCreateView(LoginRequiredMixin, StaffUserMixin, CreateView):

    model = CookiePolicy
    template_name = 'studioadmin/policy_create.html'
    form_class = CookiePolicyAdminForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["policy_type"] = "Cookie Policy"
        return context

    def get_success_url(self):
        return reverse("studioadmin:cookie_policies")


class DataPrivacyPolicyCreateView(LoginRequiredMixin, StaffUserMixin, CreateView):

    model = DataPrivacyPolicy
    template_name = 'studioadmin/policy_create.html'
    form_class = DataPrivacyPolicyAdminForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["policy_type"] = "Data Privacy Policy"
        return context

    def get_success_url(self):
        return reverse("studioadmin:data_privacy_policies")