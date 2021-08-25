from django.contrib import admin
from django.utils import timezone

from common.utils import full_name

from .models import (
    Block, BlockConfig, Booking, BlockVoucher, GiftVoucher, GiftVoucherConfig,
    Course, Event, EventType, Track, WaitingListUser, SubscriptionConfig, Subscription,
    TotalVoucher, Product, ProductCategory, ProductPurchase, ProductVariant, ProductStock
)


class CourseFilter(admin.SimpleListFilter):

    title = 'Upcoming Courses'
    parameter_name = 'course'

    def lookups(self, request, model_admin):
        return [
            (course.id, course) for course in Course.objects.all() if course.last_event_date is not None and
            course.last_event_date >= timezone.now()
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(event__course_id=self.value())
        return queryset


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


class GiftVoucherInline(admin.TabularInline):
    model = GiftVoucher


class EventTypeInline(admin.TabularInline):
    model = EventType
    can_delete = False


class ProductInline(admin.TabularInline):
    model = Product


class ProductStockInline(admin.TabularInline):
    model = ProductStock


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    inlines = (ProductVariantInline,)


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    inlines = (ProductInline,)


@admin.register(ProductVariant)
class ProductAdmin(admin.ModelAdmin):
    inlines = (ProductStockInline,)


@admin.register(ProductPurchase)
class ProductPurchaseAdmin(admin.ModelAdmin):
    ...


class TrackAdmin(admin.ModelAdmin):
    model = Track
    inlines = (EventTypeInline,)


class BookingAdmin(admin.ModelAdmin):
    model = Booking
    list_filter = ["event__event_type", CourseFilter]
    list_display = ["get_user", "event", "status", "no_show", "block"]
    search_fields = ["user__first_name", "user__last_name", "event__name"]

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
    list_filter = ["event_type"]
    search_fields = ["name"]
    inlines = (BookingInline,)


class CourseAdmin(admin.ModelAdmin):
    model = Course
    inlines = (EventInline,)


class SubscriptionAdmin(admin.ModelAdmin):
    model = Subscription
    inlines = (BookingInline,)


class GiftVoucherConfigAdmin(admin.ModelAdmin):
    model = GiftVoucherConfig
    list_display = ("discount_amount", "block_config", "duration", "active",)
    inlines = (GiftVoucherInline,)


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
admin.site.register(TotalVoucher)
admin.site.register(GiftVoucher)
admin.site.register(GiftVoucherConfig, GiftVoucherConfigAdmin)
admin.site.register(Subscription, SubscriptionAdmin)
admin.site.register(SubscriptionConfig)
