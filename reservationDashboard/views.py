from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponseBadRequest
from .models import User, Family, Testbed, Device, Software, Reservation, AllowedReservationPeriod, DeletionRequest
from .forms import ReservationForm, CustomAuthenticationForm, CustomUserCreationForm, PasswordChangeForm
from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_datetime
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from django.db.models import Prefetch, Count, Sum, F, ExpressionWrapper, fields
from django.views.decorators.http import require_http_methods
from django.core.serializers.json import DjangoJSONEncoder
from django.views.decorators.csrf import csrf_exempt, csrf_protect
import json
import traceback
from django.http import HttpResponseServerError
from webexteamssdk import WebexTeamsAPI
from django.conf import settings
from django.contrib.auth import login, authenticate, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.hashers import check_password
from django.db.models import Q
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db.models.functions import TruncHour
from django.db.models import Count
import logging
logger = logging.getLogger(__name__)

def login_view(request):
    if request.user.is_authenticated:
        return redirect('index')
        
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(username=username, password=password)
        if user is not None:
            login(request, user)
            
            # Check if user needs to change password
            if user.force_password_change:
                messages.warning(request, 'Please change your temporary password.')
                return redirect('change_password')
            
            return redirect('index')
        else:
            messages.error(request, 'Invalid username or password.')
    
    return render(request, 'auth/login.html')

@login_required
def logout_view(request):
    logout(request)
    messages.info(request, 'You have been logged out successfully.')
    return redirect('login')

def guest_login(request):
    """Handle guest user login"""
    try:
        guest_user = User.objects.get(username='guest')
        login(request, guest_user)
        return JsonResponse({'success': True, 'redirect_url': '/'})
    except User.DoesNotExist:
        return JsonResponse({
            'success': False, 
            'error': 'Guest account not available'
        }, status=400)

def register_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.force_password_change = False  # New users don't need to change password
            user.save()
            login(request, user)
            messages.success(request, 'Registration successful!')
            return redirect('index')
    else:
        form = CustomUserCreationForm()
    return render(request, 'auth/register.html', {'form': form})

@login_required
def profile_view(request):
    """Display user profile and reservation history"""
    context = {
        'user': request.user,
        'page_title': 'Profile',
        'page_subtitle': 'User Profile'
    }
    return render(request, 'auth/profile.html', context)

@login_required
def update_profile(request):
    """Handle profile updates including password changes"""
    if request.method == 'POST':
        user = request.user
        username = request.POST.get('username')
        email = request.POST.get('email')
        current_password = request.POST.get('current_password')
        new_password = request.POST.get('new_password')

        # Check if username is already taken
        if username != user.username and User.objects.filter(username=username).exists():
            messages.error(request, 'Username is already taken.')
            return redirect('profile')

        # Check if email is already taken
        if email != user.email and User.objects.filter(email=email).exists():
            messages.error(request, 'Email is already registered.')
            return redirect('profile')

        # Update basic info
        user.username = username
        user.email = email

        # Handle password change if requested
        if current_password and new_password:
            if not check_password(current_password, user.password):
                messages.error(request, 'Current password is incorrect.')
                return redirect('profile')
            
            # Validate new password
            if len(new_password) < 8:
                messages.error(request, 'Password must be at least 8 characters long.')
                return redirect('profile')
            
            user.set_password(new_password)
            messages.success(request, 'Password updated successfully. Please login again.')
        else:
            messages.success(request, 'Profile updated successfully.')

        user.save()
        
        # If password was changed, redirect to login
        if new_password:
            return redirect('login')
        
        return redirect('profile')

    return redirect('profile')


