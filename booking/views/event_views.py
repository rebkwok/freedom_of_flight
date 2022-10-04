from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, HttpResponseRedirect, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.generic import ListView, DetailView

from booking.templatetags.bookingtags import can_book_or_cancel, on_waiting_list
from common.utils import full_name


from ..forms import AvailableUsersForm, EventNameFilterForm
from ..models import Course, Event, Track, get_active_user_block, has_available_block, has_available_course_block, \
    get_active_user_course_block
from ..utils import can_book, can_cancel, can_rebook, get_view_as_user, get_user_booking_info, user_can_book_or_cancel, user_course_booking_type
from .views_utils import DataPolicyAgreementRequiredMixin


def home(request):
    track = Track.get_default()
    if track is None:
        return HttpResponse("No tracks created yet.")
    return HttpResponseRedirect(reverse("booking:events", args=(track.slug,)))


def _default_button_options(user, event):
    if event.cancelled:
        return {"buttons": [], "text": f"{event.event_type.label.upper()} CANCELLED"}, None
    
    if event.is_past:
        text = "is past" if event.course else "has started"
        return {"buttons": [], "text": f"{event.event_type.label.title()} {text}"}, None

    if event.course:
        user_booking = user.bookings.filter(event=event, status="OPEN").first()
    else:
        user_booking = user.bookings.filter(event=event).first()
    
    has_open_booking = user_booking is not None and user_booking.status == "OPEN" and user_booking.no_show == False 
    
    return {"buttons": [], "text": "", "open": has_open_booking}, user_booking


def button_options_events_list(user, event):
    """
    Determine button/payment options that should be shown for a given user and event
    """
    # Has user booked already?
    # Has user booked and cancelled?
    # Is event cancelled?
    # Is event full?
    # Can event be booked?

    options, user_booking = _default_button_options(user, event)
    if "open" not in options:
        # event is cancelled or past
        return options

    has_open_booking = options["open"]
    # events list page
    # waiting list buttons
    # only if event is full and user isn't already booked
    if event.full:
        if not has_open_booking:
            options["buttons"] = ["waiting_list"]
            return options

    # an event from a course which has started and doesn't allow any booking options
    if (
        event.course and 
        event.course.has_started and not 
        any([event.course.allow_drop_in, has_open_booking])
    ):
        return {**options, "buttons": ["course_details"], "text": "Course has started"}

    if user_can_book_or_cancel(event, user_booking):
        user_can_cancel = can_cancel(user_booking)
        if user_can_cancel:
            options["buttons"] = ["toggle_booking"]
            options["toggle_button"] = {
                "option": "cancel",
                "enabled": True, # True/False
                "text": "",  # Additional text to display with the button
            }
            return options
        
        user_can_rebook = can_rebook(user_booking, event)
        if user_can_rebook:
            options["buttons"] = ["toggle_booking"]
            options["toggle_button"] = {
                "option": "rebook",
                "enabled": True, # True/False
                "text": "",  # Additional text to display with the button
            }
            return options

        booking_restricted = event.booking_restricted_pre_start()
        user_can_book = can_book(user_booking, event, booking_restricted=booking_restricted)
        assert user_can_book

        has_available_drop_in_block = has_available_block(user, event, dropin_only=True)
        if event.course:
            if not event.course.has_started and has_available_course_block(user, event.course):
                # user has a course block, send them to the course details page to book whole course
                text = mark_safe(
                    '<span class="helptext float-right">NOT BOOKED</span><br/>'
                    '<span class="helptext float-right">Payment plan available; see course details</span>'
                )
                return {**options, "buttons": [], "text": text}
            if event.course.allow_drop_in:
                has_booked_dropin = user_course_booking_type(user, event.course) == "dropin"
                if has_available_drop_in_block:
                    if not event.course.has_started or has_booked_dropin:
                        text = mark_safe(
                            '<span class="helptext float-right">Drop-in and course options available;'
                            '<br/>see course details to book</span>'
                        )
                        return {**options, "buttons": [], "text": text}
                    else:
                        options["buttons"] = ["toggle_booking"]
                        options["toggle_button"] = {
                            "option": "book_dropin",
                            "enabled": True, # True/False
                            "text": "",  # Additional text to display with the button
                        }
                        return options
                else:
                    options["buttons"] = ["payment_options", "add_to_basket"]
                    if not event.course.has_started:
                        options["buttons"].append("add_course_to_basket")
                    return options
            
            options["buttons"] = ["payment_options"]
            if not event.course.has_started:
                options["buttons"].append("add_course_to_basket")
            return options
        elif has_available_drop_in_block:
            options["buttons"] = ["toggle_booking"]
            options["toggle_button"] = {
                "option": "book_dropin",
                "enabled": True, # True/False
                "text": "",  # Additional text to display with the button
            }
            return options
        else:
            options["buttons"] = ["payment_options", "add_to_basket"]
            return options

    elif event.booking_restricted_pre_start():
        return {**options, "buttons": [], "text": f"Unavailable { event.event_type.booking_restriction } mins before start"}


