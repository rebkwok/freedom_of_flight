from datetime import datetime

from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, HttpResponseRedirect, render, reverse, HttpResponse
from django.http import HttpResponseBadRequest, JsonResponse
from django.template.response import TemplateResponse
from django.template.loader import render_to_string
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.contrib.postgres.search import SearchVector
from django.utils import timezone

from braces.views import LoginRequiredMixin

from activitylog.models import ActivityLog
from booking.email_helpers import send_bcc_emails, send_user_and_studio_emails, send_waiting_list_email
from booking.models import Booking, Block, Course, Event, WaitingListUser, SubscriptionConfig, Subscription
from common.utils import full_name

from ..forms import EmailUsersForm, SearchForm, AddEditBookingForm, AddEditBlockForm, AddEditSubscriptionForm
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
            return HttpResponseRedirect(reverse("studioadmin:courses") + f"?track={course.event_type.track_id}")
    context = {"form": form, "course": course}
    return TemplateResponse(request, "studioadmin/email_course_users.html", context)


@login_required
@staff_required
def email_subscription_users_view(request, subscription_config_id):
    subscription_config = get_object_or_404(SubscriptionConfig, id=subscription_config_id)
    form = EmailUsersForm(subscription_config=subscription_config)
    if request.method == "POST":
        form = EmailUsersForm(request.POST, subscription_config=subscription_config)
        if form.is_valid():
            process_form_and_send_email(request, form)
            return HttpResponseRedirect(reverse("studioadmin:subscription_configs"))
    context = {"form": form, "subscription_config": subscription_config}
    return TemplateResponse(request, "studioadmin/email_subscription_users.html", context)


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


class UserDetailView(LoginRequiredMixin, InstructorOrStaffUserMixin, DetailView):
    model = User
    template_name = "studioadmin/user_detail.html"
    context_object_name = "account_user"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.get_object()
        context["latest_disclaimer"] = user.online_disclaimer.latest("id") if user.online_disclaimer.exists() else None
        return context


