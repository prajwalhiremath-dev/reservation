from django.contrib import admin
from .models import Family, User, Device, Testbed, Reservation, AllowedReservationPeriod, Software, DeletionRequest
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
import json

# Customize admin site
admin.site.site_title = "Cisco Admin Panel"
admin.site.site_header = 'Cisco Testbed Dashboard'
admin.site.index_title = "Cisco Administration"

@admin.register(Family)
class FamilyAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ['name']

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'is_staff', 'is_superuser', 'is_guest', 'force_password_change')
    list_filter = ('is_staff', 'is_superuser', 'is_guest', 'force_password_change')
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'is_guest', 'force_password_change', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2'),
        }),
    )
    search_fields = ('username', 'email')
    ordering = ('username',)


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


@admin.register(DeletionRequest)
class DeletionRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'get_reservation_info', 'requester', 'status_display', 'created_at', 'admin', 'get_testbed')
    list_filter = ('status', 'created_at', 'updated_at')
    search_fields = ('requester__username', 'admin__username', 'reason', 'admin_comment', 
                    'reservation__testbed__name', 'reservation_details__testbed_name')
    readonly_fields = ('created_at', 'updated_at', 'get_reservation_details')

    def get_reservation_info(self, obj):
        if obj.reservation:
            return str(obj.reservation)
        elif obj.reservation_details:
            return f"Deleted reservation - {obj.reservation_details.get('testbed_name')} ({obj.reservation_details.get('user')})"
        return "Unknown reservation"
    get_reservation_info.short_description = "Reservation"

    def get_testbed(self, obj):
        if obj.reservation:
            return obj.reservation.testbed.name
        return obj.reservation_details.get('testbed_name', 'Unknown') if obj.reservation_details else 'Unknown'
    get_testbed.short_description = 'Testbed'

    def status_display(self, obj):
        status_colors = {
            'PENDING': '#FFA500',  # Orange
            'APPROVED': '#28A745',  # Green
            'REJECTED': '#DC3545'   # Red
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            status_colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_display.short_description = 'Status'

    def get_reservation_details(self, obj):
        if obj.status == 'APPROVED' and obj.reservation_details:
            details = obj.reservation_details
            html = f"""
                <strong>Testbed:</strong> {details.get('testbed_name')}<br>
                <strong>User:</strong> {details.get('user')}<br>
                <strong>Start Time:</strong> {details.get('start_time')}<br>
                <strong>End Time:</strong> {details.get('end_time')}<br>
                <strong>Devices:</strong> {', '.join(details.get('devices', []))}<br>
                <strong>Type:</strong> {details.get('reservation_type')}<br>
                <strong>Software Image:</strong> {details.get('software_image') or 'None'}<br>
            """
            return mark_safe(html)
        return "-"
    get_reservation_details.short_description = "Deleted Reservation Details"

    fieldsets = (
        ('Request Information', {
            'fields': ('requester', 'reason', 'status')
        }),
        ('Reservation Information', {
            'fields': ('reservation', 'get_reservation_details'),
        }),
        ('Admin Action', {
            'fields': ('admin', 'admin_comment')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser