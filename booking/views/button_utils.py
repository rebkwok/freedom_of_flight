from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

from common.utils import full_name

from ..models import add_to_cart_course_block_config, add_to_cart_drop_in_block_config, has_available_block, has_available_course_block, get_active_user_course_block, has_available_subscription, valid_course_block_configs, valid_dropin_block_configs
from ..utils import can_book, can_cancel, can_rebook, user_can_book_or_cancel, user_course_booking_type


class UserEventInfo:

    def __init__(self, user, event):
        self.user = user
        self.event = event
        self.course = event.course

        if self.course:
            self.user_bookings = user.bookings.filter(event=event, status="OPEN")
            self.user_course_bookings = user.bookings.filter(event__course=self.course, status="OPEN")
        else:
            self.user_bookings = user.bookings.filter(event=event)
            self.user_course_bookings = None
        self.user_booking = self.user_bookings.first()
        self.has_open_booking =  self.user_bookings.filter(status="OPEN", no_show=False).exists()
        self.open = not (self.event.cancelled or self.event.is_past) 
        self.booking_restricted = event.booking_restricted_pre_start()
        self.booking_in_basket = self.has_open_booking and self.user_booking.is_in_basket()
        
        # other attributes to be updated later
        self.can_book_or_cancel = False
        self.can_cancel = False
        self.can_book = False
        self.can_rebook = False
        self.has_available_drop_in_block = False
        self.has_available_subscription = False
        self.booking_type = None
        self.can_add_course_to_basket = False
        self.can_add_drop_in_to_basket = False
        self.has_payment_options = False

        # course things
        self.has_available_course_block = False
        self.has_booked_dropin = False
        self.user_course_booking_type = None
        self.has_available_block = False

        # for main course button
        self.course_booked = False
        self.booked_for_course_events = False
        self.can_unenroll = False
        self.unenroll_end_date = None
        self.available_course_block = None

    def update(self, include_course_data=False):
        self.can_book_or_cancel = user_can_book_or_cancel(self.event, self.user_booking)
        self.can_cancel = can_cancel(self.user_booking)
        self.can_rebook = can_rebook(self.user_booking, self.event)
        self.can_book = can_book(
            self.user_booking, self.event, booking_restricted=self.booking_restricted
        )
        self.has_available_drop_in_block = has_available_block(self.user, self.event, dropin_only=True)
        if self.course:
            self.has_available_course_block = has_available_course_block(self.user, self.event.course)
            self.has_booked_dropin = user_course_booking_type(self.user, self.event.course) == "dropin"
        self.has_available_block = self.has_available_drop_in_block or self.has_available_course_block
        self.has_available_subscription = has_available_subscription(self.user, self.event)

        if include_course_data and self.has_available_course_block:
            self.available_course_block = get_active_user_course_block(self.user, self.course)

        if self.event.course:
            if add_to_cart_course_block_config(self.event.course) is not None \
                and not self.has_available_course_block \
                    and not self.event.course.full \
                        and not self.event.course.has_started:
                self.can_add_course_to_basket = True
        if add_to_cart_drop_in_block_config(self.event) is not None \
            and not self.has_available_drop_in_block and not self.event.full:
            self.can_add_drop_in_to_basket = True

        if not self.event.course or self.event.course.allow_drop_in:
            if valid_dropin_block_configs(self.event).exists():
                self.has_payment_options = True
        elif self.event.course:
            self.has_payment_options = valid_course_block_configs(self.event.course).exists()

    def update_course_booking_status(self):
        self.course_booked = self.user_course_bookings.filter(block__paid=True).count() == self.course.uncancelled_events.count()
        self.course_in_basket = not self.course_booked and self.user_course_bookings.count() == self.course.uncancelled_events.count()
        self.booked_for_course_events = self.user_course_bookings.filter(block__paid=True, no_show=False).exists()

        if self.course_booked:
            date_course_first_booked = self.user_course_bookings.first().date_booked
            unenrollment_time = date_course_first_booked + timedelta(hours=24)
            within_unenrollment_time = timezone.now() < unenrollment_time
            self.can_unenroll = not self.course.has_started and within_unenrollment_time
            self.unenroll_end_date = min(unenrollment_time, self.course.start)

        
def _default_button_options(user_event_info):
    event = user_event_info.event
    # cancelled events shouldn't ever be shown, but just in case
    if event.cancelled:  # pragma: no cover
        return {"buttons": [], "text": f"{event.event_type.label.upper()} CANCELLED"}
    
    if event.is_past:
        text = "is past" if event.course else "has started"
        return {"buttons": [], "text": f"{event.event_type.label.title()} {text}"}
        
    return {
        "buttons": [], 
        "text": "", 
        "open": user_event_info.open, 
        "in_basket": user_event_info.booking_in_basket,
        "has_open_booking": user_event_info.has_open_booking
    }


