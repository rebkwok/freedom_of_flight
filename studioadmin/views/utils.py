from datetime import datetime
from datetime import timezone as dt_timezone

from functools import wraps
from urllib.parse import urlencode

from django.core.cache import cache
from django.contrib.auth.models import Group
from django.http import HttpResponse
from django.urls import reverse
from django.shortcuts import HttpResponseRedirect
from django.utils import timezone

from delorean import Delorean

from openpyxl import Workbook
from openpyxl.writer.excel import save_virtual_workbook
from openpyxl.cell.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font

from booking.models import Course


def _include_future_course(course, start_of_today):
    if course.last_event_date is None:
        return True
    else:
        return course.last_event_date >= start_of_today


def _include_not_started_course(course, start_of_today):
    if course.last_event_date is None:
        return True
    else:
        return course.start >= start_of_today


def _include_current_started_only(course, start_of_today):
    if course.last_event_date is None:
        return False
    else:
        return course.start >= start_of_today


def _include_past_course(course, start_of_today):
    if course.last_event_date is None:
        return False
    else:
        return course.last_event_date < start_of_today


def _get_courses(queryset, include_course_function):
    if queryset is None:
        queryset = Course.objects.all()
    start_of_today = timezone.now().replace(hour=0, minute=0, microsecond=0)
    return [course for course in queryset if include_course_function(course, start_of_today)]


def _start_for_sort(course):
    return course.start if course.start is not None else datetime.min.replace(tzinfo=dt_timezone.utc)


def get_current_courses(queryset=None):
    # for future courses, courses with least one event in the future, or have no events yet
    return sorted(_get_courses(queryset, _include_future_course), key=lambda course: _start_for_sort(course))


def get_not_yet_started_courses(queryset=None):
    # courses with all events in the future, or have no events yet
    return sorted(_get_courses(queryset, _include_not_started_course), key=lambda course: _start_for_sort(course))


def get_current_and_started_courses(queryset=None):
    return sorted(_get_courses(queryset, _include_current_started_only), key=lambda course: _start_for_sort(course))


def get_past_courses(queryset=None):
    # for past course, all events before the beginning of today
    return sorted(_get_courses(queryset, _include_past_course), key=lambda course: course.start, reverse=True)


def staff_required(func):
    def decorator(request, *args, **kwargs):
        cached_is_staff = cache.get('user_%s_is_staff' % str(request.user.id))
        if cached_is_staff is not None:
            user_is_staff = bool(cached_is_staff)
        else:
            user_is_staff = request.user.is_staff
            # cache for 30 mins
            cache.set('user_%s_is_staff' % str(request.user.id), user_is_staff, 1800)
        if user_is_staff:
            return func(request, *args, **kwargs)
        else:
            return HttpResponseRedirect(reverse('booking:permission_denied'))
    return wraps(func)(decorator)


def is_instructor_or_staff(func):
    def decorator(request, *args, **kwargs):
        cached_is_instructor_or_staff = cache.get('user_%s_is_instructor_or_staff' % str(request.user.id))
        if cached_is_instructor_or_staff is not None:
            user_is_instructor_or_staff = bool(cached_is_instructor_or_staff)
        else:
            group, _ = Group.objects.get_or_create(name='instructors')
            user_is_instructor_or_staff = request.user.is_staff or group in request.user.groups.all()
            cache.set('user_%s_is_instructor_or_staff' % str(request.user.id), user_is_instructor_or_staff, 1800)

        if user_is_instructor_or_staff:
            return func(request, *args, **kwargs)
        else:
            return HttpResponseRedirect(reverse('booking:permission_denied'))
    return wraps(func)(decorator)


class StaffUserMixin:
    def dispatch(self, request, *args, **kwargs):
        cached_is_staff = cache.get('user_%s_is_staff' % str(request.user.id))
        if cached_is_staff is not None:
            user_is_staff = bool(cached_is_staff)
        else:
            user_is_staff = self.request.user.is_staff
            cache.set('user_%s_is_staff' % str(request.user.id), user_is_staff, 1800)
        if not user_is_staff:
            return HttpResponseRedirect(reverse('booking:permission_denied'))
        return super().dispatch(request, *args, **kwargs)


class InstructorOrStaffUserMixin:
    def dispatch(self, request, *args, **kwargs):
        cached_is_instructor_or_staff = cache.get('user_%s_is_instructor_or_staff' % str(request.user.id))
        if cached_is_instructor_or_staff is not None:
            user_is_instructor_or_staff = bool(cached_is_instructor_or_staff)
        else:
            group, _ = Group.objects.get_or_create(name='instructors')
            user_is_instructor_or_staff = self.request.user.is_staff or group in self.request.user.groups.all()
            cache.set('user_%s_is_instructor_or_staff' % str(request.user.id), user_is_instructor_or_staff, 1800)
        if user_is_instructor_or_staff:
            return super().dispatch(request, *args, **kwargs)
        return HttpResponseRedirect(reverse('booking:permission_denied'))


def utc_adjusted_datetime(naive_target_datetime):
    # Target datetime is naive, a date combined with the naive time that it received from user input or from a
    # unaware timetable session in the DB.
    # Check if it has a UTC offset in Europe/London
    naive_datetime_in_utc = Delorean(naive_target_datetime, timezone="UTC")
    uk_datetime = naive_datetime_in_utc.shift("Europe/London")
    utcoffset = uk_datetime.datetime.utcoffset()
    # return a datetime obj, not the Delorean datetime
    return naive_datetime_in_utc.datetime - utcoffset


def url_with_querystring(path, **kwargs):
    return path + '?' + urlencode(kwargs)


def generate_workbook_response(filename, sheet_title, header_info, object_list, object_to_row):
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename={filename}'

    header_font = Font(name='Calibri', size=12, bold=True)
    cell_font = Font(name='Calibri', size=11, bold=False)
    alignment = Alignment(wrap_text=True)

    wb = Workbook()
    sheet = wb.active
    sheet.title = sheet_title

    def _write_row(data, is_header=False):
        font = header_font if is_header else cell_font
        row = []
        for cell in data:
            cell = WriteOnlyCell(sheet, cell)
            cell.font = font
            cell.alignment = alignment
            row.append(cell)
        sheet.append(row)

    _write_row(header_info.keys(), is_header=True)

    for obj in object_list:
        row = object_to_row(obj)
        if row:
            _write_row(row)

    for i, column_cells in enumerate(sheet.columns):
        sheet.column_dimensions[column_cells[0].column_letter].width = list(header_info.values())[i]

    workbook = save_virtual_workbook(wb)
    container = [response.make_bytes(workbook)]
    response.content = b''.join(container)
    return response
