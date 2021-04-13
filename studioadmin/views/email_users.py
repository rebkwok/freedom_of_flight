import ast
import logging

from math import ceil

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User

from django.contrib import messages
from django.core.mail.message import EmailMultiAlternatives
from django.db.models import Q
from django.urls import reverse
from django.template.loader import get_template
from django.template.response import TemplateResponse
from django.shortcuts import HttpResponseRedirect
from django.utils.safestring import mark_safe

from booking.models import Event, Booking, Course

from studioadmin.forms.email_users_forms import EmailUsersForm, ChooseUsersFormSet, UserFilterForm
from studioadmin.views.utils import staff_required, url_with_querystring

from activitylog.models import ActivityLog


logger = logging.getLogger(__name__)


@login_required
@staff_required
def choose_users_to_email(
        request, template_name='studioadmin/choose_users_form.html'
):
    userfilterform = UserFilterForm(prefix='filter')
    showing_students = False

    if 'filter' in request.POST:
        showing_students = True
        event_ids = request.POST.getlist('filter-events')
        course_ids = request.POST.getlist('filter-courses')
        student_ids = request.POST.getlist('filter-students')
        if not event_ids:
            if request.session.get('events'):
                del request.session['events']
            event_ids = []
        else:
            request.session['events'] = event_ids

        if not course_ids:
            if request.session.get('courses'):
                del request.session['courses']
            course_ids = []
        else:
            request.session['courses'] = course_ids

        if not student_ids:
            if request.session.get('students'):
                del request.session['students']
            student_ids = []
        else:
            request.session['students'] = student_ids

        if not event_ids and not course_ids and not student_ids:
            usersformset = ChooseUsersFormSet(queryset=User.objects.none())
        else:
            event_ids = Event.objects.filter(Q(id__in=event_ids) | Q(course__id__in=course_ids))
            user_ids_from_bookings = Booking.objects.filter(
                event__id__in=event_ids, status="OPEN"
            ).order_by().distinct("user").values_list("user__id", flat=True)
            user_ids = set(user_ids_from_bookings) | set(student_ids)

            usersformset = ChooseUsersFormSet(
                queryset=User.objects.filter(id__in=user_ids).order_by('first_name', 'last_name')
            )
            userfilterform = UserFilterForm(
                prefix='filter',
                initial={'events': event_ids, 'courses': course_ids, 'students': student_ids}
            )

    elif request.method == 'POST':
        userfilterform = UserFilterForm(prefix='filter', data=request.POST)
        usersformset = ChooseUsersFormSet(request.POST)

        if usersformset.is_valid():
            event_ids = request.session.get('events', [])
            course_ids = request.session.get('courses', [])
            users_to_email = []

            for form in usersformset:
                # check checkbox value to determine if that user is to be
                # emailed; add user_id to list
                if form.is_valid():
                    if form.cleaned_data.get('email_user'):
                        users_to_email.append(form.instance.id)

            request.session['users_to_email'] = users_to_email

            return HttpResponseRedirect(url_with_querystring(
                reverse('studioadmin:email_users_view'),
                events=event_ids, courses=course_ids)
            )

    else:
        # for a new GET, remove any event/course session data
        if request.session.get('events'):
            del request.session['events']
        if request.session.get('courses'):
            del request.session['courses']
        if request.session.get('students'):
            del request.session['students']
        usersformset = ChooseUsersFormSet(queryset=User.objects.none())

    return TemplateResponse(
        request, template_name, {
            'usersformset': usersformset,
            'userfilterform': userfilterform,
            'showing_students': showing_students
            }
    )


@login_required
@staff_required
def email_users_view(request, template_name='studioadmin/email_users_form.html'):

        users_to_email = User.objects.filter(
            id__in=request.session['users_to_email']
        )

        if request.method == 'POST':
            form = EmailUsersForm(request.POST)
            test_email = request.POST.get('send_test', False)

            if form.is_valid():
                subject = f"{form.cleaned_data['subject']} {'[TEST EMAIL]' if test_email else ''}"
                from_address = form.cleaned_data['from_address']
                message = mark_safe(form.cleaned_data['message'])
                cc = form.cleaned_data['cc']

                # bcc recipients
                email_addresses = [user.contact_email for user in users_to_email]
                email_count = len(email_addresses)
                number_of_emails = ceil(email_count / 99)

                if test_email:
                    email_lists = [[from_address]]
                else:
                    email_lists = [email_addresses]  # will be a list of lists
                    # split into multiple emails of 99 bcc plus 1 cc
                    if email_count > 99:
                        email_lists = [
                            email_addresses[i : i + 99]
                            for i in range(0, email_count, 99)
                            ]

                host = 'http://{}'.format(request.META.get('HTTP_HOST'))

                for i, email_list in enumerate(email_lists):
                    ctx = {
                              'subject': subject,
                              'message': message,
                              'number_of_emails': number_of_emails,
                              'email_count': email_count,
                              'is_test': test_email,
                              'host': host,
                          }
                    msg = EmailMultiAlternatives(
                        subject,
                        get_template(
                            'studioadmin/email/email_users.txt').render(
                                ctx
                            ),
                        bcc=email_list,
                        cc=[from_address]
                        if (i == 0 and cc and not test_email) else [],
                        reply_to=[from_address]
                        )
                    msg.send(fail_silently=False)

                    if not test_email:
                        ActivityLog.objects.create(
                            log='Bulk email with subject "{}" sent to users {} by'
                                ' admin user {}'.format(
                                    subject, ', '.join(email_list),
                                    request.user.username
                                )
                        )

                if not test_email:
                    messages.success(
                        request,
                        f'Bulk email with subject "{subject}" has been sent to users'
                    )
                    return HttpResponseRedirect(reverse('studioadmin:users'))
                else:
                    messages.success(
                        request, 'Test email has been sent to {} only. Click '
                                 '"Send Email" below to send this email to '
                                 'users.'.format(from_address)
                    )

            # Do this if form not valid OR sending test email
            event_ids = request.session.get('events', [])
            course_ids = request.session.get('courses', [])
            events = Event.objects.filter(id__in=event_ids)
            courses = Course.objects.filter(id__in=course_ids)
            subject = subject_from_events_and_courses(events, courses)
            form = EmailUsersForm(initial={'subject': subject})
            if form.errors:
                messages.error(
                    request,
                    mark_safe(
                        "Please correct errors in form: {}".format(form.errors)
                    )
                )
            if test_email:
                form = EmailUsersForm(request.POST)

        else:
            event_ids = ast.literal_eval(request.GET.get('events', '[]'))
            events = Event.objects.filter(id__in=event_ids)
            course_ids = ast.literal_eval(request.GET.get('courses', '[]'))
            courses = Course.objects.filter(id__in=course_ids)
            form = EmailUsersForm(
                initial={'subject': subject_from_events_and_courses(events, courses)}
            )

        return TemplateResponse(
            request, template_name, {
                'form': form,
                'users_to_email': users_to_email,
                'events': events,
                'courses': courses,
            }
        )


def subject_from_events_and_courses(events, courses):
    event_str = [str(event) for event in events]
    course_str = [f"Course: {course.name}" for course in courses]
    return "; ".join(event_str + course_str)