# EVENTS/COURSE EVENTS LIST: Book/cancel/payment options/waiting list for individual classes
def button_options_events_list(user, event, course=False):
    """
    Determine button/payment options that should be shown for a given user and event
    """
    # Has user booked already?
    # Has user booked and cancelled?
    # Is event cancelled?
    # Is event full?
    # Can event be booked?
    user_event_info = UserEventInfo(user, event)
    options = _default_button_options(user_event_info)
    if not user_event_info.open:
        # event is cancelled or past
        return options

    user_event_info.update()
    if event.course:
        user_event_info.update_course_booking_status()

    if user_event_info.booking_in_basket:
        options["buttons"].append("view_cart")
        options["text"] = "In cart"
        return options

    # waiting list buttons
    # only if event is full and user isn't already booked
    if event.full:
        if not (user_event_info.has_open_booking or user_event_info.can_rebook):
            options["buttons"] = ["waiting_list"]
            options["text"] = f"{event.event_type.label.title()} is full"
            return options

    # an event from a course which has started
    if event.course and event.course.has_started:
        options["text"] = "Course has started"
        # and doesn't allow any booking options
        if not any([event.course.allow_drop_in, user_event_info.has_open_booking]):
            return options

    if user_event_info.can_book_or_cancel:
        if user_event_info.can_cancel:
            options["buttons"] = ["toggle_booking"]
            if user_event_info.can_unenroll:
                options["buttons"].append("unenroll")
            options["toggle_option"] = "cancel"
            return options
        
        if user_event_info.can_rebook:
            options["buttons"] = ["toggle_booking"]
            options["toggle_option"] = "rebook"
            return options

        assert user_event_info.can_book

        if event.course:
            if not event.course.has_started and not event.course.full and \
            user_event_info.has_available_course_block:
                # user has a course block
                options["buttons"] = ["book_course"]
            if event.course.allow_drop_in:
                if user_event_info.has_available_drop_in_block:
                    options["buttons"].append("toggle_booking")
                    options["toggle_option"] = "book_dropin"
                    if user_event_info.can_add_course_to_basket:
                        options["buttons"].append("add_course_to_basket")
                    options["buttons"].append("payment_options")
                    return options
                else:
                    if user_event_info.can_add_drop_in_to_basket:
                        options["buttons"].append("add_to_basket")
                    if user_event_info.can_add_course_to_basket:
                        options["buttons"].append("add_course_to_basket")
                    if user_event_info.has_payment_options:
                        options["buttons"].append("payment_options")
                    return options
            
            if user_event_info.can_add_course_to_basket:
                options["buttons"].append("add_course_to_basket")
            if user_event_info.has_payment_options:
                options["buttons"].append("payment_options")
            return options
        elif user_event_info.has_available_drop_in_block or user_event_info.has_available_subscription:
            options["buttons"].append("toggle_booking")
            options["toggle_option"] = "book_dropin"
            return options
        else:
            if user_event_info.can_add_drop_in_to_basket:
                options["buttons"].append("add_to_basket")
            if user_event_info.has_payment_options:
                options["buttons"].append("payment_options")
            return options

    elif user_event_info.booking_restricted:
        return {**options, "buttons": [], "text": f"Unavailable { event.event_type.booking_restriction } mins before start"}