def button_options_course_events_list(user, event):
    """
    Determine button/payment options that should be shown for a given user and event
    """
    # Has user booked already?
    # Has user booked and cancelled?
    # Is event cancelled?
    # Is event full?
    # Can event be booked?

    options, user_booking = _default_button_options(user, event)
    if "open" not in options:
        # event is cancelled or past
        return options

    has_open_booking = options["open"]

    # course events list page
    # waiting list buttons
    # if event allows drop in, we can show waiting list and book buttons
    if event.full and not has_open_booking:
        return {**options, "buttons": ["waiting_list"], "text": ""}

    if user_can_book_or_cancel(event, user_booking):
        user_can_cancel = can_cancel(user_booking)
        if user_can_cancel:
            options["buttons"] = ["toggle_booking"]
            options["toggle_button"] = {
                "option": "cancel",
                "enabled": True, # True/False
                "text": "",  # Additional text to display with the button
            }
            return options
        
        user_can_rebook = can_rebook(user_booking, event)
        if user_can_rebook:
            options["buttons"] = ["toggle_booking"]
            options["toggle_button"] = {
                "option": "rebook",
                "enabled": True, # True/False
                "text": "",  # Additional text to display with the button
            }
            return options

        user_has_available_dropin_block = has_available_block(user, event, dropin_only=True)
        user_has_available_course_block = has_available_course_block(user, event.course)
        user_has_available_block = user_has_available_course_block or user_has_available_dropin_block
        if user_has_available_block:
            # has either a dropin or course block
            if not user_has_available_course_block:
                # user has drop in block ONLY
                # if course hasn't started yet, show add course button
                if not event.course.has_started:
                    options["buttons"] = ["add_course_to_basket"]
                if event.course.allow_drop_in:
                    options["buttons"].append("toggle_booking")
                    options["toggle_button"] = {
                        "option": "book_dropin",
                        "enabled": True, # True/False
                        "text": "",  # Additional text to display with the button
                    }
                return options
            # user definitely has a course block and MAY have a drop in block too
            if not event.course.has_started:
                # course hasn't started, instruct to book using book course button
                options["text"] = mark_safe(
                    '<span class="float-right">You have an available course payment plan<br/>Use the button above to book the full course</span><br/>'
                    )
                if event.course.allow_drop_in:
                    # if they've already booked drop in, either show dropin option, or add note about drop-in booking
                    if user_has_available_dropin_block:
                        options["buttons"] = ["toggle_booking"]
                        options["toggle_button"] = {
                            "option": "book_dropin",
                            "enabled": True, # True/False
                            "text": "",  # Additional text to display with the button
                        }
                        return options
                    else:
                        options["buttons"] = ["add_to_basket"]
                        return options
            else:
                # course has started already, show drop-in buttons if allowed
                if event.course.allow_drop_in:
                    if user_has_available_dropin_block:
                        options["buttons"] = ["toggle_booking"]
                        options["toggle_button"] = {
                            "option": "book_dropin",
                            "enabled": True, # True/False
                            "text": "",  # Additional text to display with the button
                        }
                        return options
                    else:
                        options["buttons"] = ["add_to_basket"]
                        return options
        # no available block
        # drop in allowed
        elif event.course.allow_drop_in:
            if not event.course.has_started:
                options["buttons"].append("add_course_to_basket")
            options["buttons"].append("add_to_basket")
            return options
        # drop in not allowed
        else:
            if not event.course.has_started:
                options["buttons"] = ["add_course_to_basket"]
        return options


