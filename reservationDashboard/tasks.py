# reservationDashboard/tasks.py
from celery import shared_task
from django.utils import timezone
from django.conf import settings
from .models import Reservation
from webexteamssdk import WebexTeamsAPI, ApiError
import logging
from requests.exceptions import Timeout, RequestException
from celery.exceptions import MaxRetriesExceededError
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

@shared_task
def send_reservation_notifications():
    try:
        now = timezone.now()
        # Find reservations that start exactly 5 minutes from now
        target_time = now + timezone.timedelta(minutes=5)
        
        # Convert to the same timezone-naive format for comparison
        if timezone.is_aware(target_time):
            target_time = timezone.make_naive(target_time)
            
        logger.info(f"Checking for reservations at {now}, targeting start time: {target_time}")
        
        # Query for reservations
        upcoming_reservations = Reservation.objects.filter(
            start_time__year=target_time.year,
            start_time__month=target_time.month,
            start_time__day=target_time.day,
            start_time__hour=target_time.hour,
            start_time__minute=target_time.minute,
        ).select_related('user', 'testbed').prefetch_related('devices')

        logger.info(f"Found {upcoming_reservations.count()} upcoming reservations")
        
        for reservation in upcoming_reservations:
            logger.info(f"Processing reservation {reservation.id} - Start time: {reservation.start_time}")
            send_webex_notification.delay(reservation.id)
            
    except Exception as e:
        logger.error(f"Error in send_reservation_notifications: {str(e)}")
        logger.error(f"Traceback: ", exc_info=True)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_webex_notification(self, reservation_id):
    try:
        logger.info(f"Starting to send notification for reservation {reservation_id}")
        
        # Get the reservation details
        reservation = Reservation.objects.select_related('user', 'testbed', 'software_image').prefetch_related('devices').get(id=reservation_id)
        
        # Initialize Webex API
        api = WebexTeamsAPI(access_token=settings.WEBEX_BOT_TOKEN)
        
        # Construct the user's email address
        user_email = f"{reservation.user.username}@cisco.com"
        logger.info(f"Preparing to send notification to {user_email}")
        
        # Get all devices for the message
        devices = list(reservation.devices.all())
        device_names = ', '.join(device.name for device in devices)
        
        message = (
            f"Reminder: Your reservation starts in 5 minutes!\n\n"
            f"Testbed: {reservation.testbed.name}\n"
            f"Devices: {device_names}\n"
            f"Start Time: {reservation.start_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"End Time: {reservation.end_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"Type: {reservation.reservation_type}\n"
            f"Image: {reservation.software_image.image if reservation.software_image else 'N/A'}"
        )
        
        logger.info(f"Attempting to send message for reservation {reservation_id}")
        
        try:
            # Send message and log success
            response = api.messages.create(toPersonEmail=user_email, markdown=message)
            logger.info(f"Successfully sent notification for reservation {reservation_id} to {user_email}")
            return True
            
        except ApiError as e:
            logger.error(f"Webex API error for reservation {reservation_id}: {str(e)}")
            if "Rate limit exceeded" in str(e):
                raise self.retry(countdown=60, exc=e)
            return False
            
        except (Timeout, RequestException) as e:
            logger.warning(f"Connection error while sending notification for reservation {reservation_id}: {str(e)}")
            retry_countdown = 30 * (self.request.retries + 1)
            raise self.retry(countdown=retry_countdown, exc=e)
            
    except Reservation.DoesNotExist:
        logger.error(f"Reservation {reservation_id} not found")
        return False
        
    except MaxRetriesExceededError:
        logger.error(f"Max retries exceeded for sending notification for reservation {reservation_id}")
        return False
        
    except Exception as e:
        logger.error(f"Unexpected error while sending notification for reservation {reservation_id}: {str(e)}")
        logger.error(f"Traceback: ", exc_info=True)
        return False
    



    