@login_required
def change_password(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = request.user
            user.set_password(form.cleaned_data['new_password'])
            user.force_password_change = False  # Remove the force password change flag
            user.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Your password was successfully updated!')
            return redirect('profile')
    else:
        form = PasswordChangeForm(request.user)
    
    context = {
        'form': form,
        'force_change': request.user.force_password_change
    }
    return render(request, 'auth/change_password.html', context)



@login_required
def index(request):
    context = {
        'page_title': 'Cisco Dashboard',
        'page_subtitle': 'Testbed Reservation'
    }
    return render(request, 'base/index.html', context=context)

def get_todays_analytics(request):
    today = timezone.now().date()
    tomorrow = today + timedelta(days=1)
    current_time = timezone.now()
    
    # Get today's reservations
    todays_reservations = Reservation.objects.filter(
        start_time__lt=tomorrow,
        end_time__gt=current_time
    )
    
    # Get reservation type counts
    reservation_types = todays_reservations.values('reservation_type').annotate(
        count=Count('id')
    )
    
    # Get software image usage
    software_usage = todays_reservations.values('software_image__image').annotate(
        count=Count('id')
    ).exclude(software_image__isnull=True)
    
    # Get user reservation hours
    user_hours = todays_reservations.values('user__username').annotate(
        total_hours=Sum(
            ExpressionWrapper(
                F('end_time') - F('start_time'),
                output_field=fields.DurationField()
            )
        )
    ).order_by('-total_hours')           #[:10]  # Top 10 users
    
    # Convert duration to hours
    for user in user_hours:
        if user['total_hours']:
            duration_in_hours = user['total_hours'].total_seconds() / 3600
            user['total_hours'] = round(duration_in_hours, 1)
    
    # Get device availability
    all_devices = Device.objects.all()
    device_availability = []
    
    for device in all_devices:
        # Get all reservations that overlap with today
        device_reservations = device.reservation_set.filter(
            start_time__lt=tomorrow,
            end_time__gt=current_time
        ).order_by('start_time')
        
        is_available = True
        next_available = current_time
        
        # Calculate actual free hours considering overlapping periods
        reserved_periods = []
        for res in device_reservations:
            start = max(res.start_time, current_time)
            end = res.end_time
            if start < end:
                reserved_periods.append((start, end))
                if current_time >= start and current_time < end:
                    is_available = False
                    next_available = end
        
        # Calculate free hours for next 24 hours
        free_hours = 24
        day_end = current_time + timedelta(days=1)
        
        for start, end in reserved_periods:
            if start < day_end:
                overlap_start = max(current_time, start)
                overlap_end = min(day_end, end)
                free_hours -= (overlap_end - overlap_start).total_seconds() / 3600
        
        # Determine next available time
        if not is_available:
            next_available_str = next_available.strftime("%I:%M %p")
        else:
            next_available_str = "Now"
        
        device_availability.append({
            'id': device.id,
            'name': device.name,
            'free_hours': round(max(0, free_hours), 1),
            'next_available': next_available_str,
            'status': 'Available' if is_available else 'In Use'
        })
    
    # Calculate active devices and utilization rate
    active_devices = sum(1 for device in device_availability if device['status'] == 'In Use')
    total_devices = len(device_availability)
    utilization_rate = (active_devices / total_devices * 100) if total_devices > 0 else 0
    
    # Get user's reservations
    user_reservations = []
    if not request.user.is_anonymous:
        user_reservations = todays_reservations.filter(
            user=request.user
        ).values(
            'testbed__name', 
            'start_time', 
            'end_time', 
            'reservation_type'
        )
    
    data = {
        'total_reservations': todays_reservations.count(),
        'active_devices': active_devices,
        'utilization_rate': round(utilization_rate, 1),
        'reservation_types': list(reservation_types),
        'software_usage': list(software_usage),
        'user_hours': list(user_hours),
        'device_availability': device_availability,
        'user_reservations': list(user_reservations)
    }
    
    return JsonResponse(data)


@login_required
@transaction.atomic
def make_reservation(request):
    if request.method == 'POST':
        try:
            form = ReservationForm(request.POST, is_update=False)  # Remove request_user parameter
            if form.is_valid():
                try:
                    with transaction.atomic():
                        reservation = form.save(commit=False)
                        # Set the logged-in user
                        reservation.user = request.user  # Set the logged-in user
                        
                        if not AllowedReservationPeriod.is_period_allowed(reservation.start_time, reservation.end_time):
                            return JsonResponse({'success': False, 'error': "Reservation is not within allowed period."})
                        
                        # Set _devices_to_check before saving
                        reservation._devices_to_check = form.cleaned_data['devices']

                        reservation.full_clean()  # This will trigger the clean method
                        reservation.save()  # This will now handle setting the devices
                    return JsonResponse({'success': True, 'message': 'Reservation created successfully.'})
                except ValidationError as e:
                    #error_message = e.messages[0] if isinstance(e.messages, list) else str(e)
                    error_message = '; '.join(e.messages) if isinstance(e.messages, list) else str(e)
                    return JsonResponse({'success': False, 'error': error_message})
            else:
                errors = form.errors.as_text() 
                return JsonResponse({'success': False, 'error': errors})
        except Exception as e:
            logger.error(f"Unexpected error in make_reservation: {str(e)}\n{traceback.format_exc()}")
            return JsonResponse({'success': False, 'error': 'An unexpected error occurred. Please try again.'}, status=500)
    else:
        form = ReservationForm(is_update=False)  # Remove request_user parameter
 
    context = {
        'form': form,
        'current_user': request.user,  # Add current user to context   #'users': User.objects.all(),
        'families': Family.objects.all(),
        'testbeds': Testbed.objects.all(),
        'devices': Device.objects.all(),
        'software_images': Software.objects.all(),
    }
    return render(request, 'reservation/reservation.html', context)



def get_testbeds(request):
    family_id = request.GET.get('family_id')
    testbeds = Testbed.objects.filter(family_id=family_id).values('id', 'name')
    return JsonResponse(list(testbeds), safe=False)

def get_devices(request):
    testbed_id = request.GET.get('testbed_id')
    devices = Device.objects.filter(testbed_id=testbed_id).values('id', 'name')
    return JsonResponse(list(devices), safe=False)

def get_available_devices(request):
    testbed_id = request.GET.get('testbed_id')
    start_time_str = request.GET.get('start_time')
    end_time_str = request.GET.get('end_time')
    
    # Convert string to datetime and make it timezone-aware
    start_time = timezone.make_aware(datetime.strptime(start_time_str, "%Y-%m-%d %H:%M"))
    end_time = timezone.make_aware(datetime.strptime(end_time_str, "%Y-%m-%d %H:%M"))
    
    testbed = Testbed.objects.get(id=testbed_id)
    all_devices = testbed.devices.all()
    
    unavailable_devices = Reservation.objects.filter(
        testbed=testbed,
        start_time__lt=end_time,
        end_time__gt=start_time
    ).values_list('devices', flat=True).distinct()
    
    available_devices = all_devices.exclude(id__in=unavailable_devices)
    
    return JsonResponse(list(available_devices.values('id', 'name')), safe=False)


# def reservation_table(request):
#     """Render the reservation table page"""
#     return render(request, 'reservation/reservation_table.html')
@login_required
def reservation_table(request):
    return render(request, 'reservation/reservation_table.html')


@require_http_methods(["GET"])
def get_allowed_period(request):
    allowed_period = AllowedReservationPeriod.objects.first()  # Assuming you have only one period
    if allowed_period:
        return JsonResponse({
            'start_datetime': allowed_period.start_datetime.isoformat(),
            'end_datetime': allowed_period.end_datetime.isoformat()
        })
    else:
        # Return default values if no allowed period is set
        now = timezone.now()
        return JsonResponse({
            'start_datetime': now.isoformat(),
            'end_datetime': (now + timezone.timedelta(days=7)).isoformat()
        })

@require_http_methods(["GET"])
def get_reservations(request):
    try:
        start_datetime = request.GET.get('start_datetime')
        end_datetime = request.GET.get('end_datetime')

        print(f"Received start_datetime: {start_datetime}")
        print(f"Received end_datetime: {end_datetime}")

        if start_datetime and end_datetime:
            start_datetime = timezone.datetime.fromisoformat(start_datetime.replace('Z', '+00:00'))
            end_datetime = timezone.datetime.fromisoformat(end_datetime.replace('Z', '+00:00'))
        else:
            # Default to current week if no dates provided
            start_datetime = timezone.now()
            end_datetime = start_datetime + timezone.timedelta(days=7)

        print(f"Parsed start_datetime: {start_datetime}")
        print(f"Parsed end_datetime: {end_datetime}")

        reservations = Reservation.objects.filter(
            start_time__gte=start_datetime,
            end_time__lte=end_datetime
        ).select_related('user', 'testbed').prefetch_related('devices')

        data = []
        for r in reservations:
            reservation_data = {
                'id': r.id,
                'user': r.user.username,
                'testbed': r.testbed.name,
                'date': r.start_time.date().isoformat(),
                'startTime': r.start_time.strftime('%H:%M'),
                'endTime': r.end_time.strftime('%H:%M'),
                'type': r.reservation_type,
                'devices': [{'id': d.id, 'name': d.name} for d in r.devices.all()]
            }
            data.append(reservation_data)
        return JsonResponse(data, safe=False)
    except ValidationError as e:
        return HttpResponseBadRequest(f"Invalid date format: {str(e)}")
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return HttpResponseBadRequest(f"An error occurred: {str(e)}")

@require_http_methods(["GET"])
def get_reservation(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)
    data = {
        'id': reservation.id,
        'user': reservation.user.username,
        'testbed': reservation.testbed.name,
        'startTime': reservation.start_time.isoformat(),
        'endTime': reservation.end_time.isoformat(),
        'type': reservation.reservation_type,
        'devices': [{'id': d.id, 'name': d.name} for d in reservation.devices.all()],
        'software_image': {
            'id': reservation.software_image.id,
            'image': reservation.software_image.image
        } if reservation.software_image else None
    }
    return JsonResponse(data)

@csrf_protect
@require_http_methods(["POST"])
def update_reservation(request, reservation_id):
    try:
        with transaction.atomic():
            reservation = Reservation.objects.select_for_update().get(id=reservation_id)

            # Check if reservation is completed
            if reservation.is_completed():
                return JsonResponse({
                    'status': 'error',
                    'message': 'Cannot update a completed reservation. The reservation period has already passed.',
                }, status=403)
            
            original_data = {
                'user': reservation.user.username,
                'start_time': reservation.start_time,
                'end_time': reservation.end_time,
                'reservation_type': reservation.reservation_type,
                'software_image': reservation.software_image.image if reservation.software_image else None,
                'devices': set(reservation.devices.values_list('name', flat=True)),
                'testbed': reservation.testbed.name,  # Add testbed name to original data
            }
            
            try:
                data = json.loads(request.body.decode('utf-8'))
            except json.JSONDecodeError as e:
                logger.error(f"JSON Decode Error: {str(e)}")
                return JsonResponse({
                    'status': 'error',
                    'message': 'Invalid JSON data',
                }, status=400)
            print("Received data:", data)  # Debug log

            # Ensure user field is properly handled
            if 'user' in data:
                try:
                    user_id = int(data['user'])
                    User.objects.get(id=user_id)  # Verify user exists
                except (ValueError, User.DoesNotExist):
                    return JsonResponse({
                        'status': 'error',
                        'message': 'Invalid user selected'
                    }, status=400)


            data['testbed'] = reservation.testbed.id
            
            if 'devices' in data and not isinstance(data['devices'], list):
                data['devices'] = [data['devices']]


            form = ReservationForm(data, instance=reservation, is_update=True)
            if form.is_valid():
                updated_reservation = form.save(commit=False)
                
                if not AllowedReservationPeriod.is_period_allowed(updated_reservation.start_time, updated_reservation.end_time):
                    raise ValidationError("Updated reservation is not within allowed period.")
                
                updated_reservation._devices_to_check = form.cleaned_data['devices']

                # Explicitly set user if it's in the form
                if 'user' in form.cleaned_data:
                    updated_reservation.user = form.cleaned_data['user']
                
                updated_reservation.save()
                form.save_m2m()

                changes = []
                new_data = {
                    'user': updated_reservation.user.username,
                    'start_time': updated_reservation.start_time,
                    'end_time': updated_reservation.end_time,
                    'reservation_type': updated_reservation.reservation_type,
                    'software_image': updated_reservation.software_image.image if updated_reservation.software_image else None,
                    'devices': set(updated_reservation.devices.values_list('name', flat=True)),
                    'testbed': updated_reservation.testbed.name,  # Add testbed name to new data
                }
                
                for key in original_data:
                    if original_data[key] != new_data[key]:
                        changes.append(f"{key.replace('_', ' ').title()}: {original_data[key]} → {new_data[key]}")

                # Send Webex notification if user changed
                if original_data['user'] != new_data['user']:
                    notification_message = (
                        f"Reservation Update Notification:\n"
                        f"- Reservation ID: {reservation_id}\n"
                        f"- Testbed: {original_data['testbed']}\n"
                        f"- Start Time: {original_data['start_time']}\n"
                        f"- User changed from {original_data['user']} to {new_data['user']}"
                    )
                    send_webex_notification(notification_message)

                return JsonResponse({
                    'status': 'success',
                    'message': 'Reservation updated successfully.',
                    'changes': changes,
                    'updated_data': {
                        'software_image': new_data['software_image'],
                        'devices': list(new_data['devices']),
                        'user': new_data['user']
                    }
                })
            else:
                logger.error(f"Form validation failed: {form.errors}")
                return JsonResponse({
                    'status': 'error',
                    'message': 'Invalid form data.',
                    'errors': {field: errors[0] for field, errors in form.errors.items()}
                })
    except Reservation.DoesNotExist:
        logger.error(f"Reservation with id {reservation_id} not found")
        return JsonResponse({
            'status': 'error',
            'message': 'Reservation not found.',
        }, status=404)
    except ValidationError as e:
        logger.error(f"Validation Error: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': str(e),
        })
    except Exception as e:
        logger.exception(f"Unexpected error in update_reservation: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': 'An unexpected error occurred. Please try again later.',
        }, status=500)