def button_options_book_course_button(user, course):
    options = {
        "button": None,  # can be "book", "unenroll", None
        "pre_button_text": "",
        "post_button_text": ""
    }

    """
    1) user has already booked: unenroll / user is attending
    2) (dropin) booked_for_events
        text: user has booked for classes on this course
        if course not full:
            if has available course block and course not started
                book / you can switch your current class bookings to a course booking
                
    3) course full: None / course full
        if allows dropin and not all course events full:
           None / some classes can be booked as drop in + available block info if applicable
    4) course has started:
        if allows dropin: 
           None / course has started - some classes can be booked as drop in + available block info if applicable
        elif allows partial booking and has availble payment plan:
            if user has block:
                book / ?
            else:
                None / payment options?
        else
            None / course has started
    5) course hasn't started
        if has available course block:
            book / + available block info
        elif allows dropin:
            None / classes can be booked as drop in + available block info if applicable
    """
    already_booked = user.bookings.filter(event__course=course, status="OPEN").count() == course.uncancelled_events.count()
    booked_for_events = user.bookings.filter(event__course=course, status="OPEN", no_show=False).exists()

    if already_booked:
        date_first_booked = user.bookings.filter(event__course=course).first().date_booked
        unenrollment_time = date_first_booked + timedelta(hours=24)
        within_unenrollment_time = timezone.now() < unenrollment_time
        can_unenroll = not course.has_started and within_unenrollment_time
        unenroll_end_date = min(unenrollment_time, course.start)
    
    # already booked for full course
    if already_booked:
        options["pre_button_text"] = f"{full_name(user)} is attending this course."
        if can_unenroll:
            options["button"] = "unenroll"
            options["post_button_text"] = mark_safe(
                '<em><span class="text-primary">'
                'You can reschedule your course for 24hrs from the date of first booking or until '
                'the course starts (whichever is earlier).</span><br/>'
                'Unenrolling will make your payment plan available for use on another eligible course '
                f'(allowed until {unenroll_end_date.strftime("%d %b %Y %H:%M")}).</em>'
            )
        return options
    
    user_has_available_course_block = has_available_course_block(user, course)
    user_has_available_dropin_block = has_available_block(user, course.events.first(), dropin_only=True)

    # already booked for events, but not all (i.e. drop in)
    if booked_for_events:
        options["pre_button_text"] = f"{full_name(user)} has booked for classes on this course."
        if not course.full:
            if not course.has_started and user_has_available_course_block:
                available_course_block = get_active_user_course_block(user, course)
                options["button"] = "book"
                options["post_button_text"] = mark_safe(
                    '<em>You have a course credit block available; you can switch your current class '
                    'bookings to a course booking if you wish. </em><br/>'
                    '<em>'
                    f'Payment plan available: Credit block - {available_course_block.block_config.name}'
                    '</em><br/>'
                )
        return options
    
    # full course; may still have drop in options
    if course.full:
        if course.allow_drop_in and not course.all_events_full:
            options["pre_button_text"] = "There are no spaces left for the full course. Drop-in is available for some classes."
            if user_has_available_dropin_block:
                options["post_button_text"] = "You have an available drop-in payment plan"
        else:
            options["pre_button_text"] = "This course is full."
        return options
    
    if not course.has_started: 
        if user_has_available_course_block:
            available_course_block = get_active_user_course_block(user, course)
            # not started; show book button and available course block; don't show dropin options
            options["pre_button_text"] = mark_safe(
                f'<em>Payment plan available: Credit block - {available_course_block.block_config.name}</em>'
            )
            options["button"] = "book"
    else:
        options["pre_button_text"] = "This course has started"

    if course.allow_drop_in:
        if course.has_started:
            options["pre_button_text"] += "<br/><em>You can book individual classes on this course as drop in.</em>"
        else:
            options["pre_button_text"] += "<br/><em>You can book the full course or drop in for individual classes.</em>"
        purchase_url = reverse("booking:course_purchase_options", args=(course.slug,))
        if user_has_available_dropin_block:
            options["post_button_text"] = "You have an available drop-in payment plan"
        else:
            options["post_button_text"] += f'''
            To book drop in, either add classes to your basket below, or go to the
            <a href="{purchase_url}">payment plans</a> page to see available payment options.
            '''
            
    options["pre_button_text"] = mark_safe(options["pre_button_text"])
    options["post_button_text"] = mark_safe(options["post_button_text"])
    
    return options
    


