from django.contrib import admin

from .models import (
    Block, DropInBlockConfig, CourseBlockConfig, Booking, BlockVoucher, GiftVoucherType,
    Course, CourseType, Event, EventType, Track, WaitingListUser
)

admin.site.site_header = "Freedom of Flight Admin"
admin.site.register(Event)
admin.site.register(Track)
admin.site.register(Course)
admin.site.register(CourseType)
admin.site.register(Booking)
admin.site.register(Block)
admin.site.register(DropInBlockConfig)
admin.site.register(CourseBlockConfig)
admin.site.register(EventType)
admin.site.register(WaitingListUser)
admin.site.register(BlockVoucher)
admin.site.register(GiftVoucherType)