class UserBookingsListView(LoginRequiredMixin, InstructorOrStaffUserMixin, ListView):
    model = Booking
    context_object_name = "bookings"
    template_name = "studioadmin/user_bookings_list.html"
    paginate_by = 20

    def dispatch(self, request, *args, **kwargs):
        self.user = get_object_or_404(User, pk=kwargs["user_id"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["account_user"] = self.user
        return context

    def get_queryset(self):
        start_of_today = datetime.combine(datetime.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
        return self.user.bookings.filter(event__start__gte=start_of_today).order_by("event__start")


class UserBookingsHistoryListView(UserBookingsListView):

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["past"] = True
        return context

    def get_queryset(self):
        return self.user.bookings.filter(event__start__lte=timezone.now()).order_by("-event__start")


class BookingEditView(LoginRequiredMixin, InstructorOrStaffUserMixin, UpdateView):
    form_class = AddEditBookingForm
    model = Booking
    template_name = 'studioadmin/includes/user-booking-modal.html'

    def get_form_kwargs(self, *args, **kwargs):
        kwargs = super().get_form_kwargs(*args, **kwargs)
        kwargs['user'] = self.object.user
        return kwargs

    def form_valid(self, form):
        process_user_booking_updates(form, self.request, self.object.user)
        return HttpResponse(
            render_to_string(
                'studioadmin/includes/modal-success.html'
            )
        )


class BookingAddView(LoginRequiredMixin, InstructorOrStaffUserMixin, CreateView):
    model = Booking
    template_name = 'studioadmin/includes/user-booking-add-modal.html'
    form_class = AddEditBookingForm

    def dispatch(self, request, *args, **kwargs):
        self.booking_user = User.objects.get(id=kwargs['user_id'])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["booking_user"] = self.booking_user
        return context

    def get_form_kwargs(self, *args, **kwargs):
        kwargs = super().get_form_kwargs(*args, **kwargs)
        kwargs['user'] = self.booking_user
        return kwargs

    def form_valid(self, form):
        process_user_booking_updates(form, self.request, self.booking_user)
        return HttpResponse(
            render_to_string(
                'studioadmin/includes/modal-success.html'
            )
        )


def process_user_booking_updates(form, request, user):
    if form.has_changed():
        if form.changed_data == ['send_confirmation']:
            messages.info(
                request,  "'Send confirmation' checked but no changes were made; email has not been sent to user."
            )
        else:
            booking = form.save(commit=False)
            event_was_full = booking.event.spaces_left == 0
            action = 'updated' if form.instance.id else 'created'
            block_removed = False

            if 'status' in form.changed_data and action == 'updated':
                if booking.status == 'CANCELLED':
                    if booking.event.course:
                        # bookings for course events don't get cancelled fully, just set to no_show
                        booking.status = "OPEN"
                        booking.no_show = True
                        # reset the block if it was removed
                        booking.block = user.bookings.get(id=booking.id).block
                        messages.info(
                            request,
                            "Cancelled course event bookings are not refunded to user; booking has been set to no-show instead."
                        )
                    elif booking.block:  # pragma: no cover
                        # Form validation should prevent this, but make sure no block is assigned anyway
                        booking.block = None
                    action = 'cancelled'
                elif booking.status == 'OPEN':
                    action = 'reopened'

            elif 'no_show' in form.changed_data and action == 'updated' and booking.status == 'OPEN':
                action = 'cancelled' if booking.no_show else 'reopened'
                messages.success(request, f"Booking {action} as 'no-show'")

            if action == "updated" and "block" in form.changed_data and not booking.block and booking.event.course:
                # Don't remove blocks from course events
                booking.block = user.bookings.get(id=booking.id).block
                messages.info(
                    request,
                    f"Block cannot be updated; applies to all {booking.event.event_type.pluralized_label} in the course."
                )

            if not booking.block and booking.status == "OPEN":
                messages.error(request, "NOTE: This booking does not have a credit block assigned.")
            booking.save()

            if 'send_confirmation' in form.changed_data:
                host = f"http://{request.META.get('HTTP_HOST')}"
                ctx = {
                    'host': host,
                    'event': booking.event,
                    'user': user,
                    'action': action,
                }
                email_user = booking.user.manager_user if booking.user.manager_user else booking.user
                send_user_and_studio_emails(
                    ctx, email_user, send_to_studio=False,
                    subjects={"user": f"Your booking for {booking.event} has been {action}"},
                    template_dir="studioadmin/email",
                    template_short_name="booking_change_confirmation")
                send_confirmation_msg = "and confirmation email sent to user"
            else:
                send_confirmation_msg = ""

            messages.success(
                request, 'Booking for {} has been {} {}'.format(booking.event,  action,  send_confirmation_msg)
            )

            ActivityLog.objects.create(
                log='Booking id {} (user {}) for "{}" {} by admin user {}'.format(
                    booking.id,  full_name(booking.user),  booking.event, action,  full_name(request.user)
                )
            )

            if action == 'cancelled':
                if event_was_full:
                    waiting_list_users = WaitingListUser.objects.filter(event=booking.event)
                    if waiting_list_users:
                        host = f"http://{request.META.get('HTTP_HOST')}"
                        send_waiting_list_email(booking.event, waiting_list_users, host)

            if action == 'created' or action == 'reopened':
                try:
                    waiting_list_user = WaitingListUser.objects.get(user=booking.user,  event=booking.event)
                    waiting_list_user.delete()
                    ActivityLog.objects.create(
                        log=f'User {full_name(booking.user)} has been removed from the waiting list for {booking.event}'
                    )
                except WaitingListUser.DoesNotExist:
                    pass

    else:
        messages.info(request, 'No changes made')


class UserBlocksListView(LoginRequiredMixin, InstructorOrStaffUserMixin, ListView):
    model = Block
    context_object_name = "blocks"
    template_name = "studioadmin/user_blocks_list.html"
    paginate_by = 20

    def dispatch(self, request, *args, **kwargs):
        self.user = get_object_or_404(User, pk=kwargs["user_id"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["account_user"] = self.user
        return context

    def get_queryset(self):
        return self.user.blocks.all().order_by("-expiry_date", "-start_date", "-purchase_date")


class BlockMixin:
    form_class = AddEditBlockForm
    model = Block

    def form_valid(self, form):
        block = form.save(commit=False)
        if block.bookings.count() > block.block_config.size:
            form.add_error("block_config", "Too many bookings already made against block; cannot change to this block type")

        if form.is_valid():
            block.save()
            ActivityLog.objects.create(
                log=f"Block id {block.id} for user {full_name(block.user)} {self.action} by admin user {full_name(self.request.user)}"
            )
            messages.success(self.request, f"Block {self.action}")

            return HttpResponse(
                render_to_string(
                    'studioadmin/includes/modal-success.html'
                )
            )
        else:
            context = self.get_context_data()
            context["form"] = form
            return render(self.request, self.template_name, context)


class BlockEditView(LoginRequiredMixin, InstructorOrStaffUserMixin, BlockMixin, UpdateView):
    template_name = 'studioadmin/includes/user-block-modal.html'
    action = "updated"

    def get_form_kwargs(self, *args, **kwargs):
        kwargs = super().get_form_kwargs(*args, **kwargs)
        kwargs['user'] = self.object.user
        return kwargs


class BlockAddView(LoginRequiredMixin, InstructorOrStaffUserMixin, BlockMixin, CreateView):
    template_name = 'studioadmin/includes/user-block-add-modal.html'
    action = "created"

    def dispatch(self, request, *args, **kwargs):
        self.block_user = User.objects.get(id=kwargs['user_id'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self, *args, **kwargs):
        kwargs = super().get_form_kwargs(*args, **kwargs)
        kwargs['user'] = self.block_user
        return kwargs

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["block_user"] = self.block_user
        return context


def ajax_block_delete(request, block_id):
    block = Block.objects.get(id=block_id)
    if block.paid:
        return HttpResponseBadRequest("Cannot delete a paid block")
    ActivityLog.objects.create(
        log=f"Block {block.block_config} (id {block_id}) for {full_name(block.user)} deleted by admin user {full_name(request.user)}"
    )
    block.delete()
    return JsonResponse({"deleted": True, "alert_msg": "Block deleted"})


class UserSubscriptionsListView(LoginRequiredMixin, InstructorOrStaffUserMixin, ListView):
    model = Subscription
    context_object_name = "subscriptions"
    template_name = "studioadmin/user_subscriptions_list.html"
    paginate_by = 20

    def dispatch(self, request, *args, **kwargs):
        self.user = get_object_or_404(User, pk=kwargs["user_id"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["account_user"] = self.user
        return context

    def get_queryset(self):
        return self.user.subscriptions.all().order_by("-expiry_date", "-start_date", "-purchase_date")


class SubscriptionMixin:
    form_class = AddEditSubscriptionForm
    model = Subscription

    def form_valid(self, form):
        subscription = form.save(commit=False)
        subscription_config_options = form.cleaned_data["subscription"]
        subscription_config_id, start_date = subscription_config_options.rsplit("_", 1)
        config = SubscriptionConfig.objects.get(id=subscription_config_id)
        start_date = datetime.strptime(start_date, "%d-%b-%Y")
        subscription.config = config
        subscription.start_date = start_date
        # TODO if config has changed, check if subscription had bookings that are no longer valid?
        if form.is_valid():
            subscription.save()
            ActivityLog.objects.create(
                log=f"Subscription id {subscription.id} ({subscription.config.name}) "
                    f"for user {full_name(subscription.user)} {self.action} by admin user {full_name(self.request.user)}"
            )
            messages.success(self.request, f"Subscription {self.action}")
            return HttpResponse(
                render_to_string(
                    'studioadmin/includes/modal-success.html'
                )
            )
        else:
            context = self.get_context_data()
            context["form"] = form
            return render(self.request, self.template_name, context)


class SubscriptionEditView(LoginRequiredMixin, InstructorOrStaffUserMixin, SubscriptionMixin, UpdateView):
    template_name = 'studioadmin/includes/user-subscription-modal.html'
    action = "updated"

    def get_form_kwargs(self, *args, **kwargs):
        kwargs = super().get_form_kwargs(*args, **kwargs)
        kwargs['user'] = self.object.user
        return kwargs


class SubscriptionAddView(LoginRequiredMixin, InstructorOrStaffUserMixin, SubscriptionMixin, CreateView):
    template_name = 'studioadmin/includes/user-subscription-add-modal.html'
    action = "created"

    def dispatch(self, request, *args, **kwargs):
        self.subscription_user = User.objects.get(id=kwargs['user_id'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self, *args, **kwargs):
        kwargs = super().get_form_kwargs(*args, **kwargs)
        kwargs['user'] = self.subscription_user
        return kwargs

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["subscription_user"] = self.subscription_user
        return context


def ajax_subscription_delete(request, subscription_id):
    subscription = Subscription.objects.get(id=subscription_id)
    if subscription.paid:
        return HttpResponseBadRequest("Cannot delete a paid subscription")
    ActivityLog.objects.create(
        log=f"Subscription {subscription.config} (id {subscription_id}) for {full_name(subscription.user)} deleted by admin user {full_name(request.user)}"
    )
    subscription.delete()
    return JsonResponse({"deleted": True, "alert_msg": "Subscription deleted"})