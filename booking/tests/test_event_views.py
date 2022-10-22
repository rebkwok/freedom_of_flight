from bs4 import BeautifulSoup
from model_bakery import baker
from datetime import timedelta

import pytest

from django.core.cache import cache
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from accounts.models import DataPrivacyPolicy, SignedDataPrivacy
from accounts.models import has_active_data_privacy_agreement

from booking.models import BlockConfig, Event, Booking, Track, WaitingListUser, add_to_cart_course_block_config, add_to_cart_drop_in_block_config
from common.test_utils import make_disclaimer_content, TestUsersMixin, EventTestMixin
from conftest import course


pytestmark = pytest.mark.django_db


class EventListViewTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse('booking:schedule')

    def setUp(self):
        self.create_users()
        self.create_test_setup()
        self.adult_url = reverse('booking:events', args=(self.adult_track.slug,))
        self.kids_url = reverse('booking:events', args=(self.kids_track.slug,))
        self.login(self.student_user)
        self.make_data_privacy_agreement(self.student_user)
        self.make_data_privacy_agreement(self.manager_user)

    def test_schedule_no_tracks(self):
        Track.objects.all().delete()
        self.client.logout()
        resp = self.client.get(self.url)
        assert resp.content.decode("utf-8") == "No tracks created yet."

    def test_schedule(self):
        """
        With no track, redirects to the default track
        """
        self.client.logout()
        resp = self.client.get(self.url)
        assert resp.status_code == 302
        assert resp.url == self.adult_url

        resp = self.client.get(self.url, follow=True)
        assert resp.context_data['page_events'].object_list.count() == 6
        assert "Log in</a>" in resp.rendered_content
        assert "register</a> to book</span>" in resp.rendered_content

    def test_event_list_logged_in_no_data_protection_policy(self):
        DataPrivacyPolicy.objects.all().delete()
        SignedDataPrivacy.objects.all().delete()
        assert has_active_data_privacy_agreement(self.student_user) is False
        resp = self.client.get(self.adult_url)
        assert resp.status_code == 200

        DataPrivacyPolicy.objects.create(content='Foo')
        cache.clear()
        resp = self.client.get(self.adult_url)
        assert resp.status_code == 302
        assert reverse('accounts:data_privacy_review') + '?next=/adults/' in resp.url

        self.make_data_privacy_agreement(self.student_user)
        resp = self.client.get(self.adult_url)
        assert resp.status_code == 200

    def test_event_list_past_event(self):
        """
        Test that past events is not listed
        """
        baker.make_recipe('booking.past_event', event_type=self.aerial_event_type)
        # check there are now 7 events
        assert Event.objects.filter(event_type__track=self.adult_track).count() == 7
        resp = self.client.get(self.adult_url)

        # event listing should still only show future events
        assert resp.context_data['page_events'].object_list.count() == 6

    def test_event_list_past_event_within_10_mins_is_listed(self):
        """
        Test that past events is not listed
        """
        past = baker.make_recipe(
            'booking.past_event', event_type=self.aerial_event_type, start=timezone.now() - timedelta(minutes=30)
        )
        # check there are now 7 events
        assert Event.objects.filter(event_type__track=self.adult_track).count() == 7
        resp = self.client.get(self.adult_url)

        # event listing should still only show future events
        assert resp.context_data['page_events'].object_list.count() == 6
        past.start = timezone.now() - timedelta(minutes=7)
        past.save()
        resp = self.client.get(self.adult_url)
        # event listing should shows future events plus pas within 10 mins
        assert resp.context_data['page_events'].object_list.count() == 7

    def test_event_list_with_anonymous_user(self):
        """
        Test that no booked_events in context
        """
        self.client.logout()
        resp = self.client.get(self.adult_url)
        assert 'user_booking_info' not in resp.context

        self.login(self.student_user)
        resp = self.client.get(self.adult_url)
        assert 'user_booking_info' in resp.context
    
    def test_event_list_name_filter(self):
        Event.objects.all().delete()
        baker.make_recipe("booking.future_event", event_type=self.aerial_event_type, _quantity=3, name="Hoop")
        baker.make_recipe("booking.future_event", event_type=self.aerial_event_type, _quantity=1, name="Silks")
        baker.make_recipe("booking.future_event", event_type=self.aerial_event_type, _quantity=2, name="silks")
        baker.make_recipe("booking.future_event", event_type=self.aerial_event_type, _quantity=4, name="Trapeze")
        
        resp = self.client.get(self.adult_url)
        # show all by default
        assert resp.context_data['page_events'].object_list.count() == 10
        
        # filter
        resp = self.client.get(self.adult_url + "?event_name=Hoop")
        assert resp.context_data['page_events'].object_list.count() == 3
        resp = self.client.get(self.adult_url + "?event_name=Trapeze")
        assert resp.context_data['page_events'].object_list.count() == 4

        # case insensitive
        resp = self.client.get(self.adult_url + "?event_name=silks")
        assert resp.context_data['page_events'].object_list.count() == 3
                
    def test_event_list_with_booked_events(self):
        """
        test that booked events are shown on listing
        """
        # create a booking for this user
        event = self.aerial_events[0]
        baker.make(Booking, user=self.student_user, event=event)
        resp = self.client.get(self.adult_url)
        button_options = resp.context_data['button_options']
        booked = [event_id for event_id, button_info in button_options.items() if button_info["has_open_booking"]]
        assert len(booked) == 1
        assert booked == [event.id]

    def test_event_list_with_booked_events_manager_user(self):
        """
        test that booked events are shown on listing
        """
        self.login(self.manager_user)
        # create a booking for the managed user
        event = self.kids_aerial_events[0]
        baker.make(Booking, user=self.child_user, event=event)
        resp = self.client.get(self.kids_url)
        # user is not a student, view as user set to child user
        button_options = resp.context_data['button_options']
        booked = [event_id for event_id, button_info in button_options.items() if button_info["has_open_booking"]]
        assert len(booked) == 1
        assert booked == [event.id]

    def test_event_list_booked_events_no_disclaimer(self):
        make_disclaimer_content()
        resp = self.client.get(self.adult_url)
        assert "Complete a disclaimer" in resp.rendered_content

    def test_event_list_user_booking_info(self):
        """
        test that booked events are shown on listing
        """
        self.make_disclaimer(self.student_user)
        for event in self.aerial_events:
            # create a paid booking for this user for all events
            baker.make(
                Booking, block__block_config__event_type=self.aerial_event_type,
                user=self.student_user, event=event, block__paid=True
            )

        resp = self.client.get(self.adult_url)
        user_booking_info = resp.context_data['user_booking_info']
 
        # user booking info for every track event
        # track events include aerial_events, floor_events, and one course event
        assert set(user_booking_info.keys()) == set(Event.objects.filter(event_type__track=self.adult_track).values_list("id", flat=True))
        assert set(list(user_booking_info.values())[0].keys()) == {"show_warning", "on_waiting_list"}

        # cancel button shown for the booked events
        assert 'Cancel' in resp.rendered_content

        # make all bookings unpaid
        for booking in Booking.objects.all():
            booking.block.paid = False
            booking.block.save()
        resp = self.client.get(self.adult_url)
        # No cancel buttons shown as all the booked events are unpaid
        assert 'Cancel' not in resp.rendered_content
        assert 'View cart' in resp.rendered_content

    def test_cancelled_events_are_not_listed(self):
        resp = self.client.get(self.adult_url)
        baker.make_recipe('booking.future_event', event_type=self.aerial_event_type, cancelled=True)
        assert Event.objects.filter(event_type__track=self.adult_track).count() == 7
        resp = self.client.get(self.adult_url)
        assert resp.context_data['page_events'].object_list.count() == 6

    def test_show_on_site_events_only_are_not_listed(self):
        baker.make_recipe('booking.future_event', event_type=self.aerial_event_type, show_on_site=False)
        assert Event.objects.filter(event_type__track=self.adult_track).count() == 7
        resp = self.client.get(self.adult_url)
        assert resp.context_data['page_events'].object_list.count() == 6

    def test_event_list_change_view_as_user(self):
        # manager is also a student
        self.make_disclaimer(self.manager_user)
        self.manager_user.userprofile.student = True
        self.manager_user.userprofile.save()
        self.make_disclaimer(self.child_user)
        self.login(self.manager_user)
        for event in self.aerial_events:
            # manager user booked for all events
            baker.make(Booking, user=self.manager_user, event=event)

        # manager is a student, so by default shows them as view_as_user
        resp = self.client.get(self.adult_url)
        button_options = resp.context_data['button_options']
        booked = [event_id for event_id, button_info in button_options.items() if button_info["has_open_booking"]]
        assert len(booked) == 2

        # post to change the user
        resp = self.client.post(self.adult_url, data={"view_as_user": self.child_user.id}, follow=True)
        assert self.client.session["user_id"] == self.child_user.id
        button_options = resp.context_data['button_options']
        booked = [event_id for event_id, button_info in button_options.items() if button_info["has_open_booking"]]
        assert not booked

    # def test_online_event_video_link(self):
    #     online_class = baker.make_recipe(
    #         'booking.future_CL', event_type__subtype="Online class", video_link="https://foo.test"
    #     )
    #     active_video_link_id = f"video_link_id_{online_class.id}"
    #     disabled_video_link_id = f"video_link_id_disabled_{online_class.id}"
    #
    #     url = reverse('booking:lessons')
    #
    #     # User is not booked, no links shown
    #     resp = self.client.get(url)
    #     assert active_video_link_id not in resp.rendered_content
    #     assert disabled_video_link_id not in resp.rendered_content
    #
    #     b ooking = baker.make_recipe("booking.booking", event=online_class, user=self.user)
    #     # User is booked but not paid, no links shown
    #     resp = self.client.get(url)
    #     assert active_video_link_id not in resp.rendered_content
    #     assert disabled_video_link_id not in resp.rendered_content
    #
    #     # User is booked and paid but class is more than 20 mins ahead
    #     booking.paid = True
    #     booking.save()
    #     resp = self.client.get(url)
    #     assert active_video_link_id not in resp.rendered_content
    #     assert disabled_video_link_id in resp.rendered_content
    #
    #     # User is booked and paid, class is less than 20 mins ahead
    #     online_class.date = timezone.now() + timedelta(minutes=10)
    #     online_class.save()
    #     resp = self.client.get(url)
    #     assert active_video_link_id in resp.rendered_content
    #     assert disabled_video_link_id not in resp.rendered_content
    #
    #     # User is no show
    #     booking.no_show = True
    #     booking.save()
    #     resp = self.client.get(url)
    #     assert active_video_link_id not in resp.rendered_content
    #     assert disabled_video_link_id not in resp.rendered_content
    #
    #     # user has cancelled
    #     booking.no_show = False
    #     booking.status = "CANCELLED"
    #     booking.save()
    #     resp = self.client.get(url)
    #     assert active_video_link_id not in resp.rendered_content
    #     assert disabled_video_link_id not in resp.rendered_content


class EventDetailViewTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def setUp(self):
        self.create_users()
        self.create_events_and_course()
        self.event = self.aerial_events[0]
        self.login(self.student_user)
        self.make_data_privacy_agreement(self.student_user)
        self.make_data_privacy_agreement(self.manager_user)

    def test_get(self):
        url = reverse('booking:event', args=[self.event.slug])
        resp = self.client.get(url)
        assert resp.status_code == 200

    def test_with_booked_event(self):
        """
        Test that booked event is shown as booked
        """
        #create a booking for this event and user
        url = reverse('booking:event', args=[self.event.slug])
        baker.make(Booking, event=self.event, user=self.student_user)
        resp = self.client.get(url)
        assert "You have booked for this class" in resp.rendered_content

    def test_with_booked_event_for_managed_user(self):
        #create a booking for this event and user
        self.login(self.manager_user)
        url = reverse('booking:event', args=[self.event.slug])
        baker.make(Booking, event=self.event, user=self.child_user)
        resp = self.client.get(url)
        assert f"{self.child_user.first_name} {self.child_user.last_name} has booked for this class" in resp.rendered_content


class CourseEventsListViewTests(EventTestMixin, TestUsersMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.create_cls_tracks_and_event_types()

    def setUp(self):
        self.create_users()
        self.login(self.student_user)
        self.create_events_and_course()
        self.course_event1 = baker.make_recipe(
            "booking.future_event", event_type=self.aerial_event_type, course=self.course
        )
        self.url = reverse("booking:course_events", args=(self.course.slug,))

        self.make_data_privacy_agreement(self.student_user)
        self.make_data_privacy_agreement(self.manager_user)

    def test_course_list(self):
        resp = self.client.get(self.url)
        # course events are displayed
        response_events = resp.context_data['page_events'].object_list
        assert response_events.count() == 2
        for event in response_events:
            assert event.course == self.course

    def test_course_list_shows_past_events(self):
        baker.make_recipe(
            "booking.past_event", event_type=self.aerial_event_type, course=self.course
        )
        resp = self.client.get(self.url)
        # course events are displayed
        assert resp.context_data['page_events'].object_list.count() == 3

    def test_course_list_with_booked_course(self):
        baker.make(Booking, event=self.course_event, user=self.student_user, block__paid=True)
        baker.make(Booking, event=self.course_event1, user=self.student_user, block__paid=True)
        resp = self.client.get(self.url)
        assert resp.context_data["book_course_button_options"]["pre_button_text"] == "Student User is attending this course."
    
    def test_course_list_with_booked_course_unenroll(self):
        booking = baker.make(Booking, event=self.course_event, user=self.student_user, block__paid=True)
        booking1 = baker.make(Booking, event=self.course_event1, user=self.student_user, block__paid=True)
        resp = self.client.get(self.url)
        assert resp.context_data["book_course_button_options"]["button"] == "unenroll"

        for bk in [booking, booking1]:
            bk.date_booked = timezone.now() - timedelta(hours=26)
            bk.save()
        resp = self.client.get(self.url)
        assert resp.context_data["book_course_button_options"]["button"] is None

        for bk in [booking, booking1]:
            bk.date_booked = timezone.now()
            bk.save()
        resp = self.client.get(self.url)
        assert resp.context_data["book_course_button_options"]["button"] == "unenroll"

        self.course_event.start = timezone.now() - timedelta(hours=2)
        self.course_event.save()
        self.course.refresh_from_db()
        assert self.course.has_started
        resp = self.client.get(self.url)
        assert resp.context_data["book_course_button_options"]["button"] is None

    def test_course_list_with_booked_events_manager_user(self):
        """
        test that booked events are shown on listing
        """
        self.login(self.manager_user)
        resp = self.client.get(self.url)
        # user is not a student, view as user set to child user
        assert "Complete a disclaimer" in resp.rendered_content

        resp = self.client.get(self.url)
        self.make_disclaimer(self.child_user)
        # check there are no booked events yet
        assert resp.context_data["book_course_button_options"]["button"] is None

        # create a booking for the managed user
        baker.make(Booking, event=self.course_event, user=self.child_user, block__paid=True)
        baker.make(Booking, event=self.course_event1, user=self.child_user, block__paid=True)
        resp = self.client.get(self.url)
        # booking just made, can unenroll
        assert resp.context_data["book_course_button_options"]["button"] == "unenroll"



###### EventsListView Buttons ##########

def _get_buttons(client, event):
    url = reverse('booking:events', args=(event.event_type.track.slug,))
    response = client.get(url)
    soup = BeautifulSoup(response.rendered_content, features="html.parser")
    return {
        "button_text": soup.find(id=f"button_text_{event.id}"),
        "toggle_booking": soup.find(id=f"book_{event.id}"),
        "book_course": soup.find(id=f"book_course_event_{event.id}"),
        "unenroll_course_from_event": soup.find(id=f"unenroll_course_from_event_{event.id}"),
        "add_event": soup.find(id=f"add_to_basket_{event.id}"),
        "add_course": soup.find(id=f"add_course_to_basket_{event.id}"),
        "payment_options":  soup.find(id=f"payment_options_{event.id}"),
        "waiting_list":  soup.find(id=f"waiting_list_button_{event.id}"),
        "view_cart":  soup.find(id=f"view_cart_{event.id}"),
    }


def test_event_button_dropin_event_no_disclaimer(client, student_user, event):
    student_user.online_disclaimer.all().delete()
    client.force_login(student_user)
    url = reverse('booking:events', args=(event.event_type.track.slug,))
    resp = client.get(url)
    assert resp.context_data['page_events'].object_list.count() == 1
    assert "Complete a disclaimer" in resp.rendered_content


def test_event_button_dropin_event(client, student_user, event):
    client.force_login(student_user)
    buttons = _get_buttons(client, event)
    for button in ["toggle_booking", "add_course", "waiting_list", "book_course", "unenroll_course_from_event"]:
        assert buttons[button] is None
    assert "Add drop-in" in buttons["add_event"].text
    assert "Payment Plans" in buttons["payment_options"].text 
    assert buttons["button_text"].text == ""


def test_event_button_dropin_event_cancelled(client, student_user, event, booking, dropin_block):
    booking.status = "CANCELLED"
    booking.save()
    client.force_login(student_user)

    # block available
    buttons = _get_buttons(client, event)
    for button in ["add_event", "add_course", "waiting_list", "payment_options", "book_course", "unenroll_course_from_event"]:
        assert buttons[button] is None
    assert "Book Drop-in" in buttons["toggle_booking"].text
    assert buttons["button_text"].text == ""
     
    # block not available
    dropin_block.delete()
    buttons = _get_buttons(client, event)
    for button in ["toggle_booking", "add_course", "waiting_list", "book_course", "unenroll_course_from_event"]:
        assert buttons[button] is None
    assert "Add drop-in" in buttons["add_event"].text
    assert "Payment Plans" in buttons["payment_options"].text 
    assert buttons["button_text"].text == ""


def test_event_button_dropin_event_available_block(client, student_user, event, dropin_block):
    client.force_login(student_user)
    buttons = _get_buttons(client, event)
    for button in ["add_event", "add_course", "waiting_list", "payment_options", "book_course", "unenroll_course_from_event"]:
        assert buttons[button] is None
    assert "Book Drop-in" in buttons["toggle_booking"].text
    assert buttons["button_text"].text == ""

  
def test_event_button_dropin_event_available_block_booking_restricted(
      client, student_user, event, dropin_block
    ):
    client.force_login(student_user)
    event.start = timezone.now() + timedelta(minutes=10)
    event.save()
    buttons = _get_buttons(client, event)
    for button in ["add_event", "add_course", "waiting_list", "payment_options", "toggle_booking", "book_course", "unenroll_course_from_event"]:
        assert buttons[button] is None
    assert "Unavailable 15 mins before start" in buttons["button_text"].text


def test_event_button_dropin_event_no_show(client, student_user, event, booking):
    booking.no_show = True
    booking.save()
    client.force_login(student_user)

    # block is still used for no-show, full
    buttons = _get_buttons(client, event)
    for button in ["toggle_booking", "add_course", "waiting_list", "book_course", "unenroll_course_from_event"]:
        assert buttons[button] is None
    assert "Add drop-in" in buttons["add_event"].text
    assert "Payment Plans" in buttons["payment_options"].text 
    assert buttons["button_text"].text == ""


def test_event_button_dropin_event_full(client, student_user, event):
    baker.make(Booking, event=event, _quantity=2)
    client.force_login(student_user)

    # block is still used for no-show, full
    buttons = _get_buttons(client, event)
    for button in ["add_event", "add_course", "toggle_booking", "payment_options", "book_course", "unenroll_course_from_event"]:
        assert buttons[button] is None
    assert "Join waiting list" in buttons["waiting_list"].text
    assert buttons["button_text"].text == "Class is full"

    # on waiting list
    baker.make(WaitingListUser, event=event, user=student_user)
    buttons = _get_buttons(client, event)
    for button in ["add_event", "add_course", "toggle_booking", "payment_options", "book_course", "unenroll_course_from_event"]:
        assert buttons[button] is None
    assert "Leave waiting list" in buttons["waiting_list"].text
    assert buttons["button_text"].text == "Class is full"


def test_event_button_dropin_event_full_with_booking(client, student_user, event, booking):
    baker.make(Booking, event=event)
    client.force_login(student_user)

    # block is still used for no-show, full
    buttons = _get_buttons(client, event)
    for button in ["add_event", "add_course", "waiting_list", "payment_options", "book_course", "unenroll_course_from_event"]:
        assert buttons[button] is None
    assert "Cancel" in buttons["toggle_booking"].text
    assert buttons["button_text"].text == ""


def test_event_button_course_event(client, student_user, course):
    client.force_login(student_user)
    buttons = _get_buttons(client, course.uncancelled_events.first())
    for button in ["toggle_booking", "add_event", "waiting_list", "book_course", "unenroll_course_from_event"]:
        assert buttons[button] is None

    assert "Add course" in buttons["add_course"].text
    assert "Payment Plans" in buttons["payment_options"].text 
    assert buttons["button_text"].text == ""


def test_event_button_course_event_config_inactive(client, student_user, course, course_cart_block_config):
    course_cart_block_config.active = False
    course_cart_block_config.save()
    client.force_login(student_user)
    buttons = _get_buttons(client, course.events.first())
    for button in ["toggle_booking", "add_event", "waiting_list", "book_course", "unenroll_course_from_event"]:
        assert buttons[button] is None
    assert "Add course" in buttons["add_course"].text
    # block config is inactive, so no Payment Plans to show
    assert buttons["payment_options"] is None
    assert buttons["button_text"].text == ""


def test_event_button_course_event_valid_block(client, student_user, course, course_block):
    client.force_login(student_user)
    buttons = _get_buttons(client, course.events.first())
    for button in ["toggle_booking", "add_event", "add_course", "waiting_list", "unenroll_course_from_event"]:
        assert buttons[button] is None
    assert "Payment Plans" in buttons["payment_options"].text
    assert "Book course" in buttons["book_course"].text


def test_event_button_course_event_full_valid_block(client, student_user, course, course_block):
    for event in course.uncancelled_events:
        baker.make(Booking, event=event, _quantity=2)
    client.force_login(student_user)
    buttons = _get_buttons(client, course.events.first())
    for button in ["toggle_booking", "add_event", "add_course", "payment_options", "book_course", "unenroll_course_from_event"]:
        assert buttons[button] is None
    assert "Join waiting list" in buttons["waiting_list"].text
    assert buttons["button_text"].text == "Class is full"


def test_event_button_course_event_no_show(client, student_user, course, course_bookings):
    for booking in course_bookings:
        booking.no_show = True
        booking.save()
    client.force_login(student_user)
    buttons = _get_buttons(client, course.events.first())
    for button in ["add_event", "add_course", "payment_options", "waiting_list", "book_course", "unenroll_course_from_event"]:
        assert buttons[button] is None
    assert "Rebook" in buttons["toggle_booking"].text
    assert buttons["button_text"].text == ""
     

def test_event_button_course_event_full_has_booking(client, student_user, course, course_bookings):
    for event in course.uncancelled_events:
        baker.make(Booking, event=event)
    client.force_login(student_user)
    buttons = _get_buttons(client, course.events.first())
    for button in ["add_event", "add_course", "payment_options", "waiting_list", "book_course"  ]:
        assert buttons[button] is None
    assert buttons["unenroll_course_from_event"] is not None
    assert "Cancel" in buttons["toggle_booking"].text
    assert buttons["button_text"].text == ""


###### CourseEventsListView Buttons ##########

def _get_book_course_buttons(client, course, event=None):
    response = client.get(reverse("booking:course_events", args=(course.slug,)))
    soup = BeautifulSoup(response.rendered_content, features="html.parser")
    book_course_button = {
        "pre_text": soup.find(id="course_button_pre_text"),
        "post_text": soup.find(id="course_button_post_text"),
        "book_button": soup.find(id=f"book_course_{course.id}"),
        "unenroll": soup.find(id="unenroll"),
    }
    
    for button_key in book_course_button:
        if book_course_button[button_key]:
            book_course_button[button_key] = book_course_button[button_key].text.replace("\n", "").strip()

    event = event or course.uncancelled_events.first()    
    event_buttons = {
        "button_text": soup.find(id=f"button_text_{event.id}"),
        "toggle_booking": soup.find(id=f"book_{event.id}"),
        "book_course": soup.find(id=f"book_course_event_{event.id}"),
        "unenroll_course_from_event": soup.find(id=f"unenroll_course_from_event_{event.id}"),
        "add_event": soup.find(id=f"add_to_basket_{event.id}"),
        "add_course": soup.find(id=f"add_course_to_basket_{event.id}"),
        "payment_options": soup.find(id=f"payment_options_{event.id}"),
        "waiting_list": soup.find(id=f"waiting_list_button_{event.id}"),
        "view_cart": soup.find(id=f"view_cart_{event.id}"),
    }

    for button_key in event_buttons:
        if event_buttons[button_key] is not None:
            event_buttons[button_key] = event_buttons[button_key].text.replace("\n", "").strip()
    
    return book_course_button, event_buttons


###### CourseEventsListView button options for DROP-IN NOT ALLOWED COURSE

def test_buttons_course_no_disclaimer(client, student_user, course):
    student_user.online_disclaimer.all().delete()
    client.force_login(student_user)
    resp = client.get(reverse("booking:course_events", args=(course.slug,)))
    assert resp.context_data['page_events'].object_list.count() == 2
    assert "Complete a disclaimer" in resp.rendered_content


def test_buttons_course_not_booked_no_purchaseable_block_configs(client, student_user, course, course_cart_block_config):
    course_cart_block_config.active = False
    course_cart_block_config.save()
    client.force_login(student_user)
    course_button, event_buttons = _get_book_course_buttons(client, course)
    assert course_button["book_button"] is None
    assert not course_button["unenroll"]
    assert course_button["pre_text"] == ""
    assert course_button["post_text"] == ""

    for button in [
            "toggle_booking", 
            "book_course", 
            "unenroll_course_from_event",
            "waiting_list",
            "add_event", # dropin not allowed
            "payment_options", # no purchaseable blocks
            "view_cart"
        ]:
        assert event_buttons[button] is None, button
    for button in ["add_course"]:
        assert event_buttons[button] is not None, button
    assert event_buttons["button_text"] == ""


def test_buttons_course_not_booked_no_valid_block_configs(client, student_user, course, course_cart_block_config):
    course_cart_block_config.delete()
    client.force_login(student_user)
    course_button, event_buttons = _get_book_course_buttons(client, course)
    assert course_button["book_button"] is None
    assert not course_button["unenroll"]
    assert course_button["pre_text"] == ""
    assert course_button["post_text"] == ""

    for button in [
            "toggle_booking", 
            "book_course", 
            "unenroll_course_from_event",
            "waiting_list",
            "add_event",
            "add_course", 
            "payment_options",
            "view_cart",
        ]:
        assert event_buttons[button] is None, button
    assert event_buttons["button_text"] == ""


def test_buttons_course_not_booked_with_purchaseable_block_configs(client, student_user, course, course_cart_block_config):
    client.force_login(student_user)
    course_button, event_buttons = _get_book_course_buttons(client, course)
    assert course_button["book_button"] is None
    assert not course_button["unenroll"]
    assert course_button["pre_text"] == ""
    assert course_button["post_text"] == ""

    for button in [
        "toggle_booking", 
        "book_course", 
        "unenroll_course_from_event",
        "waiting_list",
        "add_event", # dropin not allowed
        "view_cart"
    ]:
        assert event_buttons[button] is None, button
    
    for button in ["add_course", "payment_options"]:
        assert event_buttons[button] is not None, button
    assert event_buttons["button_text"] == ""


def test_buttons_course_cancelled_booking(client, student_user, course, booking):
    booking.event = course.uncancelled_events.first()
    booking.status = "CANCELLED"
    booking.save()
    client.force_login(student_user)
    course_button, event_buttons = _get_book_course_buttons(client, course)

    assert course_button["book_button"] is None
    assert not course_button["unenroll"]
    assert course_button["pre_text"] == ""
    assert course_button["post_text"] == ""
    for button in [
        "toggle_booking", 
        "book_course", 
        "unenroll_course_from_event",
        "waiting_list",
        "add_event", # dropin not allowed
        "view_cart"
    ]:
        assert event_buttons[button] is None, button
    for button in ["add_course", "payment_options"]:
        assert event_buttons[button] is not None, button
    
    assert event_buttons["button_text"] == ""


def test_buttons_course_not_booked_block_available(client, student_user, course, course_block):
    client.force_login(student_user)
    course_button, event_buttons = _get_book_course_buttons(client, course)
    assert "Book Course" in course_button["book_button"]
    assert not course_button["unenroll"]
    assert "Payment plan available" in course_button["pre_text"]
    assert course_button["post_text"] == ""

    for button in [
        "toggle_booking", 
        "add_course", 
        "unenroll_course_from_event",
        "waiting_list",
        "add_event", # dropin not allowed
        "view_cart"
    ]:
        assert event_buttons[button] is None, button
    
    for button in ["book_course", "payment_options"]:
        assert event_buttons[button] is not None, button
    assert event_buttons["button_text"] == ""


def test_buttons_course_cancelled_booking_block_available(client, student_user, course, booking, course_block):
    booking.event = course.uncancelled_events.first()
    booking.status = "CANCELLED"
    booking.save()
    client.force_login(student_user)
    course_button, event_buttons = _get_book_course_buttons(client, course)

    assert "Book Course" in course_button["book_button"]
    assert not course_button["unenroll"]
    assert "Payment plan available" in course_button["pre_text"]
    assert course_button["post_text"] == ""
    for button in [
        "toggle_booking", 
        "add_course", 
        "unenroll_course_from_event",
        "waiting_list",
        "add_event", # dropin not allowed
        "view_cart"
    ]:
        assert event_buttons[button] is None, button
    
    for button in ["book_course", "payment_options"]:
        assert event_buttons[button] is not None, button
    assert event_buttons["button_text"] == ""


def test_buttons_course_no_show_booking_block_available(client, student_user, course, course_bookings):
    for booking in course_bookings:
        booking.no_show = True
        booking.save()
    client.force_login(student_user)
    course_button, event_buttons = _get_book_course_buttons(client, course)

    assert course_button["book_button"] is None
    assert course_button["unenroll"] == ""  # unenroll is a form, no text == ""
    assert "Student User is attending this course" in course_button["pre_text"]
    assert "You can reschedule your course" in course_button["post_text"]

    for button in [
        "add_course", 
        "book_course",
        "waiting_list",
        "payment_options",
        "add_event", # dropin not allowed
        "unenroll_course_from_event", # not shown for event b/c cancelled so show rebook
        "view_cart"
    ]:
        assert event_buttons[button] is None, button
    for button in ["toggle_booking"]:
        assert event_buttons[button] is not None, button
    
    assert event_buttons["toggle_booking"] == "Rebook"
    assert event_buttons["button_text"] == ""


def test_buttons_course_full(client, student_user, course):
    for event in course.uncancelled_events:
        baker.make(Booking, event=event, _quantity=2)
    client.force_login(student_user)
    course_button, event_buttons = _get_book_course_buttons(client, course)
    assert course_button["book_button"] is None
    assert not course_button["unenroll"]
    assert "This course is full" in course_button["pre_text"]
    assert course_button["post_text"] == ""
    for button in [
        "add_course", 
        "book_course",
        "unenroll_course_from_event",
        "payment_options",
        "add_event", # dropin not allowed
        "toggle_booking",
        "view_cart"
    ]:
        assert event_buttons[button] is None, button
    assert event_buttons["waiting_list"] == "Join waiting list"
    assert event_buttons["button_text"] == "Class is full"

    # on waiting list
    baker.make(WaitingListUser, event=course.uncancelled_events.first(), user=student_user)
    course_button, event_buttons = _get_book_course_buttons(client, course)
    assert course_button["book_button"] is None
    assert not course_button["unenroll"]
    assert "This course is full" in course_button["pre_text"]
    assert course_button["post_text"] == ""
    assert event_buttons["waiting_list"] == "Leave waiting list"


def test_buttons_course_full_has_booking(client, student_user, course, course_bookings):
    for event in course.uncancelled_events:
        baker.make(Booking, event=event)
    client.force_login(student_user)
    course_button, event_buttons = _get_book_course_buttons(client, course)

    assert course_button["book_button"] is None
    assert course_button["unenroll"] == ""  # unenroll is a form, no text
    assert "Student User is attending this course" in course_button["pre_text"]
    assert "You can reschedule your course" in course_button["post_text"]
    for button in [
        "add_course", 
        "book_course",
        "payment_options",
        "add_event", # dropin not allowed
        "waiting_list",
        "view_cart"
    ]:
        assert event_buttons[button] is None, button
    
    assert event_buttons["toggle_booking"] == "Cancel"
    assert event_buttons["unenroll_course_from_event"] is not None
    assert event_buttons["button_text"] == ""


def test_buttons_course_booking_made_more_than_24hrs_ago(
    client, student_user, course, course_bookings
):
    for booking in course_bookings:
        booking.date_booked = timezone.now() - timedelta(hours=25)
        booking.save()
    client.force_login(student_user)
    course_button, event_buttons = _get_book_course_buttons(client, course)

    assert course_button["book_button"] is None
    assert not course_button["unenroll"]
    assert "Student User is attending this course" in course_button["pre_text"]
    assert course_button["post_text"] == ""
    assert event_buttons["unenroll_course_from_event"] is None


def test_buttons_course_course_started_block_available(
    client, student_user, course, course_block
):  
    ev = course.uncancelled_events.first()
    ev.start = timezone.now() - timedelta(1)
    ev.save()
    course.refresh_from_db()
    assert course.has_started

    client.force_login(student_user)
    course_button, event_buttons = _get_book_course_buttons(client, course, course.uncancelled_events.last())

    assert course_button["book_button"] is None
    assert not course_button["unenroll"]
    assert "This course has started" in course_button["pre_text"]
    assert course_button["post_text"] == ""
    
    for button, button_text in event_buttons.items():
        if button != "button_text":
            assert button_text is None, button
        else:
            assert button_text == "Course has started"

    # get the event buttons for the first event (past)
    course_button, event_buttons = _get_book_course_buttons(client, course)
    assert "This course has started" in course_button["pre_text"]
    assert event_buttons["button_text"] == "Class is past"


###### CourseEventsListView button options for DROP-IN ALLOWED COURSE

def test_buttons_dropin_course_no_disclaimer(client, student_user, drop_in_course):
    student_user.online_disclaimer.all().delete()
    client.force_login(student_user)
    resp = client.get(reverse("booking:course_events", args=(drop_in_course.slug,)))
    assert resp.context_data['page_events'].object_list.count() == 2
    assert "Complete a disclaimer" in resp.rendered_content


def test_buttons_dropin_course_not_booked(client, student_user, drop_in_course):
    client.force_login(student_user)
    course_button, event_buttons = _get_book_course_buttons(client, drop_in_course)
    assert course_button["book_button"] is None
    assert not course_button["unenroll"]
    assert "You can book the full course or drop in" in course_button["pre_text"]
    assert "To book drop in, add classes" in course_button["post_text"]
    for button in [
        "book_course",
        "toggle_booking",
        "view_cart"
    ]:
        assert event_buttons[button] is None, button
    
    for button in [
        "add_course",
        "add_event",
        "payment_options",
    ]:
        assert event_buttons[button] is not None, button
    assert event_buttons["button_text"] == ""


def test_buttons_dropin_course_cancelled_no_block(client, student_user, drop_in_course, booking):
    booking.event = drop_in_course.uncancelled_events[0]
    booking.status = "CANCELLED"
    booking.save()
    client.force_login(student_user)
    course_button, event_buttons = _get_book_course_buttons(client, drop_in_course)
    assert course_button["book_button"] is None
    assert not course_button["unenroll"]
    assert "You can book the full course or drop in" in course_button["pre_text"]
    assert "To book drop in, add classes" in course_button["post_text"]
    for button in [
        "book_course",
        "toggle_booking",
        "view_cart"
    ]:
        assert event_buttons[button] is None, button
    
    for button in [
        "add_course",
        "add_event",
        "payment_options",
    ]:
        assert event_buttons[button] is not None, button
    assert event_buttons["button_text"] == ""


def test_buttons_dropin_course_not_booked_with_course_block(client, student_user, drop_in_course, course_block):
    client.force_login(student_user)
    course_button, event_buttons = _get_book_course_buttons(client, drop_in_course)

    assert "Book Course" in course_button["book_button"]
    assert not course_button["unenroll"]
    assert "You can book the full course or drop in" in course_button["pre_text"]
    assert "To book drop in, add classes" in course_button["post_text"]
    for button in [
        "add_course",
        "toggle_booking",
        "view_cart"
    ]:
        assert event_buttons[button] is None, button
    
    for button in [
        "book_course",
        "add_event",
        "payment_options",
    ]:
        assert event_buttons[button] is not None, button
    assert event_buttons["button_text"] == ""


def test_buttons_dropin_course_not_booked_with_course_and_dropin_block(client, student_user, drop_in_course, course_block, dropin_block):
    client.force_login(student_user)
    course_button, event_buttons = _get_book_course_buttons(client, drop_in_course)

    assert "Book Course" in course_button["book_button"]
    assert not course_button["unenroll"]
    assert "You can book the full course or drop in" in course_button["pre_text"]
    assert "You have an available drop-in payment plan" in course_button["post_text"]
    for button in [
        "add_course",
        "add_event",
        "view_cart"
    ]:
        assert event_buttons[button] is None, button
    
    for button in [
        "book_course",
        "toggle_booking",
        "payment_options",
    ]:
        assert event_buttons[button] is not None, button
    assert event_buttons["toggle_booking"] == "Book Drop-in"
    assert event_buttons["button_text"] == ""


def test_buttons_dropin_course_not_booked_with_dropin_block(client, student_user, drop_in_course, dropin_block):
    client.force_login(student_user)
    course_button, event_buttons = _get_book_course_buttons(client, drop_in_course)

    assert course_button["book_button"] is None
    assert not course_button["unenroll"]
    assert "You can book the full course or drop in" in course_button["pre_text"]
    assert "You have an available drop-in payment plan" in course_button["post_text"]
    for button in [
        "book_course",
        "add_event",
        "view_cart"
    ]:
        assert event_buttons[button] is None, button
    for button in [
        "add_course",
        "toggle_booking",
        "payment_options",
    ]:
        assert event_buttons[button] is not None, button
    
    assert event_buttons["toggle_booking"] == "Book Drop-in"
    assert event_buttons["button_text"] == ""


def test_buttons_dropin_course_cancelled_with_dropin_block(client, student_user, drop_in_course, dropin_block, booking):
    client.force_login(student_user)
    booking.event = drop_in_course.uncancelled_events.first()
    booking.block = None
    booking.status = "CANCELLED"
    booking.save()
    course_button, event_buttons = _get_book_course_buttons(client, drop_in_course)
    assert course_button["book_button"] is None
    assert not course_button["unenroll"]
    assert "You can book the full course or drop in" in course_button["pre_text"]
    assert "You have an available drop-in payment plan" in course_button["post_text"]
    for button in [
        "book_course",
        "add_event",
        "view_cart"
    ]:
        assert event_buttons[button] is None, button
    
    for button in [
        "add_course",
        "toggle_booking",
        "payment_options",
    ]:
        assert event_buttons[button] is not None, button
    assert event_buttons["toggle_booking"] == "Book Drop-in"
    assert event_buttons["button_text"] == ""


def test_buttons_dropin_course_no_show_with_course_block(client, student_user, drop_in_course, drop_in_course_bookings):
    client.force_login(student_user)
    booking = drop_in_course_bookings.first()
    booking.no_show = True
    booking.save()
    course_button, event_buttons = _get_book_course_buttons(client, drop_in_course)

    assert course_button["book_button"] is None
    assert course_button["unenroll"] == ""  # unenroll is a form, no text
    assert "Student User is attending this course" in course_button["pre_text"]
    assert "You can reschedule" in course_button["post_text"]
    for button in [
        "book_course",
        "add_course",
        "add_event",
        "payment_options",
        "view_cart"
    ]:
        assert event_buttons[button] is None, button
    
    assert event_buttons["toggle_booking"] == "Rebook"
    assert event_buttons["button_text"] == ""


def test_buttons_dropin_course_event_full(client, student_user, drop_in_course):
    client.force_login(student_user)
    for event in drop_in_course.uncancelled_events:
        baker.make(Booking, event=event, _quantity=2)
    drop_in_course.refresh_from_db()
    assert drop_in_course.full
    course_button, event_buttons = _get_book_course_buttons(client, drop_in_course)

    assert course_button["book_button"] is None
    assert not course_button["unenroll"]
    assert "This course is full" in course_button["pre_text"]
    assert course_button["post_text"] == ""


def test_buttons_dropin_course_booked_dropin_event_full(client, student_user, drop_in_course, booking):
    client.force_login(student_user)
    booking.event = drop_in_course.uncancelled_events.first()
    booking.save()
    baker.make(Booking, event=drop_in_course.uncancelled_events[1], _quantity=2)
    drop_in_course.refresh_from_db()
    assert drop_in_course.full

    course_button, event_buttons = _get_book_course_buttons(client, drop_in_course)
    assert course_button["book_button"] is None
    assert course_button["unenroll"] is None
    assert "Student User has booked for classes on this course." in course_button["pre_text"]
    assert course_button["post_text"] == ""
    for button in [
        "book_course",
        "add_course",
        "add_event",
        "payment_options",
        "view_cart"
    ]:
        assert event_buttons[button] is None, button
    
    assert event_buttons["toggle_booking"] == "Cancel"
    assert event_buttons["button_text"] == ""


def test_buttons_dropin_course_booked_dropin_event_course_block_available(
    client, student_user, drop_in_course, booking, course_block
):
    client.force_login(student_user)
    booking.event = drop_in_course.uncancelled_events.first()
    booking.save()

    course_button, event_buttons = _get_book_course_buttons(client, drop_in_course)
    assert course_button["book_button"] == "Book Course"
    assert course_button["unenroll"] is None
    assert "Student User has booked for classes on this course." in course_button["pre_text"]
    assert "You have a course credit block available" in course_button["post_text"]
    for button in [
        "book_course",
        "add_course",
        "add_event",
        "payment_options",
        "view_cart"
    ]:
        assert event_buttons[button] is None, button
    
    assert event_buttons["toggle_booking"] == "Cancel"
    assert event_buttons["button_text"] == ""


def test_buttons_dropin_course_in_basket(
    client, student_user, drop_in_course, booking, course_block, drop_in_course_bookings
):
    client.force_login(student_user)
    course_block.paid = False
    course_block.save()

    course_button, event_buttons = _get_book_course_buttons(client, drop_in_course)
    assert course_button["book_button"] is None
    assert course_button["unenroll"] is None
    assert "Booking is provisionally held pending payment." in course_button["pre_text"]
    assert course_button["post_text"] == ""
    for button in [
        "book_course",
        "add_course",
        "add_event",
        "payment_options",
        "toggle_booking"
    ]:
        assert event_buttons[button] is None, button
    # view cart button is always present but hidden if necessary
    assert "View cart" in event_buttons["view_cart"]
    assert event_buttons["button_text"] == "In cart"


def test_buttons_dropin_course_full_for_one_event(client, student_user, drop_in_course, dropin_block):
    # course full for one event (i.e. entire course full), but space on another event
    # dropin allowed, no block available
    client.force_login(student_user)
    baker.make(Booking, event=drop_in_course.uncancelled_events[1], _quantity=2)
    drop_in_course.refresh_from_db()
    assert drop_in_course.full

    # dropin block available
    course_button, _ = _get_book_course_buttons(client, drop_in_course)
    assert course_button["book_button"] is None
    assert course_button["pre_text"] == "There are no spaces left for the full course. Drop-in is available for some classes."
    assert course_button["post_text"] == "You have an available drop-in payment plan"

    dropin_block.delete()
    # dropin block not available
    course_button, _ = _get_book_course_buttons(client, drop_in_course)
    assert course_button["book_button"] is None
    assert course_button["pre_text"] == "There are no spaces left for the full course. Drop-in is available for some classes."
    assert course_button["post_text"] == ""


def test_buttons_dropin_course_started(client, student_user, drop_in_course):
    ev = drop_in_course.uncancelled_events.first()
    ev.start = timezone.now() - timedelta(3)
    ev.save()
    client.force_login(student_user)

    drop_in_course.refresh_from_db()
    drop_in_course.has_started
    course_button, _ = _get_book_course_buttons(client, drop_in_course)
    assert "This course has started" in course_button["pre_text"]
    assert "You can book individual classes on this course as drop in" in course_button["pre_text"]


def test_buttons_dropin_course_started_block_available(client, student_user, drop_in_course, dropin_block):
    ev = drop_in_course.uncancelled_events.first()
    ev.start = timezone.now() - timedelta(3)
    ev.save()
    client.force_login(student_user)

    drop_in_course.refresh_from_db()
    drop_in_course.has_started
    course_button, _ = _get_book_course_buttons(client, drop_in_course)
    assert "This course has started" in course_button["pre_text"]
    assert "You can book individual classes on this course as drop in" in course_button["pre_text"]
    assert course_button["post_text"] == "You have an available drop-in payment plan"