def send_webex_notification(message):
    try:
        api = WebexTeamsAPI(access_token=settings.WEBEX_BOT_TOKEN)
        api.messages.create(roomId=settings.WEBEX_ROOM_ID, markdown=message)
    except Exception as e:
        logger.exception(f"Error sending Webex notification: {str(e)}")



@csrf_protect
@require_http_methods(["POST"])
def delete_reservation(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)
    reservation.delete()
    return JsonResponse({'status': 'success'})


def get_software_images(request):
    images = Software.objects.all().values('id', 'image')
    return JsonResponse(list(images), safe=False)


def get_available_devices(request):
    testbed_id = request.GET.get('testbed_id')
    start_time_str = request.GET.get('start_time')
    end_time_str = request.GET.get('end_time')
    
    # Convert string to datetime and make it timezone-aware
    start_time = timezone.make_aware(datetime.strptime(start_time_str, "%Y-%m-%d %H:%M"))
    end_time = timezone.make_aware(datetime.strptime(end_time_str, "%Y-%m-%d %H:%M"))
    
    testbed = Testbed.objects.get(id=testbed_id)
    all_devices = testbed.devices.all()
    
    unavailable_devices = Reservation.objects.filter(
        testbed=testbed,
        start_time__lt=end_time,
        end_time__gt=start_time
    ).values_list('devices', flat=True).distinct()
    
    available_devices = all_devices.exclude(id__in=unavailable_devices)
    
    return JsonResponse(list(available_devices.values('id', 'name')), safe=False)

