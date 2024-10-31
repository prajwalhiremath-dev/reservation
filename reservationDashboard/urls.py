from django.contrib import admin
from django.urls import path, include
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('guest-login/', views.guest_login, name='guest_login'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/update/', views.update_profile, name='update_profile'),
    path('change-password/', views.change_password, name='change_password'),
    path("", views.index, name = "index" ),
    path('reservation/', views.make_reservation, name='reservation'),
    path('get-testbeds/', views.get_testbeds, name='get_testbeds'),
    path('get-devices/', views.get_devices, name='get_devices'),
    path('get_available_devices/', views.get_available_devices, name='get_available_devices'),
    path('reservation-table/', views.reservation_table, name='reservation_table'),
    path('api/reservations/', views.get_reservations, name='get_reservations'),
    path('api/reservations/<int:reservation_id>/', views.get_reservation, name='get_reservation'),
    path('api/reservations/<int:reservation_id>/update/', views.update_reservation, name='update_reservation'),
    path('api/reservations/<int:reservation_id>/delete/', views.delete_reservation, name='delete_reservation'),
    path('get_allowed_period/', views.get_allowed_period, name='get_allowed_period'),
    path('get-software-images/', views.get_software_images, name='get_software_images'),
    path('get-available-devices/', views.get_available_devices, name='get_available_devices'),
    path('get-available-devices-update/', views.get_available_devices_update, name='get_available_devices_update'),
    path('get-users/', views.get_users, name='get_users'),
    path('get-devices-update/', views.get_devices_update, name='get_devices_update'),
    path('get-families/', views.get_families, name='get_families'),
    path('get-all-testbeds/', views.get_all_testbeds, name='get_all_testbeds'),
    path('maintenance/', views.maintenance, name='maintenance'),
    path('about/', views.about, name='about'),
    path('api/reservations/<int:reservation_id>/request-deletion/', views.create_deletion_request, name='create_deletion_request'),
    path('api/deletion-requests/<int:request_id>/handle/', views.handle_deletion_request, name='handle_deletion_request'),
    path('api/deletion-requests/', views.get_deletion_requests, name='get_deletion_requests'),


]