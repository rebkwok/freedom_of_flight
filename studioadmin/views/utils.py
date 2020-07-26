from functools import wraps

from django.core.cache import cache
from django.contrib.auth.models import Group
from django.urls import reverse
from django.shortcuts import HttpResponseRedirect
from django.utils import timezone

from delorean import Delorean


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
