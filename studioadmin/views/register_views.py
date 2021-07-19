from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseBadRequest, JsonResponse, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.template.loader import render_to_string
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.utils.text import slugify
from django.urls import reverse

from braces.views import LoginRequiredMixin

from openpyxl import Workbook
from openpyxl.writer.excel import save_virtual_workbook
from openpyxl.cell.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font

from activitylog.models import ActivityLog
from booking.email_helpers import send_waiting_list_email
from booking.models import Booking, Event, WaitingListUser
from common.utils import full_name

from ..forms import AddRegisterBookingForm, RegisterFormSet
from .event_views import BaseEventAdminListView
from .utils import is_instructor_or_staff, InstructorOrStaffUserMixin


class RegisterListView(LoginRequiredMixin, InstructorOrStaffUserMixin, BaseEventAdminListView):
    template_name = "studioadmin/registers.html"
    custom_paginate_by = 10

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(cancelled=False)


@login_required
@is_instructor_or_staff
def register_view(request, event_id):
    template = 'studioadmin/register.html'
    event = get_object_or_404(Event, pk=event_id)
    bookings = event.bookings.filter(status="OPEN").order_by('date_booked')

    if request.method == 'POST':
        formset = RegisterFormSet(request.POST, queryset=bookings)
        if formset.is_valid():
            formset.save()
            return HttpResponseRedirect(reverse("studioadmin:register", args=(event_id,)))
    else:
        register_formset = RegisterFormSet(queryset=bookings)

    return TemplateResponse(
        request, template, {
            'event': event, 'bookings': bookings, "register_formset": register_formset,
            'can_add_more': event.spaces_left > 0,
        }
    )


