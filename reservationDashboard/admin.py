from django.contrib import admin
from .models import Family, User, Device, Testbed, Reservation, AllowedReservationPeriod, Software

# Customize admin site
admin.site.site_title = "Cisco Admin Panel"
admin.site.site_header = 'Cisco Testbed Dashboard'
admin.site.index_title = "Cisco Administration"

@admin.register(Family)
class FamilyAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ['name']

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username',)
    search_fields = ['username']

@admin.register(Testbed)
class TestbedAdmin(admin.ModelAdmin):
    list_display = ('name', 'family', 'total_devices')
    list_filter = ['family']
    search_fields = ['name', 'family__name']

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'family', 'testbed', 'is_eor')
    list_filter = ['family', 'testbed', 'is_eor']
    search_fields = ['name', 'testbed__name', 'family__name']
    fieldsets = (
        (None, {
            'fields': ('family', 'testbed', 'name', 'is_eor')
        }),
        ('Network Details', {
            'fields': ('mgmt', 'console', 'gateway')
        }),
        ('EOR Specific', {
            'fields': ('mgmt2_standby', 'console2_standby'),
            'classes': ('collapse',),
            'description': "Only applicable for EOR devices"
        }),
        ('Additional Info', {
            'fields': ('platform_details',)
        }),
    )

@admin.register(Software)
class SoftwareAdmin(admin.ModelAdmin):
    list_display = ('image',)
    search_fields = ['image']

@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'testbed', 'reservation_type', 'start_time', 'end_time', 'created_at')
    list_filter = ['reservation_type', 'testbed', 'user']
    search_fields = ['user__username', 'testbed__name']
    filter_horizontal = ('devices',)
    readonly_fields = ('created_at',)
    fieldsets = (
        (None, {
            'fields': ('user', 'testbed', 'devices')
        }),
        ('Reservation Details', {
            'fields': ('start_time', 'end_time', 'reservation_type', 'software_image')
        }),
        ('Additional Info', {
            'fields': ('comments', 'created_at')
        }),
    )

@admin.register(AllowedReservationPeriod)
class AllowedReservationPeriodAdmin(admin.ModelAdmin):
    list_display = ('start_datetime', 'end_datetime')