from django.contrib import admin

from .models import (
    Block, BlockConfig, Booking, BlockVoucher, GiftVoucherType,
    Course, Event, EventType, Track, WaitingListUser, SubscriptionConfig, Subscription
)


class BookingInline(admin.TabularInline):
    model = Booking


class EventInline(admin.TabularInline):
    model = Event
    can_delete = False
    max_num = 0


class EventTypeInline(admin.TabularInline):
    model = EventType
    can_delete = False


class TrackAdmin(admin.ModelAdmin):
    model = Track
    inlines = (EventTypeInline,)


class BlockAdmin(admin.ModelAdmin):
    model = Block
    inlines = (BookingInline,)


class EventAdmin(admin.ModelAdmin):
    model = Event
    inlines = (BookingInline,)


class CourseAdmin(admin.ModelAdmin):
    model = Course
    inlines = (EventInline,)


class SubscriptionAdmin(admin.ModelAdmin):
    model = Subscription
    inlines = (BookingInline,)


admin.site.site_header = "Freedom of Flight Admin"
admin.site.register(Event, EventAdmin)
admin.site.register(Track, TrackAdmin)
admin.site.register(Course, CourseAdmin)
admin.site.register(Booking)
admin.site.register(Block, BlockAdmin)
admin.site.register(BlockConfig)
admin.site.register(EventType)
admin.site.register(WaitingListUser)
admin.site.register(BlockVoucher)
admin.site.register(GiftVoucherType)
admin.site.register(Subscription, SubscriptionAdmin)
admin.site.register(SubscriptionConfig)