def get_available_devices_update(request):
    testbed_name = request.GET.get('testbed_id')  # Change this to testbed_name
    start_time = parse_datetime(request.GET.get('start_time'))
    end_time = parse_datetime(request.GET.get('end_time'))
    
    # Get the testbed by name instead of ID
    testbed = get_object_or_404(Testbed, name=testbed_name)
    
    # Get all devices for the testbed
    all_devices = Device.objects.filter(testbed=testbed)
    
    # Get devices that are already reserved during this period
    reserved_devices = Reservation.objects.filter(
        testbed=testbed,
        start_time__lt=end_time,
        end_time__gt=start_time
    ).values_list('devices__id', flat=True)
    
    # Filter out reserved devices
    available_devices = all_devices.exclude(id__in=reserved_devices)
    
    return JsonResponse(list(available_devices.values('id', 'name')), safe=False)


def get_users(request):
    users = User.objects.all().values('id', 'username')
    return JsonResponse(list(users), safe=False)

def get_devices_update(request):
    testbed_name = request.GET.get('testbed_id')  # This is actually the testbed name
    testbed = get_object_or_404(Testbed, name=testbed_name)
    devices = Device.objects.filter(testbed=testbed).values('id', 'name')
    return JsonResponse(list(devices), safe=False)


def get_families(request):
    families = Family.objects.all().values('id', 'name')
    return JsonResponse(list(families), safe=False)

def get_all_testbeds(request):
    testbeds = Testbed.objects.all().values('id', 'name', 'family_id')
    return JsonResponse(list(testbeds), safe=False)

@login_required
def maintenance(request):
    return render(request, 'reservation/maintenance.html')

@login_required
def about(request):

    return render(request, 'base/about.html')

@login_required
def create_deletion_request(request, reservation_id):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            reason = data.get('reason')
            
            if not reason:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Reason is required'
                }, status=400)

            reservation = get_object_or_404(Reservation, id=reservation_id)

            # Check if start time has passed
            if timezone.now() >= reservation.start_time:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Cannot request deletion after reservation has started'
                }, status=400)
            
            # Check if there's already a pending request
            existing_request = DeletionRequest.objects.filter(
                reservation=reservation,
                status='PENDING'
            ).exists()
            
            if existing_request:
                return JsonResponse({
                    'status': 'error',
                    'message': 'A deletion request for this reservation is already pending'
                }, status=400)

            deletion_request = DeletionRequest.objects.create(
                reservation=reservation,
                requester=request.user,
                reason=reason
            )

            return JsonResponse({
                'status': 'success',
                'message': 'Deletion request submitted successfully'
            })

        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)

@login_required
def handle_deletion_request(request, request_id):
    if request.method == 'POST':
        try:
            if not request.user.is_staff:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Only administrators can handle deletion requests'
                }, status=403)

            deletion_request = get_object_or_404(DeletionRequest, id=request_id)
            data = json.loads(request.body)
            
            status = data.get('status')
            comment = data.get('comment', '')

            if status not in ['APPROVED', 'REJECTED']:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Invalid status'
                }, status=400)
            
            # Store reservation details before deletion
            reservation_details = {
                'testbed': deletion_request.reservation.testbed.name,
                'devices': [d.name for d in deletion_request.reservation.devices.all()],
                'start_time': deletion_request.reservation.start_time,
                'end_time': deletion_request.reservation.end_time,
                'requester': deletion_request.requester.username
            }

            # Handle the request (this will delete the reservation if approved)
            deletion_request.handle_request(request.user, status, comment)

            # Send Webex notification if approved
            if status == 'APPROVED':
                devices_list = ', '.join(reservation_details['devices'])
                notification_message = (
                    f"Reservation Deletion Approved\n\n"
                    f"- Testbed: {reservation_details['testbed']}\n"
                    f"- Devices: {devices_list}\n"
                    f"- Start Time: {reservation_details['start_time']}\n"
                    f"- End Time: {reservation_details['end_time']}\n"
                    f"- Originally Reserved by: {reservation_details['requester']}\n"
                    f"- Deletion Approved by: {request.user.username}\n"
                    f"- Admin Comment: {comment or 'No comment provided'}\n\n"
                    f"These resources are now available for reservation."
                )
                send_webex_notification(notification_message)

            return JsonResponse({
                'status': 'success',
                'message': f'Request {status.lower()}'
            })

        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)

