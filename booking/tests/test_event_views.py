from model_bakery import baker
from datetime import timedelta

from django.core.cache import cache
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from accounts.models import DataPrivacyPolicy, SignedDataPrivacy
from accounts.models import has_active_data_privacy_agreement

from booking.models import Event, Booking, Track
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
        assert "Log in</a> to book</span>" in resp.rendered_content

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
            # create a booking for this user for all events
            baker.make(
                Booking, block__block_config__event_type=self.aerial_event_type,
                user=self.student_user, event=event
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
                assert user_info["has_booked"] is True
                assert user_info["can_book_or_cancel"] is True
                assert user_info["on_waiting_list"] is False
                assert user_info["has_available_block"] is False
                assert user_info["available_block"] is None
                assert user_info["open"] is True
                assert user_info["cancelled"] is False
                assert user_info["used_block"] is not None
            else:
                assert user_info["has_booked"] is False
                assert user_info["can_book_or_cancel"] is True
                assert user_info["on_waiting_list"] is False
                assert user_info["has_available_block"] is False
                assert user_info["available_block"] is None
                assert "open" not in user_info
                assert "cancelled" not in user_info
                assert "used_block" not in user_info

            if Event.objects.get(id=event_id).course:
                assert user_info["has_available_course_block"] is False
            else:
                assert "has_available_course_block" not in user_info

        # cancel button shown for the booked events
        assert 'Cancel' in resp.rendered_content
        # course details button shown for the unbooked course
        assert 'View course details' in resp.rendered_content

    def test_event_list_user_booking_info_booking_restriction(self):
        """
        test that booked events are shown on listing
        """
        self.make_disclaimer(self.student_user)
        resp = self.client.get(self.adult_url)
        user_booking_info = resp.context_data['user_booking_info']

        # user booking info for every track event
        assert len(user_booking_info) == Event.objects.filter(event_type__track=self.adult_track).count()
        # make the aerial events a queryset
        aerial_events = Event.objects.filter(id__in=[event.id for event in self.aerial_events])
        for event_id, user_info in user_booking_info.items():
            if event_id in aerial_events.values_list("id", flat=True):
                assert user_info["has_booked"] is False
                assert user_info["can_book_or_cancel"] is True

        # set the start date to <15 mins ahead (the default booking restriction time)
        for event in self.aerial_events:
            event.start = timezone.now() + timedelta(minutes=10)
            event.save()
        resp = self.client.get(self.adult_url)
        user_booking_info = resp.context_data['user_booking_info']
        for event_id, user_info in user_booking_info.items():
            if event_id in aerial_events.values_list("id", flat=True):
                assert user_info["has_booked"] is False
                assert user_info["can_book_or_cancel"] is False

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

    def test_button_displays(self):
        # TODO
        # With a single event, check that the button displays as expected for:
        # - no disclaimer
        # - not booked (with and without available blocks)
        # - booked and open
        # - cancelled (with and without available blocks)
        # - no-show (with and without available blocks)
        # - event full and booked
        # - event full and cancelled/no-show
        # - event cancelled and cancelled/no-show
        # - on waiting list
        ...


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


class CourseListViewTests(EventTestMixin, TestUsersMixin, TestCase):

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
        assert resp.context_data["already_booked"] is True

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
        assert "Purchase a payment plan" in resp.rendered_content
        # check there are no booked events yet
        assert resp.context_data["already_booked"] is False

        # create a booking for the managed user
        baker.make(Booking, event=self.course_event, user=self.child_user)
        baker.make(Booking, event=self.course_event1, user=self.child_user)
        resp = self.client.get(self.url)
        assert "Payment plan available" not in resp.rendered_content
        assert resp.context_data["already_booked"] is True