# Main course book button on course events page
def button_options_book_course_button(user, course):
    user_event_info = UserEventInfo(user, course.uncancelled_events.first())
    user_event_info.update_course_booking_status()

    options = {
        "button": None,  # can be "book", "unenroll", None
        "pre_button_text": "",
        "post_button_text": ""
    }

    # already booked for full course
    if user_event_info.course_booked:
        options["pre_button_text"] = f"{full_name(user)} is attending this course."
        if user_event_info.can_unenroll:
            options["button"] = "unenroll"
            options["post_button_text"] = mark_safe(
                '<em><span class="text-primary">'
                'You can reschedule your course for 24hrs from the date of first booking or until '
                'the course starts (whichever is earlier).</span><br/>'
                'Unenrolling will make your payment plan available for use on another eligible course '
                f'(allowed until {user_event_info.unenroll_end_date.strftime("%d %b %Y %H:%M")}).</em>'
            )
        return options
    
    if user_event_info.course_in_basket:
        options["pre_button_text"] = f"Booking is provisionally held pending payment."
        return options
    
    user_event_info.update(include_course_data=True)
    # already booked for events, but not all (i.e. drop in)
    if user_event_info.booked_for_course_events:
        options["pre_button_text"] = f"{full_name(user)} has booked for classes on this course."
        if not course.full:
            if not course.has_started and user_event_info.has_available_course_block:
                options["button"] = "book"
                options["post_button_text"] = mark_safe(
                    '<em>You have a course credit block available; you can switch your current class '
                    'bookings to a course booking if you wish. </em><br/>'
                    '<em>'
                    f'Payment plan available: Credit block - {user_event_info.available_course_block.block_config.name}'
                    '</em><br/>'
                )
        return options
    
    # full course; may still have drop in options
    if course.full:
        if course.allow_drop_in and not course.all_events_full:
            options["pre_button_text"] = "There are no spaces left for the full course. Drop-in is available for some classes."
            if user_event_info.has_available_drop_in_block:
                options["post_button_text"] = "You have an available drop-in payment plan"
        else:
            options["pre_button_text"] = "This course is full."
        return options
    
    if not course.has_started: 
        if user_event_info.has_available_course_block:
            # not started; show book button and available course block; don't show dropin options
            options["pre_button_text"] = mark_safe(
                f'<em>Payment plan available: Credit block - {user_event_info.available_course_block.block_config.name}</em>'
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
        if user_event_info.has_available_drop_in_block:
            options["post_button_text"] = "You have an available drop-in payment plan"
        else:
            options["post_button_text"] += f'''
            <em>To book drop in, add classes below, or go to the
            <a href="{purchase_url}">payment plans</a> page to see alternative payment options.</em>
            '''
            
    options["pre_button_text"] = mark_safe(options["pre_button_text"])
    options["post_button_text"] = mark_safe(options["post_button_text"])
    return options


# Courses list; book button for full course
def course_list_button_info(user, course, user_info):
    options = {"button": "", "text": ""}

    if user_info["has_booked_all"] and not user_info["items_in_basket"]:
        return {
            "button": "", 
            "text": mark_safe('<i class="text-success fas fa-check-circle"></i> Booked')
        }
    
    if user_info["items_in_basket"]:
        if not user_info["has_booked_all"]:
            options["text"] = f"<span class='float-right'>Item(s) in cart</span>"
        options["button"] = "view_cart"
        options["text"] = mark_safe(options["text"])

    if user_info["has_booked_dropin"]:
        if options["text"]:
            options["text"] += "<br/>"
        options["text"] += '<i class="text-success fas fa-check-circle"></i> Booked drop-in'
    if user_info["has_booked_dropin"] or user_info["items_in_basket"]:
        options["text"] = f"<span class='float-right'>{options['text']}</span>"
        if course.allow_drop_in and not course.all_events_full and not user_info["has_booked_all"]:
            options["text"] += "</br><span class='float-right'>See course details for other class availability.</span>"
        options["text"] = mark_safe(options["text"])
        return options

    if course.full:
        text = "Course is full."
        if course.allow_drop_in and not course.all_events_full:
            text += " Drop-in is available for some classes, see course details."
        return {"button": "", "text": text}
    if course.has_started:
        text = "Course has started"
        if course.allow_drop_in and not course.all_events_full:
            text += " Drop-in is available for some classes, see course details."
        return {"button": "", "text": text}

    # Not started and not already booked
    if has_available_course_block(user, course):
        options["button"] = "book"
        if course.allow_drop_in:
            options["text"] = "Course and drop-in booking is available, see course details."
        return options
    
    if add_to_cart_course_block_config(course):
        options["button"] = "add_course_to_basket"
    if course.allow_drop_in:
        options["text"] = "Drop-in booking is also available, see course details."
    return options


def booking_list_button(booking, history=False):
    options = {"button": "", "text": "", "styling": ""}
    if booking.event.cancelled:
        options["text"] = f"{booking.event.event_type.label.upper()} CANCELLED"
        options["styling"] = "cancelled"
        return options
    elif booking.status == "CANCELLED" or booking.no_show:
        options["text"] = "You have cancelled this booking."
        options["styling"] = "cancelled"

    if history:
        options["text"] = options["text"] or "Booked"
        return options

    if user_can_book_or_cancel(booking.event, booking):
        if can_cancel(booking):
            options["button"] = "toggle_booking"
            options["toggle_option"] = "cancel"
        elif can_rebook(booking, booking.event):
            # this is course no-shows only
            options["button"] = "toggle_booking"
            options["toggle_option"] = "rebook"
        elif can_book(booking, booking.event):
            if has_available_block(booking.user, booking.event) or has_available_subscription(booking.user, booking.event):
                options["button"] = "toggle_booking"
                options["toggle_option"] = "book"
            else:
                track_url = reverse("booking:events", args=(booking.event.event_type.track.slug,))
                options["text"] += f"</br>Go to <a href='{track_url}'>schedule</a> for booking options"
    elif booking.event.full:
        if booking.status == "CANCELLED" or booking.no_show:
            options["button"] = "waiting_list"
    elif booking.event.booking_restricted_pre_start():
        options["text"] = "Booking unavailable"
    
    options["text"] = mark_safe(options["text"])
    return options