class EventListView(DataPolicyAgreementRequiredMixin, ListView):

    model = Event
    context_object_name = 'events_by_date'
    template_name = 'booking/events.html'

    def post(self, request, *args, **kwargs):
        view_as_user = request.POST.get("view_as_user")
        self.request.session["user_id"] = int(view_as_user)
        return HttpResponseRedirect(reverse("booking:events", args=(self.kwargs["track"],)))

    def get_queryset(self):
        track = get_object_or_404(Track, slug=self.kwargs["track"])
        cutoff_time = timezone.now() - timedelta(minutes=10)
        events = Event.objects.select_related("event_type").filter(
            event_type__track=track, start__gt=cutoff_time, show_on_site=True, cancelled=False
        ).order_by('start__date', 'start__time', "id")
        event_name = self.request.GET.get("event_name")
        if event_name:
            events = events.filter(name__iexact=event_name)
        return events

    def get_title(self):
        return Track.objects.get(slug=self.kwargs["track"]).name

    def _get_button_info(self, user, events):
        return {
            event.id: button_options_events_list(user, event) for event in events
        }

    def get_context_data(self, **kwargs):
        # Call the base implementation first to get a context
        context = super().get_context_data(**kwargs)
        all_events = self.get_queryset()

        page = self.request.GET.get('page', 1)
        all_paginator = Paginator(all_events, 20)
        page_events = all_paginator.get_page(page)
        event_ids_by_date = page_events.object_list.values('start__date').annotate(count=Count('id')).values('start__date', 'id')
        events_by_date = {}
        for event_info in event_ids_by_date:
            events_by_date.setdefault(event_info["start__date"], []).append(all_events.get(id=event_info["id"]))

        context["page_events"] = page_events
        context["events_by_date"] = events_by_date
        context['title'] = self.get_title()

        if "track" in self.kwargs:
            track = Track.objects.get(slug=self.kwargs["track"])
            context['track'] = track
            context["courses_available"] = any(
                [course for course in Course.objects.filter(event_type__track=track, cancelled=False, show_on_site=True)
                 if course.last_event_date and course.last_event_date.date() >= timezone.now().date()]
            )
            event_name = self.request.GET.get("event_name")
            if event_name:
                context["name_filter_form"] = EventNameFilterForm(track=track, initial={"event_name": event_name})
            else:
                context["name_filter_form"] = EventNameFilterForm(track=track)

        if self.request.user.is_authenticated:
            # Add in the booked_events
            # All user bookings for events in this list view (may be cancelled)
            view_as_user = get_view_as_user(self.request)
            user_booking_info = {
                event.id: get_user_booking_info(view_as_user, event) for event in page_events.object_list
            }
            context["user_booking_info"] = user_booking_info
            context["available_users_form"] = AvailableUsersForm(request=self.request, view_as_user=view_as_user)
            context["buttons"] = self._get_button_info(view_as_user, page_events.object_list)
        return context


class EventDetailView(DataPolicyAgreementRequiredMixin, DetailView):

    model = Event
    context_object_name = 'event'
    template_name = 'booking/event.html'

    def get_object(self):
        return get_object_or_404(Event, slug=self.kwargs['slug'])

    def get_context_data(self, **kwargs):
        # Call the base implementation first to get a context
        context = super().get_context_data()
        if self.request.user.is_authenticated:
            view_as_user = get_view_as_user(self.request)
            open_booking = view_as_user.bookings.filter(event=self.object, user=view_as_user, status="OPEN", no_show=False).first()
            context["open_booking"] = open_booking
        return context


class CourseEventsListView(EventListView):

    def get_title(self):
        return Course.objects.get(slug=self.kwargs["course_slug"]).name

    def post(self, request, *args, **kwargs):
        view_as_user = request.POST.get("view_as_user")
        self.request.session["user_id"] = view_as_user
        return HttpResponseRedirect(reverse("booking:course_events", args=(self.kwargs["course_slug"],)))

    def get_queryset(self):
        course_slug =self.kwargs["course_slug"]
        return Event.objects.filter(course__slug=course_slug).order_by('start__date', 'start__time')

    def _get_button_info(self, user, events):
        return {
            event.id: button_options_course_events_list(user, event) for event in events
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        course = Course.objects.get(slug=self.kwargs["course_slug"])
        context["course"] = course
        if self.request.user.is_authenticated:
            view_as_user = get_view_as_user(self.request)
            # already booked == has an open (no-show or not) booking for all events in the course
            # already_booked = view_as_user.bookings.filter(event__course=course, status="OPEN").count() == course.uncancelled_events.count()
            # context["already_booked"] = already_booked
            # if already_booked:
            #     date_first_booked = view_as_user.bookings.filter(event__course=course).first().date_booked
            #     unenrollment_time = date_first_booked + timedelta(hours=24)
            #     within_unenrollment_time = timezone.now() < unenrollment_time
            #     context["can_unenroll"] = not course.has_started and within_unenrollment_time
            #     context["unenroll_end_date"] = min(unenrollment_time, course.start)

            # context["booked_for_events"] = view_as_user.bookings.filter(event__course=course, status="OPEN", no_show=False).exists()
            # context["has_available_course_block"] = has_available_course_block(view_as_user, course)
            # context["has_available_dropin_block"] = has_available_block(view_as_user, course.events.first(), dropin_only=True)
            context["available_course_block"] = get_active_user_course_block(view_as_user, course)
            context["book_course_button_options"] = button_options_book_course_button(view_as_user, course)
        return context