@login_required
@ensure_csrf_cookie
def get_deletion_requests(request):
    """Get deletion requests for the profile page"""
    try:
        # logger.info(f"get_deletion_requests accessed by: {request.user.username}")
        # logger.info(f"Is authenticated: {request.user.is_authenticated}")
        # logger.info(f"Is staff: {request.user.is_staff}")
        
        if not request.user.is_authenticated:
            logger.error("User is not authenticated")
            return JsonResponse({'error': 'Authentication required'}, status=401)

        if request.user.is_staff:
            requests = DeletionRequest.objects.select_related(
                'requester', 
                'reservation', 
                'reservation__user', 
                'reservation__testbed'
            ).all()
            logger.info(f"Admin user {request.user.username} - Found {requests.count()} requests")
        else:
            logger.info(f"Processing for normal user: {request.user.username}")
            
            # # Get user's own requests
            # own_requests = DeletionRequest.objects.filter(requester=request.user)
            # logger.info(f"User's own requests count: {own_requests.count()}")
            
            # # Get user's reservation requests
            # reservation_requests = DeletionRequest.objects.filter(reservation__user=request.user)
            # logger.info(f"User's reservation requests count: {reservation_requests.count()}")
            
            # Combine both types of requests
            requests = DeletionRequest.objects.select_related(
                'requester', 
                'reservation', 
                'reservation__user', 
                'reservation__testbed'
            ).filter(
                Q(requester=request.user) | 
                Q(reservation__user=request.user)
            ).distinct()
            
            # logger.info(f"Total requests for user: {requests.count()}")
            # logger.info(f"SQL Query: {requests.query}")

        data = []
        for req in requests:
            request_data = {
                'id': req.id,
                'requester': req.requester.username,
                'reason': req.reason,
                'status': req.status,
                'created_at': req.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'admin_comment': req.admin_comment or '',
                'admin': req.admin.username if req.admin else None
            }

            if req.reservation:
                request_data.update({
                    'reservation_id': req.reservation.id,
                    'testbed': req.reservation.testbed.name,
                    'reservation_user': req.reservation.user.username
                })
            elif req.reservation_details:
                request_data.update({
                    'reservation_id': None,
                    'testbed': req.reservation_details.get('testbed_name', 'Deleted'),
                    'reservation_user': req.reservation_details.get('user', 'Unknown')
                })
            else:
                request_data.update({
                    'reservation_id': None,
                    'testbed': 'Unknown',
                    'reservation_user': 'Unknown'
                })
            
            data.append(request_data)
            # logger.info(f"Added request data for request ID: {req.id}")

        # logger.info(f"Returning {len(data)} requests for user {request.user.username}")
        return JsonResponse(data, safe=False)
        
    except Exception as e:
        logger.error(f"Error in get_deletion_requests: {str(e)}", exc_info=True)
        return JsonResponse({
            'error': True,
            'message': str(e)
        }, status=500)
