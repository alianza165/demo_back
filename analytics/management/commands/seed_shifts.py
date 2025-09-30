from django.core.management.base import BaseCommand
from analytics.models import ShiftDefinition

class Command(BaseCommand):
    help = 'Create sample shift definitions'
    
    def handle(self, *args, **options):
        shifts = [
            {
                'name': 'Morning Shift',
                'description': '8 AM to 4 PM shift',
                'shift_start': '08:00:00',
                'shift_end': '16:00:00',
                'days_of_week': [0, 1, 2, 3, 4],  # Mon-Fri
                'product_type': 'Widget A',
                'units_produced': 1000,
                'tariff_rate': 0.15
            },
            {
                'name': 'Evening Shift', 
                'description': '4 PM to 12 AM shift',
                'shift_start': '16:00:00',
                'shift_end': '00:00:00',
                'days_of_week': [0, 1, 2, 3, 4],  # Mon-Fri
                'product_type': 'Widget B',
                'units_produced': 800,
                'tariff_rate': 0.15
            },
            {
                'name': 'Weekend Shift',
                'description': 'Weekend production',
                'shift_start': '06:00:00',
                'shift_end': '18:00:00',
                'days_of_week': [5, 6],  # Sat-Sun
                'product_type': 'Special Widget',
                'units_produced': 500,
                'tariff_rate': 0.12  # Lower weekend rate
            }
        ]
        
        for shift_data in shifts:
            shift, created = ShiftDefinition.objects.get_or_create(
                name=shift_data['name'],
                defaults=shift_data
            )
            if created:
                self.stdout.write(f"Created shift: {shift.name}")
            else:
                self.stdout.write(f"Shift already exists: {shift.name}")
        
        self.stdout.write(self.style.SUCCESS('Successfully seeded shift definitions'))
