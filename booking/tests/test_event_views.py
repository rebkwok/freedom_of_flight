from bs4 import BeautifulSoup
from model_bakery import baker
from datetime import timedelta

from django.core.cache import cache
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from accounts.models import DataPrivacyPolicy, SignedDataPrivacy
from accounts.models import has_active_data_privacy_agreement

from booking.models import BlockConfig, Event, Booking, Track, WaitingListUser, add_to_cart_course_block_config, add_to_cart_drop_in_block_config
from common.test_utils import make_disclaimer_content, TestUsersMixin, EventTestMixin


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

    def _get_buttons(self, event, url=None):
        url = url or self.adult_url
        response = self.client.get(url)
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
        }

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
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 6
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
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 6

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
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 6
        past.start = timezone.now() - timedelta(minutes=7)
        past.save()
        resp = self.client.get(self.adult_url)
        # event listing should shows future events plus pas within 10 mins
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 7

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
        baker.make_recipe("booking.future_event", event_type=self.aerial_event_type, _quantity=2, name="Silks")
        baker.make_recipe("booking.future_event", event_type=self.aerial_event_type, _quantity=2, name="silks")
        baker.make_recipe("booking.future_event", event_type=self.aerial_event_type, _quantity=4, name="Trapeze")
        
        resp = self.client.get(self.adult_url)
        # show all by default
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 11
        
        # filter
        resp = self.client.get(self.adult_url + "?event_name=Hoop")
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 3
        resp = self.client.get(self.adult_url + "?event_name=Trapeze")
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 4

        # case insensitive
        resp = self.client.get(self.adult_url + "?event_name=silks")
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 4
                
    def test_event_list_with_booked_events(self):
        """
        test that booked events are shown on listing
        """
        # create a booking for this user
        event = self.aerial_events[0]
        baker.make(Booking, user=self.student_user, event=event)
        resp = self.client.get(self.adult_url)
        user_booking_info = resp.context_data['user_booking_info']
        booked = [event_id for event_id, user_info in user_booking_info.items() if user_info.get("open")]
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
        user_booking_info = resp.context_data['user_booking_info']
        booked = [event_id for event_id, user_info in user_booking_info.items() if user_info.get("open")]
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
        assert len(user_booking_info) == Event.objects.filter(event_type__track=self.adult_track).count()
        # make the aerial events a queryset
        aerial_events = Event.objects.filter(id__in=[event.id for event in self.aerial_events])
        for event_id, user_info in user_booking_info.items():
            if event_id in aerial_events.values_list("id", flat=True):
                assert user_info["available_block"] is None
                assert user_info["available_subscription_info"] is None
                assert user_info["show_warning"] is False
                assert user_info["on_waiting_list"] is False
                # additional data where user has a booking
                assert user_info["open"]
                assert user_info["used_block"] is not None
                assert user_info["used_subscription"] is None
                assert user_info["used_subscription_info"] is None
            else:
                assert user_info["on_waiting_list"] is False
                assert user_info["available_block"] is None
                assert user_info["available_subscription_info"] is None
                assert user_info["show_warning"] is False
                for key in ["open", "used_block", "used_subscription", "used_subscription_info"]:
                    assert key not in user_info

        # cancel button shown for the booked events
        assert 'Cancel' in resp.rendered_content
        # course details button shown for the unbooked course
        assert 'Course details' in resp.rendered_content

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
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 6

    def test_show_on_site_events_only_are_not_listed(self):
        baker.make_recipe('booking.future_event', event_type=self.aerial_event_type, show_on_site=False)
        assert Event.objects.filter(event_type__track=self.adult_track).count() == 7
        resp = self.client.get(self.adult_url)
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 6

    def test_event_list_change_view_as_user(self):
        # manager is also a student
        self.make_disclaimer(self.manager_user)
        self.manager_user.userprofile.student = True
        self.manager_user.userprofile.save()
        self.make_disclaimer(self.child_user)
        self.login(self.manager_user)
        for event in self.aerial_events:
            # create a booking for the manager user for all events
            baker.make(
                Booking, block__dropin_block_config__event_type=self.aerial_event_type,
                user=self.manager_user, event=event
            )

        # manager is a student, so by default shows them as view_as_user
        resp = self.client.get(self.adult_url)
        user_booking_info = resp.context_data['user_booking_info']
        booked_count = sum([1 if user_info.get("open") else 0 for user_info in user_booking_info.values()])
        assert booked_count == 2

        # post to change the user
        resp = self.client.post(self.adult_url, data={"view_as_user": self.child_user.id}, follow=True)
        assert self.client.session["user_id"] == self.child_user.id
        user_booking_info = resp.context_data['user_booking_info']
        booked_count = sum([1 if user_info.get("open") else 0 for user_info in user_booking_info.values()])
        assert booked_count == 0

    def test_block_info(self):
        self.make_disclaimer(self.student_user)
        block = baker.make_recipe(
            "booking.dropin_block", block_config__event_type=self.aerial_event_type,
            block_config__size=10, user=self.student_user, paid=True
        )
        resp = self.client.get(self.adult_url)
        assert "(10/10 remaining); not started" in resp.rendered_content

        block.block_config.duration = None
        block.block_config.save()
        resp = self.client.get(self.adult_url)
        assert "(10/10 remaining); never expires" in resp.rendered_content

        block.block_config.duration = 2
        block.save()
        baker.make(Booking, block=block, event=self.aerial_events[0])
        resp = self.client.get(self.adult_url)
        assert f"(9/10 remaining); expires {(self.aerial_events[0].start + timedelta(14)).strftime('%d-%b-%y')}" in resp.rendered_content
        block.delete()

        baker.make_recipe(
            "booking.course_block",
            block_config__name="A Test Course Block",
            block_config__event_type=self.aerial_event_type,
            block_config__course=True,
            block_config__size=self.course.number_of_events,
            user=self.student_user, paid=True)
        resp = self.client.get(self.adult_url)
        assert "A Test Course Block" in resp.rendered_content
        # Doesn't show the remaining count
        assert "remaining" not in resp.rendered_content

    def test_button_display_dropin_event(self):
        Event.objects.all().delete()
        event = baker.make_recipe("booking.future_event", event_type=self.aerial_event_type)
        make_disclaimer_content(version=None)

        # make a block config so add to cart and paymetn options are shown
        baker.make(BlockConfig, event_type=event.event_type, size=1, active=True)

        self.login(self.student_user)
        resp = self.client.get(self.adult_url)
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 1
        assert "Complete a disclaimer" in resp.rendered_content

        # not booked, has disclaimer
        self.make_disclaimer(self.student_user)
        buttons = self._get_buttons(event)
        for button in ["toggle_booking", "add_course", "waiting_list", "book_course", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Add to cart" in buttons["add_event"].text
        assert "Payment Options" in buttons["payment_options"].text 
        assert buttons["button_text"].text == ""

        # cancelled, no block
        booking = baker.make(Booking, user=self.student_user, event=event, status="CANCELLED")
        buttons = self._get_buttons(event)
        for button in ["toggle_booking", "add_course", "waiting_list", "book_course", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Add to cart" in buttons["add_event"].text
        assert "Payment Options" in buttons["payment_options"].text 
        assert buttons["button_text"].text == ""
        booking.delete()

        # not booked with valid block
        block = baker.make_recipe(
            "booking.dropin_block", block_config__event_type=self.aerial_event_type,
            block_config__size=10, user=self.student_user, paid=True
        )
        buttons = self._get_buttons(event)
        for button in ["add_event", "add_course", "waiting_list", "payment_options", "book_course", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Book Drop-in" in buttons["toggle_booking"].text
        assert buttons["button_text"].text == ""

        # not booked with valid block, booking restricted
        # set the start date to <15 mins ahead (the default booking restriction time)
        event.start = timezone.now() + timedelta(minutes=10)
        event.save()
        buttons = self._get_buttons(event)
        for button in ["add_event", "add_course", "waiting_list", "payment_options", "toggle_booking", "book_course", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Unavailable 15 mins before start" in buttons["button_text"].text

        # reset event
        event.start = timezone.now() + timedelta(minutes=60)
        event.save()
        # cancelled, with block available
        buttons = self._get_buttons(event)
        for button in ["add_event", "add_course", "waiting_list", "payment_options", "book_course", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Book Drop-in" in buttons["toggle_booking"].text
        assert buttons["button_text"].text == ""
        
        # no-show, with block
        booking.status = "OPEN"
        booking.block = block
        booking.no_show = True
        booking.save()
        buttons = self._get_buttons(event)
        for button in ["add_event", "add_course", "waiting_list", "payment_options", "book_course", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Book Drop-in" in buttons["toggle_booking"].text
        assert buttons["button_text"].text == ""
        booking.delete()

        # event full
        baker.make(Booking, event=event, _quantity=event.max_participants)
        buttons = self._get_buttons(event)
        for button in ["add_event", "add_course", "toggle_booking", "payment_options", "book_course", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Join waiting list" in buttons["waiting_list"].text
        assert buttons["button_text"].text == "Class is full"

        # event full, on waiting list
        baker.make(WaitingListUser, event=event, user=self.student_user)
        buttons = self._get_buttons(event)
        for button in ["add_event", "add_course", "toggle_booking", "payment_options", "book_course", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Leave waiting list" in buttons["waiting_list"].text
        assert buttons["button_text"].text == "Class is full"

        # event full, has booking
        event.max_participants += 1
        event.save()
        baker.make(Booking, user=self.student_user, event=event, block=block)
        buttons = self._get_buttons(event)
        for button in ["add_event", "add_course", "waiting_list", "payment_options", "book_course", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Cancel" in buttons["toggle_booking"].text
        assert buttons["button_text"].text == ""
        
    def test_button_display_course_event(self):
        # With a course event, check that the button displays as expected for:
        # - no disclaimer
        # - not booked (with and without available course blocks)
        # - booked and open
        # - cancelled (with and without available course blocks)
        # - no-show (with and without available course blocks)
        # - course full and booked
        # - course full and cancelled/no-show
        # - event cancelled
        # - on waiting list

        Event.objects.all().delete()
        self.course.number_of_events = 1
        self.course.save()
        event = baker.make_recipe("booking.future_event", event_type=self.aerial_event_type, course=self.course)
        make_disclaimer_content(version=None)
        # ensure we have a course block config available (not active)
        course_block_config = baker.make(
            BlockConfig, course=True, event_type=self.course.event_type, size=1, active=False
        )

        self.login(self.student_user)
        resp = self.client.get(self.adult_url)
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 1
        assert "Complete a disclaimer" in resp.rendered_content

        # not booked, has disclaimer
        self.make_disclaimer(self.student_user)
        buttons = self._get_buttons(event)
        for button in ["toggle_booking", "add_event", "waiting_list", "book_course", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Add to cart (course)" in buttons["add_course"].text
        # block config is inactive, so no payment options to show
        assert buttons["payment_options"] is None
        assert buttons["button_text"].text == ""

        # make it active, now payment options are shown
        course_block_config.active = True
        course_block_config.save()
        buttons = self._get_buttons(event)
        assert "Payment Options" in buttons["payment_options"].text 

        # cancelled, no block
        booking = baker.make(Booking, user=self.student_user, event=event, status="CANCELLED")
        buttons = self._get_buttons(event)
        for button in ["toggle_booking", "add_event", "waiting_list", "book_course", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Add to cart (course)" in buttons["add_course"].text
        assert "Payment Options" in buttons["payment_options"].text 
        assert buttons["button_text"].text == ""
        booking.delete()

        # not booked with valid block; book course plus payment options (for dropin)
        block = baker.make_recipe(
            "booking.course_block", block_config__event_type=self.aerial_event_type,
            block_config__size=1, user=self.student_user, paid=True
        )
        buttons = self._get_buttons(event)
        for button in ["toggle_booking", "add_event", "add_course", "waiting_list", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Payment Options" in buttons["payment_options"].text
        assert "Book course" in buttons["book_course"].text

        # cancelled, with block
        booking = baker.make(Booking, user=self.student_user, event=event, status="CANCELLED")
        buttons = self._get_buttons(event)

        # Rebooking allowed if course isn't full
        buttons = self._get_buttons(event)
        for button in ["toggle_booking", "add_event", "add_course", "waiting_list", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Payment Options" in buttons["payment_options"].text
        assert "Book course" in buttons["book_course"].text

        # Make course full
        for courseevent in self.course.events.all():
            baker.make(Booking, event=courseevent, status="OPEN", _quantity=courseevent.max_participants)
        assert self.course.full
        # No book button, user with fully cancelled booking can't rebook
        buttons = self._get_buttons(event)
        for button in ["toggle_booking", "add_event", "add_course", "payment_options", "book_course", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Join waiting list" in buttons["waiting_list"].text
        assert buttons["button_text"].text == "Class is full"

        # get rid of the other bookings
        Booking.objects.exclude(id=booking.id).delete()

        # no-show, with block
        booking.status = "OPEN"
        booking.no_show = True
        booking.save()
        buttons = self._get_buttons(event)
        for button in ["add_event", "add_course", "payment_options", "waiting_list", "book_course", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Rebook" in buttons["toggle_booking"].text
        assert buttons["button_text"].text == ""
        booking.delete()

        # event full
        baker.make(Booking, event=event, _quantity=event.max_participants)
        buttons = self._get_buttons(event)
        for button in ["toggle_booking", "add_event", "add_course", "payment_options", "book_course", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Join waiting list" in buttons["waiting_list"].text
        assert buttons["button_text"].text == "Class is full"

        # event full, on waiting list
        baker.make(WaitingListUser, event=event, user=self.student_user)
        buttons = self._get_buttons(event)
        for button in ["toggle_booking", "add_event", "add_course", "payment_options", "book_course", "unenroll_course_from_event"]:
            assert buttons[button] is None
        assert "Leave waiting list" in buttons["waiting_list"].text
        assert buttons["button_text"].text == "Class is full"

        # event full, has booking
        Booking.objects.all().delete()
        baker.make(Booking, user=self.student_user, event=event, block=block)
        buttons = self._get_buttons(event)
        for button in ["add_event", "add_course", "payment_options", "waiting_list", "book_course"  ]:
            assert buttons[button] is None
        assert buttons["unenroll_course_from_event"] is not None
        assert "Cancel" in buttons["toggle_booking"].text
        assert buttons["button_text"].text == ""

    def test_button_display_course_event_drop_in_allowed(self):
        # With a course event that allows drop-in, check that the button displays as expected for:
        # - no disclaimer
        # - not booked (with and without available course block, dropin block and both)
        # - booked and open
        # - cancelled (with and without available course block, dropin block and both)
        # - no-show (with and without available course block, dropin block and both)
        # - course full and booked
        # - course full and cancelled/no-show
        # - event cancelled
        # - on waiting list

        Event.objects.all().delete()
        self.course.number_of_events = 1
        self.course.allow_drop_in = True
        self.course.save()
        event = baker.make_recipe(
            "booking.future_event",
            event_type=self.aerial_event_type, course=self.course
        )
        make_disclaimer_content(version=None)

        # ensure we have block configs available (not active)
        course_block_config = baker.make(
            BlockConfig, course=True, event_type=self.course.event_type, size=1, active=False
        )
        dropin_block_config = baker.make(
            BlockConfig, course=False, event_type=self.course.event_type, size=1, active=False
        )

        self.login(self.student_user)
        resp = self.client.get(self.adult_url)
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 1
        assert "Complete a disclaimer" in resp.rendered_content

        # not booked, has disclaimer
        self.make_disclaimer(self.student_user)
        buttons = self._get_buttons(event)
        for button in ["toggle_booking", "waiting_list"]:
            assert buttons[button] is None
        assert "Add to cart (course)" in buttons["add_course"].text
        assert "Add to cart (drop-in)" in buttons["add_event"].text
        # block configs aren't active, no payment options shown
        assert buttons["payment_options"] is None
        assert buttons["button_text"].text == ""

        # make them active
        course_block_config.active = True
        course_block_config.save()
        dropin_block_config.active = True
        dropin_block_config.save() 
        buttons = self._get_buttons(event)
        assert "Payment Options" in buttons["payment_options"].text 

        # cancelled, no block
        booking = baker.make(
            Booking, user=self.student_user, event=event, status="CANCELLED"
        )
        buttons = self._get_buttons(event)
        for button in ["toggle_booking", "waiting_list"]:
            assert buttons[button] is None
        assert "Add to cart (course)" in buttons["add_course"].text
        assert "Add to cart (drop-in)" in buttons["add_event"].text
        assert "Payment Options" in buttons["payment_options"].text 
        assert buttons["button_text"].text == ""
        booking.delete()

        # not booked with valid course block; show book course, add drop in, and payment options
        block = baker.make_recipe(
            "booking.course_block", block_config__event_type=self.aerial_event_type,
            block_config__size=1, user=self.student_user, paid=True
        )
        buttons = self._get_buttons(event)
        for button in ["add_course", "waiting_list", "toggle_booking"]:
            assert buttons[button] is None
        for button in ["book_course", "add_event", "payment_options"]:
            assert button is not None
        assert buttons["button_text"].text == ""

        # cancelled, with course block
        booking = baker.make(Booking, user=self.student_user, event=event, status="CANCELLED")
        # Booking allowed if course isn't full; show book course, add drop in, payment options
        buttons = self._get_buttons(event)
        for button in ["add_course", "waiting_list", "toggle_booking"]:
            assert buttons[button] is None
        for button in ["book_course", "add_event", "payment_options"]:
            assert buttons[button] is not None
        assert buttons["button_text"].text == ""

        # cancelled, with drop in block
        block.block_config.course = False
        block.block_config.save()

        # For a drop-in allowed course, user has drop in block, has no course block, but 
        # could also book course
        buttons = self._get_buttons(event)
        for button in ["book_course", "waiting_list", "add_event"]:
            assert buttons[button] is None, button
        for button in ["add_course", "toggle_booking", "payment_options"]:
            assert buttons[button] is not None, button
        assert "Book Drop-in" in buttons["toggle_booking"].text
        assert buttons["button_text"].text == ""

        # But not if the course has started, so just show drop in is available
        self.course.number_of_events = 2
        self.course.save()
        past_event = baker.make_recipe(
            "booking.past_event", event_type=self.aerial_event_type, course=self.course,
        )
        buttons = self._get_buttons(event)
        for button in ["add_course", "add_event", "book_course", "waiting_list"]:
            assert buttons[button] is None, button
        assert buttons["payment_options"] is not None
        assert buttons["button_text"].text  == "Course has started"
        assert "Book Drop-in" in buttons["toggle_booking"].text

        # past event isn't shown
        buttons = self._get_buttons(past_event)
        for button in buttons:
            assert buttons[button] is None
            
        # Make course full
        for courseevent in self.course.events.all():
            baker.make(Booking, event=courseevent, status="OPEN",
                       _quantity=courseevent.max_participants)
        assert self.course.full
        # No book button, user with fully cancelled booking can't rebook
        buttons = self._get_buttons(event)
        for button in ["add_course", "add_event", "toggle_booking", "payment_options"]:
            assert buttons[button] is None
        assert buttons["button_text"].text  == "Class is full"
        assert "Join waiting list" in buttons["waiting_list"].text

        # event full, on waiting list, cancelled booking
        baker.make(WaitingListUser, event=event, user=self.student_user)
        buttons = self._get_buttons(event)
        for button in ["add_course", "add_event", "toggle_booking", "payment_options"]:
            assert buttons[button] is None
        assert buttons["button_text"].text  == "Class is full"
        assert "Leave waiting list" in buttons["waiting_list"].text

        # event full, has no_show booking
        # no-show booking for a course event is from a course booking, so rebooking is allowed
        # delete the first open booking so we can make one for this user
        booking.status = "OPEN"
        booking.no_show = True
        booking.save()
        assert event.full
        buttons = self._get_buttons(event)
        for button in ["add_course", "add_event", "waiting_list", "payment_options"]:
            assert buttons[button] is None
        assert buttons["button_text"].text  == ""
        assert "Rebook" in buttons["toggle_booking"].text
        
        # event full, has open booking
        # delete the first open booking so we can make one for this user
        event.bookings.filter(status="OPEN").first().delete()
        booking.status = "OPEN"
        booking.no_show = False
        booking.save()
        assert event.full
        buttons = self._get_buttons(event)
        for button in ["add_course", "add_event", "waiting_list", "payment_options"]:
            assert buttons[button] is None
        assert buttons["button_text"].text  == ""
        assert "Cancel" in buttons["toggle_booking"].text

        # get rid of the other bookings
        Booking.objects.exclude(id=booking.id).delete()

        # no-show, with block
        booking.status = "OPEN"
        booking.no_show = True
        booking.save()
        buttons = self._get_buttons(event)
        for button in ["add_course", "add_event", "waiting_list", "payment_options"]:
            assert buttons[button] is None
        assert buttons["button_text"].text  == ""
        assert "Rebook" in buttons["toggle_booking"].text
        booking.delete()

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
    #     booking = baker.make_recipe("booking.booking", event=online_class, user=self.user)
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

    def _get_book_course_buttons(self, course, event=None):
        response = self.client.get(self.url)
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
            "payment_options":  soup.find(id=f"payment_options_{event.id}"),
            "waiting_list":  soup.find(id=f"waiting_list_button_{event.id}"),
        }

        for button_key in event_buttons:
            if event_buttons[button_key]:
                event_buttons[button_key] = event_buttons[button_key].text.replace("\n", "").strip()
       
        return book_course_button, event_buttons

    def test_course_list(self):
        resp = self.client.get(self.url)
        # course events are displayed
        response_events = sum(list(resp.context_data['events_by_date'].values()), [])
        assert len(response_events) == 2
        for event in response_events:
            assert event.course == self.course

    def test_course_list_shows_past_events(self):
        baker.make_recipe(
            "booking.past_event", event_type=self.aerial_event_type, course=self.course
        )
        resp = self.client.get(self.url)
        # course events are displayed
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 3

    def test_course_list_with_booked_course(self):
        baker.make(Booking, event=self.course_event, user=self.student_user)
        baker.make(Booking, event=self.course_event1, user=self.student_user)
        resp = self.client.get(self.url)
        assert resp.context_data["book_course_button_options"]["pre_button_text"] == "Student User is attending this course."
    
    def test_course_list_with_booked_course_unenroll(self):
        booking = baker.make(Booking, event=self.course_event, user=self.student_user)
        booking1 = baker.make(Booking, event=self.course_event1, user=self.student_user)
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
        baker.make(Booking, event=self.course_event, user=self.child_user)
        baker.make(Booking, event=self.course_event1, user=self.child_user)
        resp = self.client.get(self.url)
        # booking just made, can unenroll
        assert resp.context_data["book_course_button_options"]["button"] == "unenroll"

    def test_button_display_course_event(self):
        # With a course event, check that the button displays as expected for:
        # - no disclaimer
        # - not booked (with and without available course blocks)
        # - booked and open
        # - cancelled (with and without available course blocks)
        # - no-show (with and without available course blocks)
        # - course full and booked
        # - course full and cancelled/no-show
        # - event cancelled
        # - on waiting list

        Event.objects.all().delete()
        self.course.number_of_events = 1
        self.course.save()
        event = baker.make_recipe("booking.future_event", event_type=self.aerial_event_type, course=self.course)
        make_disclaimer_content(version=None)

        self.login(self.student_user)
        resp = self.client.get(self.url)
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 1
        assert "Complete a disclaimer" in resp.rendered_content

        self.make_disclaimer(self.student_user)
        # not booked, has disclaimer. No main booking button       
        self.make_disclaimer(self.student_user)
        course_button, event_buttons = self._get_book_course_buttons(self.course)
        assert course_button["book_button"] is None
        assert not course_button["unenroll"]
        assert course_button["pre_text"] == ""
        assert course_button["post_text"] == ""

        # There are no valid block configs; no add to basket buttons or payment options shown
        assert add_to_cart_course_block_config(self.course) is None
        assert add_to_cart_drop_in_block_config(self.course.events.first()) is None
        for button in [
            "toggle_booking", 
            "book_course", 
            "unenroll_course_from_event",
            "waiting_list",
            "add_event",
            "add_course", 
            "payment_options"
        ]:
            assert event_buttons[button] is None, button
        assert event_buttons["button_text"] == ""

        # make block configs that are inactive
        course_config = baker.make(
            BlockConfig, course=True, size=1, event_type=self.course.event_type, active=False
        )
        dropin_config = baker.make(
            BlockConfig, course=False, size=1, event_type=self.course.event_type, active=False
        )
        _, event_buttons = self._get_book_course_buttons(self.course)
        for button in [
            "toggle_booking", 
            "book_course", 
            "unenroll_course_from_event",
            "waiting_list",
            "add_event", # dropin not allowed
            "payment_options" # no purchaseable blocks
        ]:
            assert event_buttons[button] is None, button
        for button in ["add_course"]:
            assert event_buttons[button] is not None, button
        assert event_buttons["button_text"] == ""

        # make block configs purchaseable
        for config in [course_config, dropin_config]:
            config.active = True
            config.save()
        _, event_buttons = self._get_book_course_buttons(self.course)
        for button in [
            "toggle_booking", 
            "book_course", 
            "unenroll_course_from_event",
            "waiting_list",
            "add_event", # dropin not allowed
        ]:
            assert event_buttons[button] is None, button
        for button in ["add_course", "payment_options"]:
            assert event_buttons[button] is not None, button
        assert event_buttons["button_text"] == ""

        # cancelled, no block.
        booking = baker.make(Booking, user=self.student_user, event=event, status="CANCELLED")
        course_button, event_buttons = self._get_book_course_buttons(self.course)
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
        ]:
            assert event_buttons[button] is None, button
        for button in ["add_course", "payment_options"]:
            assert event_buttons[button] is not None, button
        assert event_buttons["button_text"] == ""
        booking.delete()

        # not booked with valid block
        block = baker.make_recipe(
            "booking.course_block", block_config__event_type=self.aerial_event_type,
            block_config__size=1, user=self.student_user, paid=True
        )
        course_button, event_buttons = self._get_book_course_buttons(self.course)
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
        ]:
            assert event_buttons[button] is None, button
        for button in ["book_course", "payment_options"]:
            assert event_buttons[button] is not None, button
        assert event_buttons["button_text"] == ""

        # cancelled, with block available
        booking = baker.make(
            Booking, user=self.student_user, event=event, status="CANCELLED"
        )
        course_button, event_buttons = self._get_book_course_buttons(self.course)
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
        ]:
            assert event_buttons[button] is None, button
        for button in ["book_course", "payment_options"]:
            assert event_buttons[button] is not None, button
        assert event_buttons["button_text"] == ""

        # no-show, with block assigned; considered already booked
        booking.status = "OPEN"
        booking.no_show = True
        booking.block = block
        booking.save()
        course_button, event_buttons = self._get_book_course_buttons(self.course)
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
            "unenroll_course_from_event" # not shown for event b/c cancelled so show rebook
        ]:
            assert event_buttons[button] is None, button
        for button in ["toggle_booking"]:
            assert event_buttons[button] is not None, button
        assert event_buttons["toggle_booking"] == "Rebook"
        assert event_buttons["button_text"] == ""
        booking.delete()

        # event full
        baker.make(Booking, event=event, _quantity=event.max_participants)
        course_button, event_buttons = self._get_book_course_buttons(self.course)
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
        ]:
            assert event_buttons[button] is None, button
        assert event_buttons["waiting_list"] == "Join waiting list"
        assert event_buttons["button_text"] == "Class is full"

        # event full, on waiting list
        baker.make(WaitingListUser, event=event, user=self.student_user)
        course_button, event_buttons = self._get_book_course_buttons(self.course)
        assert course_button["book_button"] is None
        assert not course_button["unenroll"]
        assert "This course is full" in course_button["pre_text"]
        assert course_button["post_text"] == ""
        assert event_buttons["waiting_list"] == "Leave waiting list"

        # event full, has booking
        Booking.objects.all().delete()
        booking = baker.make(Booking, user=self.student_user, event=event, block=block)
        course_button, event_buttons = self._get_book_course_buttons(self.course)
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
        ]:
            assert event_buttons[button] is None, button
        assert event_buttons["toggle_booking"] == "Cancel"
        assert event_buttons["unenroll_course_from_event"] is not None
        assert event_buttons["button_text"] == ""

        # has booking made < 24 hrs ago
        booking.date_booked = timezone.now() - timedelta(hours=25)
        booking.save()
        course_button, event_buttons = self._get_book_course_buttons(self.course)
        assert course_button["book_button"] is None
        assert not course_button["unenroll"]
        assert "Student User is attending this course" in course_button["pre_text"]
        assert course_button["post_text"] == ""
        assert event_buttons["unenroll_course_from_event"] is None

        # no bookings, block available, course started
        Booking.objects.all().delete()
        self.course.number_of_events = 2
        self.course.save()
        baker.make_recipe("booking.past_event", course=self.course, event_type=self.aerial_event_type)
        assert self.course.has_started
        # get the event buttons for the last event (not past)
        course_button, event_buttons = self._get_book_course_buttons(self.course, event=self.course.uncancelled_events.last())
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
        course_button, event_buttons = self._get_book_course_buttons(self.course)
        assert "This course has started" in course_button["pre_text"]
        assert event_buttons["button_text"] == "Class is past"

    def test_button_display_course_event_drop_in_allowed(self):
        # With a course event, check that the button displays as expected for:
        # - no disclaimer
        # - not booked (with and without available course blocks)
        # - booked and open
        # - cancelled (with and without available course blocks)
        # - no-show (with and without available course blocks)
        # - course full and booked
        # - course full and cancelled/no-show
        # - event cancelled
        # - on waiting list
        Event.objects.all().delete()
        self.course.number_of_events = 1
        self.course.allow_drop_in = True
        self.course.save()
        event = baker.make_recipe("booking.future_event", event_type=self.aerial_event_type, course=self.course)
        make_disclaimer_content(version=None)

        # make block configs that are purchaseable
        baker.make(
            BlockConfig, course=True, size=1, event_type=self.course.event_type, active=True
        )
        baker.make(
            BlockConfig, course=False, size=1, event_type=self.course.event_type, active=True
        )

        self.login(self.student_user)
        resp = self.client.get(self.url)
        assert len(sum(list(resp.context_data['events_by_date'].values()), [])) == 1
        assert "Complete a disclaimer" in resp.rendered_content

        # not booked, has disclaimer. Booking button for individual events is shown
        self.make_disclaimer(self.student_user)
        course_button, event_buttons = self._get_book_course_buttons(self.course)
        assert course_button["book_button"] is None
        assert not course_button["unenroll"]
        assert "You can book the full course or drop in" in course_button["pre_text"]
        assert "To book drop in, either add classes" in course_button["post_text"]
        for button in [
            "book_course",
            "toggle_booking",
        ]:
            assert event_buttons[button] is None, button
        for button in [
            "add_course",
            "add_event",
            "payment_options",
        ]:
            assert event_buttons[button] is not None, button
        assert event_buttons["button_text"] == ""

        # cancelled, no block.  Booking button for individual events is shown
        booking = baker.make(Booking, user=self.student_user, event=event, status="CANCELLED")
        course_button, event_buttons = self._get_book_course_buttons(self.course)
        assert course_button["book_button"] is None
        assert not course_button["unenroll"]
        assert "You can book the full course or drop in" in course_button["pre_text"]
        assert "To book drop in, either add classes" in course_button["post_text"]
        booking.delete()
        for button in [
            "book_course",
            "toggle_booking",
        ]:
            assert event_buttons[button] is None, button
        for button in [
            "add_course",
            "add_event",
            "payment_options",
        ]:
            assert event_buttons[button] is not None, button
        assert event_buttons["button_text"] == ""

        # not booked with valid course block
        course_block = baker.make_recipe(
            "booking.course_block", block_config__event_type=self.aerial_event_type,
            block_config__size=1, user=self.student_user, paid=True
        )
        course_button, event_buttons = self._get_book_course_buttons(self.course)
        assert "Book Course" in course_button["book_button"]
        assert not course_button["unenroll"]
        assert "You can book the full course or drop in" in course_button["pre_text"]
        assert "To book drop in, either add classes" in course_button["post_text"]
        for button in [
            "add_course",
            "toggle_booking",
        ]:
            assert event_buttons[button] is None, button
        for button in [
            "book_course",
            "add_event",
            "payment_options",
        ]:
            assert event_buttons[button] is not None, button
        assert event_buttons["button_text"] == ""

        # not booked with valid drop in block and course block
        dropin_block = baker.make_recipe(
            "booking.dropin_block", block_config__event_type=self.aerial_event_type,
            block_config__size=1, user=self.student_user, paid=True
        )

        course_button, event_buttons = self._get_book_course_buttons(self.course)
        assert "Book Course" in course_button["book_button"]
        assert not course_button["unenroll"]
        assert "You can book the full course or drop in" in course_button["pre_text"]
        assert "You have an available drop-in payment plan" in course_button["post_text"]
        for button in [
            "add_course",
            "add_event"
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

        # not booked with valid dropin block only
        course_block.paid = False
        course_block.save()
        course_button, event_buttons = self._get_book_course_buttons(self.course)
        assert course_button["book_button"] is None
        assert not course_button["unenroll"]
        assert "You can book the full course or drop in" in course_button["pre_text"]
        assert "You have an available drop-in payment plan" in course_button["post_text"]
        for button in [
            "book_course",
            "add_event"
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

        # cancelled, with dropin block
        booking = baker.make(Booking, user=self.student_user, event=event, status="CANCELLED")
        course_button, event_buttons = self._get_book_course_buttons(self.course)
        assert course_button["book_button"] is None
        assert not course_button["unenroll"]
        assert "You can book the full course or drop in" in course_button["pre_text"]
        assert "You have an available drop-in payment plan" in course_button["post_text"]
        for button in [
            "book_course",
            "add_event"
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

        # no-show, with course block
        booking.block = course_block
        booking.status = "OPEN"
        booking.no_show = True
        booking.save()
        course_button, event_buttons = self._get_book_course_buttons(self.course)
        assert course_button["book_button"] is None
        assert course_button["unenroll"] == ""  # unenroll is a form, no text
        assert "Student User is attending this course" in course_button["pre_text"]
        assert "You can reschedule" in course_button["post_text"]
        for button in [
            "book_course",
            "add_course",
            "add_event",
            "payment_options"
        ]:
            assert event_buttons[button] is None, button
        assert event_buttons["toggle_booking"] == "Rebook"
        assert event_buttons["button_text"] == ""
        booking.delete()

        # event full; dropin allowed
        baker.make(Booking, event=event, _quantity=event.max_participants)
        course_button, _ = self._get_book_course_buttons(self.course)
        assert course_button["book_button"] is None
        assert not course_button["unenroll"]
        assert "This course is full" in course_button["pre_text"]
        assert course_button["post_text"] == ""

        # event full, has booking on course block
        course_block.paid = True
        course_block.save()
        Booking.objects.all().delete()
        baker.make(Booking, user=self.student_user, event=event, block=course_block)
        course_button, _  = self._get_book_course_buttons(self.course)
        assert course_button["book_button"] is None
        assert course_button["unenroll"] == ""  # unenroll is a form, no text
        assert "Student User is attending this course" in course_button["pre_text"]
        assert "You can reschedule" in course_button["post_text"]

        # event full, has booking on dropin block
        course_block.paid = False
        course_block.save()
        Booking.objects.all().delete()
        baker.make(Booking, user=self.student_user, event=event, block=dropin_block)
        course_button, event_buttons  = self._get_book_course_buttons(self.course)
        assert course_button["book_button"] is None
        assert course_button["unenroll"] == ""  # unenroll is a form, no text
        assert "Student User is attending this course" in course_button["pre_text"]
        assert "You can reschedule" in course_button["post_text"]

        # booked dropin for some events only with dropin block
        # no course block available
        self.course.number_of_events = 2
        self.course.save()
        second_event = baker.make_recipe("booking.future_event", event_type=self.aerial_event_type, course=self.course)

        course_button, event_buttons = self._get_book_course_buttons(self.course)
        assert course_button["book_button"] is None
        assert course_button["unenroll"] is None
        assert "Student User has booked for classes on this course." in course_button["pre_text"]
        assert course_button["post_text"] == ""
        for button in [
            "book_course",
            "add_course",
            "add_event",
            "payment_options"
        ]:
            assert event_buttons[button] is None, button
        assert event_buttons["toggle_booking"] == "Cancel"
        assert event_buttons["button_text"] == ""

        # booked dropin for some events only with dropin block
        # course block available
        baker.make_recipe(
            "booking.course_block", block_config__event_type=self.aerial_event_type,
            block_config__size=2, user=self.student_user, paid=True
        )
        course_button, event_buttons = self._get_book_course_buttons(self.course)
        assert course_button["book_button"] == "Book Course"
        assert course_button["unenroll"] is None
        assert "Student User has booked for classes on this course." in course_button["pre_text"]
        assert "You have a course credit block available" in course_button["post_text"]
        for button in [
            "book_course",
            "add_course",
            "add_event",
            "payment_options"
        ]:
            assert event_buttons[button] is None, button
        assert event_buttons["toggle_booking"] == "Cancel"
        assert event_buttons["button_text"] == ""

        # booked dropin for some events only with dropin block
        # course block available but course not full
        baker.make(Booking, event=second_event, _quantity=self.course.max_participants)
        self.course.refresh_from_db()
        assert self.course.full
        course_button, event_buttons = self._get_book_course_buttons(self.course)
        assert course_button["book_button"] is None
        assert course_button["unenroll"] is None
        assert "Student User has booked for classes on this course." in course_button["pre_text"]
        assert course_button["post_text"] == ""
        for button in [
            "book_course",
            "add_course",
            "add_event",
            "payment_options"
        ]:
            assert event_buttons[button] is None, button
        assert event_buttons["toggle_booking"] == "Cancel"
        assert event_buttons["button_text"] == ""