@login_required
@is_instructor_or_staff
def ajax_add_register_booking(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    if request.method == 'GET':
        form = AddRegisterBookingForm(event=event)

    else:
        form = AddRegisterBookingForm(request.POST, event=event)
        if event.spaces_left > 0:
            if form.is_valid():
                process_event_booking_updates(form, event, request)
                return HttpResponse(
                    render_to_string(
                        'studioadmin/includes/register-booking-add-success.html'
                    )
                )
        else:
            form.add_error(
                '__all__',
                'Event is now full, booking could not be created. '
                'Please close this window and refresh register page.'
            )

    context = {'form_event': event, 'form': form}
    return TemplateResponse(
        request, 'studioadmin/includes/register-booking-add-modal.html', context
    )


def process_event_booking_updates(form, event, request):
    user_id = int(form.cleaned_data['user'])
    booking, created = Booking.objects.get_or_create(user_id=user_id, event=event)
    if created:
        action = 'opened'
    elif booking.status == 'OPEN' and not booking.no_show:  # pragma: no cover
        # we shouldn't ever get here because the form only shows user choices for users that aren't
        # already booked, but this is here just on the off chance that a user books at the same time as we
        # try to add a booking in the register
        messages.info(request, 'Open booking for this user already exists')
        return
    else:
        booking.status = 'OPEN'
        booking.no_show = False
        action = 'reopened'

    # if there's no subscription OR block, look for available ones.  Don't change what's set on an existing booking already.
    if not booking.subscription and not booking.block:
        booking.assign_next_available_subscription_or_block()
        if not booking.subscription and not booking.block:
            messages.warning(request, "User does not have a valid subscription or block for this event")
    booking.save()

    messages.success(request, f'Booking for {booking.event} has been {action}.')
    ActivityLog.objects.create(
        log=f'Booking id {booking.id} (user {booking.user.username}) for {booking.event} '
            f'{action} by admin user {request.user.username}.'
    )

    try:
        waiting_list_user = WaitingListUser.objects.get(user=booking.user,  event=booking.event)
        waiting_list_user.delete()
        ActivityLog.objects.create(
            log='User {booking.user.username} has been removed from the waiting list for {booking.event}'
        )
    except WaitingListUser.DoesNotExist:
        pass


@login_required
@is_instructor_or_staff
@require_http_methods(['POST'])
def ajax_toggle_attended(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    attendance = request.POST.get('attendance')
    if not attendance or attendance not in ['attended', 'no-show']:
        return HttpResponseBadRequest('No attendance data')

    alert_msg = None
    event_was_full = booking.event.spaces_left == 0
    if attendance == 'attended':
        # no need to check for full for course events; users can't cancel out of them, can always reopen
        if not booking.event.course \
                and (booking.no_show or booking.status == 'CANCELLED') and booking.event.spaces_left == 0:
            return HttpResponseBadRequest(f'{booking.event.event_type.label.title()} is now full, cannot reopen booking.')
        else:
            if booking.attended:  # clicking on attended again - toggle off
                booking.attended = False
            else:
                booking.status = 'OPEN'
                booking.attended = True
                booking.no_show = False
    elif attendance == 'no-show':
        if booking.no_show: # clicking on no-show again - toggle off
            booking.no_show = False
        else:
            booking.attended = False
            booking.no_show = True
    booking.save()

    ActivityLog.objects.create(
        log=f'User {booking.user.username} marked as {attendance} for {booking.event} '
        f'by admin user {request.user.username}'
    )

    # no need to check for full for course events; users can't cancel out of them, can always reopen
    if not booking.event.course and \
            event_was_full and attendance == 'no-show' and booking.event.start > (timezone.now() + timedelta(hours=1)):
        # Only send waiting list emails if marking booking as no-show more than 1 hr before the event start
        host = 'http://{}'.format(request.META.get('HTTP_HOST'))
        waiting_list_users = WaitingListUser.objects.filter(event=booking.event)
        send_waiting_list_email(booking.event, waiting_list_users, host)
    return JsonResponse(
        {'attended': booking.attended, 'no_show': booking.no_show, "spaces_left": booking.event.spaces_left, 'alert_msg': alert_msg}
    )


@login_required
@is_instructor_or_staff
def download_register(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    bookings = event.bookings.filter(status="OPEN", no_show=False)

    childrens_event = False
    if bookings.exists() and bookings.first().user.age < 17:
        childrens_event = True

    filename = f"{slugify(event.name)}_{slugify(event.start.strftime('%d %b %Y'))}.xlsx"

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename={filename}'

    header_font = Font(name='Calibri', size=14, bold=True)
    cell_font = Font(name='Calibri', size=11, bold=False)
    alignment = Alignment(wrap_text=True)

    wb = Workbook()
    worksheet_name = slugify(f"{event.name} {event.start.strftime('%d %b %Y, %H:%M')}")[:31]
    sheet = wb.active
    sheet.title = worksheet_name

    def _write_row(data, is_header=False):
        font = header_font if is_header else cell_font
        row = []
        for cell in data:
            cell = WriteOnlyCell(sheet, cell)
            cell.font = font
            cell.alignment = alignment
            row.append(cell)
        sheet.append(row)

    header = [
        "Name", "Date of Birth", "Emergency Contact",
        "Emergency Contact Relationship", "Emergency Contact Phone"
    ]
    col_widths = [20, 12, 20, 20, 20]

    if childrens_event:
        header.insert(2, "Age")
        col_widths.insert(2, 8)

    _write_row(header, is_header=True)

    for booking in bookings:
        user = booking.user
        disclaimer = user.online_disclaimer.latest("id")
        if user.manager_user is not None:
            profile = user.childuserprofile
        else:
            profile = user.userprofile
        # row_num += 1
        age = [profile.user.age] if childrens_event else []
        row = [
            full_name(user),
            profile.date_of_birth.strftime("%d %b %Y")
        ] + age + [
            disclaimer.emergency_contact_name,
            disclaimer.emergency_contact_relationship,
            disclaimer.emergency_contact_phone
        ]
        _write_row(row)

    for i, column_cells in enumerate(sheet.columns):
        sheet.column_dimensions[column_cells[0].column_letter].width = col_widths[i]

    workbook = save_virtual_workbook(wb)
    container = [response.make_bytes(workbook)]
    response.content = b''.join(container)
    return response
