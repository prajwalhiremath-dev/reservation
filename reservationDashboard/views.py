from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponseBadRequest
from .models import User, Family, Testbed, Device, Software, Reservation, AllowedReservationPeriod
from .forms import ReservationForm
from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_datetime
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from django.db.models import Prefetch
from django.views.decorators.http import require_http_methods
from django.core.serializers.json import DjangoJSONEncoder
from django.views.decorators.csrf import csrf_exempt, csrf_protect
import json
import traceback
from django.http import HttpResponseServerError
from webexteamssdk import WebexTeamsAPI
from django.conf import settings
import logging
logger = logging.getLogger(__name__)

def test(request):
    context = {
        'page_title': 'Cisco Dashboard',
        'page_subtitle': 'Testbed Reservation'
    }
    return render(request, 'base/index.html', context=context)


@transaction.atomic
def make_reservation(request):
    if request.method == 'POST':
        try:
            form = ReservationForm(request.POST)
            if form.is_valid():
                try:
                    with transaction.atomic():
                        reservation = form.save(commit=False)
                        
                        if not AllowedReservationPeriod.is_period_allowed(reservation.start_time, reservation.end_time):
                            return JsonResponse({'success': False, 'error': "Reservation is not within allowed period."})
                        
                        devices_to_lock = Device.objects.filter(id__in=form.cleaned_data['devices'])
                        devices_to_lock.select_for_update()
                        
                        # Set _devices_to_check before saving
                        reservation._devices_to_check = form.cleaned_data['devices']

                        reservation.full_clean()  # This will trigger the clean method
                        reservation.save()  # This will now handle setting the devices
                    return JsonResponse({'success': True})
                except ValidationError as e:
                    error_message = e.messages[0] if isinstance(e.messages, list) else str(e)
                    return JsonResponse({'success': False, 'error': error_message})
            else:
                errors = form.errors.as_text()
                return JsonResponse({'success': False, 'error': errors})
        except Exception as e:
            logger.error(f"Unexpected error in make_reservation: {str(e)}\n{traceback.format_exc()}")
            return JsonResponse({'success': False, 'error': 'An unexpected error occurred. Please try again.'}, status=500)
    else:
        form = ReservationForm()
 
    context = {
        'form': form,
        'users': User.objects.all(),
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

            data['testbed'] = reservation.testbed.id
            
            if 'devices' in data and not isinstance(data['devices'], list):
                data['devices'] = [data['devices']]

            form = ReservationForm(data, instance=reservation, is_update=True)
            if form.is_valid():
                updated_reservation = form.save(commit=False)
                
                if not AllowedReservationPeriod.is_period_allowed(updated_reservation.start_time, updated_reservation.end_time):
                    raise ValidationError("Updated reservation is not within allowed period.")
                
                updated_reservation._devices_to_check = form.cleaned_data['devices']
                
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
                        'devices': list(new_data['devices'])
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
