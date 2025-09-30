from django.core.management.base import BaseCommand
from modbus.models import RegisterTemplate

class Command(BaseCommand):
    help = 'Seed database with common energy meter register templates'

    def handle(self, *args, **options):
        templates = [
            # Voltage
            {'name': 'Voltage L1-L2', 'address': 778, 'data_type': 'uint16', 'scale_factor': 10.0, 'unit': 'V', 'category': 'voltage'},
            {'name': 'Voltage L1-N', 'address': 782, 'data_type': 'uint16', 'scale_factor': 10.0, 'unit': 'V', 'category': 'voltage'},
            # Current
            {'name': 'Current Phase 1', 'address': 768, 'data_type': 'uint16', 'scale_factor': 100.0, 'unit': 'A', 'category': 'current'},
            # Power
            {'name': 'Total Active Power', 'address': 804, 'data_type': 'int32', 'scale_factor': 10.0, 'unit': 'kW', 'category': 'power'},
            # Frequency
            {'name': 'Frequency', 'address': 790, 'data_type': 'uint16', 'scale_factor': 10.0, 'unit': 'Hz', 'category': 'frequency'},
            # ... add more templates
        ]

        for template_data in templates:
            RegisterTemplate.objects.get_or_create(
                name=template_data['name'],
                defaults=template_data
            )

        self.stdout.write(self.style.SUCCESS('Successfully seeded register templates'))
