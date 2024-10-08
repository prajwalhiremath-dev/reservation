from django import forms
from .models import Reservation, AllowedReservationPeriod
from datetime import timedelta  # If you implement duration checks


class ReservationForm(forms.ModelForm):
    class Meta:
        model = Reservation
        fields = ['user', 'testbed', 'reservation_type', 'start_time', 'end_time', 'software_image', 'devices', 'comments']
        widgets = {
            'user': forms.Select(attrs={'class': 'form-select'}),
            'testbed': forms.Select(attrs={'class': 'form-select'}),
            'reservation_type': forms.Select(attrs={'class': 'form-select'}),
            'start_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'end_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'software_image': forms.Select(attrs={'class': 'form-select'}),
            'devices': forms.SelectMultiple(attrs={'class': 'form-select'}),
            'comments': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
        }

    def __init__(self, *args, **kwargs):
        self.is_update = kwargs.pop('is_update', False)
        super().__init__(*args, **kwargs)
        if self.is_update:
            del self.fields['testbed']

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')

        if self.is_update:
            # Ensure testbed is not changed during update
            cleaned_data['testbed'] = self.instance.testbed
        
        if start_time and end_time:
            # Check if the reservation is within allowed periods
            if not AllowedReservationPeriod.is_period_allowed(start_time, end_time):
                raise forms.ValidationError("Reservation is not within allowed period.")

            # Check if end time is after start time
            if end_time <= start_time:
                raise forms.ValidationError("End time must be after start time.")

            # You can add more custom validations here if needed
            # For example, check if the duration is within a certain limit
            # if (end_time - start_time) > timedelta(hours=24):
            #     raise forms.ValidationError("Reservation cannot exceed 24 hours.")

        return cleaned_data





    
    