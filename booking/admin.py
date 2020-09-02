from django.contrib import admin

from common.utils import full_name

from .models import (
    Block, BlockConfig, Booking, BlockVoucher, GiftVoucherType,
    Course, Event, EventType, Track, WaitingListUser, SubscriptionConfig, Subscription
)


class BookingInline(admin.TabularInline):
    model = Booking


class SubscriptionInline(admin.TabularInline):
    model = Subscription


class BlockInline(admin.TabularInline):
    model = Block


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


class BookingAdmin(admin.ModelAdmin):
    model = Booking
    list_filter = ["event"]
    list_display = ["get_user", "event", "status", "no_show", "block"]
    search_fields = ["user__first_name", "user__last_name"]

    def get_user(self, obj):
        return full_name(obj.user)
    get_user.short_description = "User"
    get_user.admin_order_field = 'user__first_name'


class BlockAdmin(admin.ModelAdmin):
    model = Block
    inlines = (BookingInline,)
    list_filter = ["user"]
    list_display = ["get_user", "block_config", "start_date", "expiry_date", "paid"]
    search_fields = ["user__first_name", "user__last_name"]

    def get_user(self, obj):
        return full_name(obj.user)
    get_user.short_description = "User"
    get_user.admin_order_field = 'user__first_name'


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
admin.site.register(Booking, BookingAdmin)
admin.site.register(Block, BlockAdmin)
admin.site.register(BlockConfig)
admin.site.register(EventType)
admin.site.register(WaitingListUser)
admin.site.register(BlockVoucher)
admin.site.register(GiftVoucherType)
admin.site.register(Subscription, SubscriptionAdmin)
admin.site.register(SubscriptionConfig)
