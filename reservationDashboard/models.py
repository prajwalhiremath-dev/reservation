from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction


class Family(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Families"

class User(models.Model):
    username = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.username

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