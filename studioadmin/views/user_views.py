from django.contrib import messages
from django.shortcuts import get_object_or_404, HttpResponseRedirect, reverse
from django.template.response import TemplateResponse

from booking.email_helpers import send_bcc_emails
from booking.models import Booking, Course, Event

from ..forms import EmailUsersForm


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
    booking_ids = form.cleaned_data.get("open_bookings", []) + form.cleaned_data.get("cancelled_bookings", [])
    selected_bookings = Booking.objects.filter(id__in=booking_ids)
    user_emails = set()
    for booking in selected_bookings:
        if hasattr(booking.user, "childuserprofile"):
            # send waiting list email to manager user
            user_emails.add(booking.user.childuserprofile.parent_user_profile.user.email)
        else:
            user_emails.add(booking.user.email)
    context = {"host": 'http://{}'.format(request.META.get('HTTP_HOST')), "message": form.cleaned_data["message"]}
    send_bcc_emails(
        context, user_emails, form.cleaned_data["subject"], "studioadmin/email/email_users",
        reply_to=form.cleaned_data["reply_to_email"], cc=form.cleaned_data["cc"]
    )
    messages.success(request, "Email sent")