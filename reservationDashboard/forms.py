from django import forms
from .models import Reservation, AllowedReservationPeriod, DeletionRequest
from datetime import timedelta  # If you implement duration checks
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
User = get_user_model()

class CustomUserCreationForm(UserCreationForm):
    """
    Custom registration form with email field and custom styling
    """
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Enter your email'})
    )
    
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'password1', 'password2')
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add Bootstrap classes to all fields
        for field in self.fields:
            self.fields[field].widget.attrs.update({'class': 'form-control'})
            
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already registered.")
        return email

class CustomAuthenticationForm(AuthenticationForm):
    """
    Custom login form with styled widgets
    """
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Passcode'})
    )



class PasswordChangeForm(forms.Form):
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter current password'
        })
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter new password'
        })
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm new password'
        })
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        current_password = self.cleaned_data.get('current_password')
        if not self.user.check_password(current_password):
            raise ValidationError('Current password is incorrect.')
        return current_password

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        if new_password and confirm_password:
            if new_password != confirm_password:
                raise ValidationError('New passwords do not match.')
            
            # Password validation
            if len(new_password) < 8:
                raise ValidationError('Password must be at least 8 characters long.')
            if not any(char.isupper() for char in new_password):
                raise ValidationError('Password must contain at least one uppercase letter.')
            if not any(char.islower() for char in new_password):
                raise ValidationError('Password must contain at least one lowercase letter.')
            if not any(char.isdigit() for char in new_password):
                raise ValidationError('Password must contain at least one number.')
            if not any(char in '!@#$%^&*(),.?":{}|<>' for char in new_password):
                raise ValidationError('Password must contain at least one special character.')

            try:
                validate_password(new_password, self.user)
            except ValidationError as e:
                raise ValidationError(e.messages)

        return cleaned_data

class ReservationForm(forms.ModelForm):
    class Meta:
        model = Reservation
        fields = ['testbed', 'reservation_type', 'start_time', 'end_time', 
                 'software_image', 'devices', 'comments']
        widgets = {
            'testbed': forms.Select(attrs={'class': 'form-select'}),
            'reservation_type': forms.Select(attrs={'class': 'form-select'}),
            'start_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'end_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'software_image': forms.Select(attrs={'class': 'form-select', 'required': True}),
            'devices': forms.SelectMultiple(attrs={'class': 'form-select'}),
            'comments': forms.Textarea(attrs={'class': 'form-control', 'rows': 1}),
        }

    def __init__(self, *args, **kwargs):
        self.is_update = kwargs.pop('is_update', False)
        # self.request_user = kwargs.pop('request_user', None)  # Get the logged-in user
        super().__init__(*args, **kwargs)
        
         # For new reservations, don't show user field as it will be set to logged-in user
        if self.is_update:
            # Add user field for updates only
            self.fields['user'] = forms.ModelChoiceField(
                queryset=User.objects.all(),
                widget=forms.Select(attrs={'class': 'form-select'}),
                required=True,
                to_field_name='id'  # Important: use ID for the field value
            )
            # Remove testbed field for updates
            if 'testbed' in self.fields:
                del self.fields['testbed']

        self.fields['devices'].required = True

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')

        if self.is_update:
            cleaned_data['testbed'] = self.instance.testbed

            # Validate user selection
            if 'user' in cleaned_data:
                try:
                    user_id = cleaned_data['user'].id
                    user = User.objects.get(id=user_id)
                    cleaned_data['user'] = user
                except User.DoesNotExist:
                    raise forms.ValidationError("Selected user does not exist")
        
        if start_time and end_time:
            if not AllowedReservationPeriod.is_period_allowed(start_time, end_time):
                raise forms.ValidationError("Reservation is not within allowed period.")

            if end_time <= start_time:
                raise forms.ValidationError("End time must be after start time.")

        if not cleaned_data.get('devices'):
            raise forms.ValidationError("At least one device must be selected.")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        
        if commit:
            instance.save()
            self.save_m2m()
            
            # If this was an update and the user field was changed
            if self.is_update and 'user' in self.changed_data:
                # The webex notification is handled in the view
                pass
                
        return instance

class DeletionRequestForm(forms.ModelForm):
    class Meta:
        model = DeletionRequest
        fields = ['reason']
        widgets = {
            'reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Please provide a reason for deletion'
            })
        }

class HandleDeletionRequestForm(forms.ModelForm):
    class Meta:
        model = DeletionRequest
        fields = ['status', 'admin_comment']
        widgets = {
            'status': forms.Select(attrs={
                'class': 'form-select'
            }),
            'admin_comment': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Add a comment (optional)'
            })
        }
    
    