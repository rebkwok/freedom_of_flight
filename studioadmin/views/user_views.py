from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, HttpResponseRedirect, reverse
from django.template.response import TemplateResponse
from django.views.generic import ListView, DetailView
from django.contrib.postgres.search import SearchVector
from django import forms
from braces.views import LoginRequiredMixin

from booking.email_helpers import send_bcc_emails
from booking.models import Booking, Course, Event

from ..forms import EmailUsersForm, SearchForm
from .utils import staff_required, InstructorOrStaffUserMixin


@login_required
@staff_required
def email_event_users_view(request, event_slug):
    event = get_object_or_404(Event, slug=event_slug)
    form = EmailUsersForm(event=event)
    if request.method == "POST":
        form = EmailUsersForm(request.POST, event=event)
        if form.is_valid():
            process_form_and_send_email(request, form)
            return HttpResponseRedirect(reverse("studioadmin:events") + f"?track={event.event_type.track_id}")
    context = {"form": form, "event": event}
    return TemplateResponse(request, "studioadmin/email_event_users.html", context)


@login_required
@staff_required
def email_course_users_view(request, course_slug):
    course = get_object_or_404(Course, slug=course_slug)
    form = EmailUsersForm(course=course)
    if request.method == "POST":
        form = EmailUsersForm(request.POST, course=course)
        if form.is_valid():
            process_form_and_send_email(request, form)
            return HttpResponseRedirect(reverse("studioadmin:courses") + f"?track={course.course_type.event_type.track_id}")
    context = {"form": form, "course": course}
    return TemplateResponse(request, "studioadmin/email_course_users.html", context)


def process_form_and_send_email(request, form):
    user_ids = form.cleaned_data.get("students", [])
    users = User.objects.filter(id__in=user_ids)
    user_emails = set()
    for user in users:
        if hasattr(user, "childuserprofile"):
            # send waiting list email to manager user
            user_emails.add(user.childuserprofile.parent_user_profile.user.email)
        else:
            user_emails.add(user.email)
    context = {"host": 'http://{}'.format(request.META.get('HTTP_HOST')), "message": form.cleaned_data["message"]}
    send_bcc_emails(
        context, user_emails, form.cleaned_data["subject"], "studioadmin/email/email_users",
        reply_to=form.cleaned_data["reply_to_email"], cc=form.cleaned_data["cc"]
    )
    messages.success(request, "Email sent")


class UserListView(LoginRequiredMixin, InstructorOrStaffUserMixin, ListView):

    model = User
    context_object_name = "users"
    template_name = "studioadmin/users.html"
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.GET.get('search')
        action = self.request.GET.get('action')
        if self.request.GET.get('search') and action == "Search":
            queryset = queryset.annotate(
                search=SearchVector('first_name', 'last_name', 'username'),
            ).filter(search=search)
        return queryset

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        search = self.request.GET.get('search', '')
        action = self.request.GET.get('action')
        if action == "Search":
            initial = {"search": search}
        else:
            initial = {"search": ""}
        context["search_form"] = SearchForm(initial=initial)
        context["total_users"] = self.get_queryset().count()
        return context


class UserDetailView(InstructorOrStaffUserMixin, LoginRequiredMixin, DetailView):
    model = User
    template_name = "studioadmin/user_detail.html"
    context_object_name = "account_user"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.get_object()
        context["latest_disclaimer"] = user.online_disclaimer.exists() and user.online_disclaimer.latest("id")
        return context
