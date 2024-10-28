from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password
from reservationDashboard.models import User

class Command(BaseCommand):
    help = 'Setup users and update passwords'

    def handle(self, *args, **kwargs):
        # Update existing users
        for user in User.objects.all():
            # Skip special users that already have defined passwords
            if user.username in ['guest', 'admin', 'aprajwal']:
                continue
                
            # Set temporary password as username + "@123"
            temp_password = f"{user.username}@123"
            user.password = make_password(temp_password)
            user.save()
            self.stdout.write(self.style.SUCCESS(
                f'Updated user {user.username} with temporary password: {temp_password}'
            ))

        # Ensure special users exist with correct passwords
        admin_user, created = User.objects.update_or_create(
            username='admin',
            defaults={
                'email': 'admin@example.com',
                'is_staff': True,
                'is_superuser': True,
                'password': make_password('admin@123')
            }
        )
        
        user, created = User.objects.update_or_create(
            username='aprajwal',
            defaults={
                'email': 'aprajwal@example.com',
                'is_staff': False,
                'is_superuser': False,
                'password': make_password('aprajwal@123')
            }
        )
        
        guest_user, created = User.objects.update_or_create(
            username='guest',
            defaults={
                'email': 'guest@example.com',
                'is_staff': False,
                'is_superuser': False,
                'is_guest': True,
                'password': make_password('Guestuser@12345')
            }
        )

        self.stdout.write(self.style.SUCCESS('Successfully setup all users'))

        # Print temporary passwords for all users
        self.stdout.write(self.style.WARNING('\nTemporary passwords for users:'))
        for user in User.objects.all():
            if user.username not in ['guest', 'admin', 'aprajwal']:
                self.stdout.write(f"{user.username}: {user.username}@123")

        self.stdout.write(self.style.WARNING(
            '\nPlease ask users to change their passwords upon first login.'
        ))