from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.hashers import make_password

class Family(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Families"

class User(AbstractUser):
    is_guest = models.BooleanField(default=False)
    force_password_change = models.BooleanField(default=False)  # Default is False for new registrations
    
    class Meta:
        db_table = 'reservationDashboard_user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return self.username

    def save(self, *args, **kwargs):
        # Ensure password is hashed before saving
        if self.password and not self.password.startswith(('pbkdf2_sha256$', 'bcrypt$', 'argon2')):
            self.password = make_password(self.password)
        super().save(*args, **kwargs)

class Testbed(models.Model):
    family = models.ForeignKey(Family, related_name='testbeds', on_delete=models.CASCADE)
    name = models.CharField(max_length=100, unique=True)
    total_devices = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.name} ({self.family.name})"

class Device(models.Model):
    family = models.ForeignKey(Family, related_name='devices', on_delete=models.CASCADE)
    testbed = models.ForeignKey(Testbed, related_name='devices', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    mgmt = models.CharField(max_length=100, blank=True, null=True)
    console = models.CharField(max_length=100, blank=True, null=True)
    gateway = models.CharField(max_length=100, blank=True, null=True)
    is_eor = models.BooleanField(default=False)
    mgmt2_standby = models.CharField(max_length=100, blank=True, null=True)
    console2_standby = models.CharField(max_length=100, blank=True, null=True)
    platform_details = models.CharField(max_length=200, blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.testbed.name})"

class Software(models.Model):
    image = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.image

from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction

class Reservation(models.Model):
    RESERVATION_TYPES = [
        ('Integration', 'Integration'),
        ('Regression', 'Regression'),
        ('Priority', 'Priority')
    ]

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, related_name='reservations', on_delete=models.CASCADE)
    testbed = models.ForeignKey(Testbed, related_name='reservations', on_delete=models.CASCADE)
    devices = models.ManyToManyField(Device, blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    reservation_type = models.CharField(max_length=20, choices=RESERVATION_TYPES)
    software_image = models.ForeignKey(Software, on_delete=models.SET_NULL, null=True, blank=True)
    comments = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    version = models.IntegerField(default=0)

    class Meta:
        ordering = ['-created_at']
        '''
        Removed the UniqueConstraint: This constraint was preventing overlapping reservations on the same testbed, 
        even when different devices were being reserved. By removing it, we allow multiple reservations on the same 
        testbed as long as the devices don't conflict.
        '''
        # constraints = [
        #     models.UniqueConstraint(
        #         fields=['testbed', 'start_time', 'end_time'],
        #         name='unique_testbed_reservation'
        #     )
        # ]

    def __str__(self):
        return f"{self.user.username} - {self.testbed.name} ({self.start_time} to {self.end_time})"
    
    #Added to restrict the update 
    def is_completed(self):
        """Check if the reservation period has passed"""
        return self.end_time < timezone.now()
    
    def clean(self):
        super().clean()
        if not hasattr(self, '_devices_to_check'):
            self._devices_to_check = []

        '''
        Removed the validate_unique check in the clean method: This check was related to the removed constraint and is no longer necessary.
        '''
        
        # try:
        #     self.validate_unique()
        # except ValidationError as e:
        #     if 'unique_together' in str(e):
        #         raise ValidationError("A reservation for this testbed already exists during the selected time period.")
        
        self._check_availability(self._devices_to_check)

    def _check_availability(self, devices_to_check):
        available, unavailable_devices = self.__class__.check_availability(
            self.testbed, devices_to_check, self.start_time, self.end_time,
            exclude_reservation_id=self.pk
        )
        
        if not available:
            raise ValidationError(f"The following devices are not available during the selected time: {', '.join(str(d) for d in unavailable_devices)}")

    @classmethod
    def check_availability(cls, testbed, devices, start_time, end_time, exclude_reservation_id=None):
        with transaction.atomic():
            overlapping_reservations = cls.objects.filter(
                testbed=testbed,
                start_time__lt=end_time,
                end_time__gt=start_time,
            )
            if exclude_reservation_id:
                overlapping_reservations = overlapping_reservations.exclude(pk=exclude_reservation_id)
            
            #overlapping_reservations = overlapping_reservations.select_for_update().prefetch_related('devices') #checking with bug case_1_and_case_2
            #from here the code is changed
            overlapping_reservations = overlapping_reservations.select_for_update()

            # Quick check for any overlapping reservations
            if overlapping_reservations.exists():
                 # Proceed with detailed device availability check
                overlapping_reservations = overlapping_reservations.prefetch_related('devices')

                unavailable_devices = set()
                for reservation in overlapping_reservations:
                    unavailable_devices.update(reservation.devices.all())
                
                # Check if any of the requested devices are unavailable
                requested_devices = set(devices)
                conflicting_devices = requested_devices.intersection(unavailable_devices)
                
                if conflicting_devices:
                    return False, conflicting_devices
            return True, set()

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        if hasattr(self, '_devices_to_check'):
            self.devices.set(self._devices_to_check)
            del self._devices_to_check

class AllowedReservationPeriod(models.Model):
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()

    def __str__(self):
        return f"Reservation period: {self.start_datetime} to {self.end_datetime}"

    def clean(self):
        if self.end_datetime <= self.start_datetime:
            raise ValidationError("End datetime should be after start datetime.")

    def is_within_allowed_period(self, start_datetime, end_datetime):
        return self.start_datetime <= start_datetime and self.end_datetime >= end_datetime

    @classmethod
    def is_period_allowed(cls, start_datetime, end_datetime):
        allowed_periods = cls.objects.filter(
            start_datetime__lte=start_datetime,
            end_datetime__gte=end_datetime
        )
        return allowed_periods.exists()

class DeletionRequest(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected')
    ]

    reservation = models.ForeignKey(Reservation, on_delete=models.SET_NULL, null=True, related_name='deletion_requests')
    # Add fields to store reservation details
    reservation_details = models.JSONField(null=True, blank=True)  # Store reservation details before deletion
    requester = models.ForeignKey(User, on_delete=models.CASCADE, related_name='deletion_requests')
    admin = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='handled_requests')
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    admin_comment = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        if self.reservation:
            return f"Delete request for {self.reservation} by {self.requester}"
        return f"Delete request (Approved) by {self.requester} - {self.reservation_details.get('testbed_name', 'Unknown')}"
        
    def handle_request(self, admin, status, comment=None):
        """Handle the deletion request"""
        self.admin = admin
        self.status = status
        self.admin_comment = comment
        if status == 'APPROVED' and self.reservation:
            # Store reservation details before deleting
            self.reservation_details = {
                'testbed_name': self.reservation.testbed.name,
                'devices': list(self.reservation.devices.values_list('name', flat=True)),
                'start_time': self.reservation.start_time.isoformat(),
                'end_time': self.reservation.end_time.isoformat(),
                'user': self.reservation.user.username,
                'reservation_type': self.reservation.reservation_type,
                'software_image': self.reservation.software_image.image if self.reservation.software_image else None,
            }
            # Delete the reservation
            self.reservation.delete()
            self.reservation = None  # Set to None since it's deleted
            
        self.save()
