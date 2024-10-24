# reservation/reservation/celery.py
from __future__ import absolute_import, unicode_literals
import os
from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'reservation.settings')

app = Celery('reservation')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

# Configure the Celery beat schedule
from celery.schedules import crontab

app.conf.beat_schedule = {
    'send-reservation-notifications-every-5-minutes': {
        'task': 'reservationDashboard.tasks.send_reservation_notifications',
        'schedule': crontab(minute='*/5'),
    },
}