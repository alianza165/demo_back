# modbus/management/commands/create_default_models.py
from django.core.management.base import BaseCommand
from modbus.models import DeviceModel, ModbusRegister

class Command(BaseCommand):
    help = 'Create default device models with common register configurations'
    
    def handle(self, *args, **options):
        # Create a default energy meter model
        energy_meter, created = DeviceModel.objects.get_or_create(
            name="Standard Energy Meter",
            defaults={
                'manufacturer': 'Generic',
                'description': 'Standard three-phase energy meter with basic measurements'
            }
        )
        
        if created:
            # Define common registers for energy meters
            standard_registers = [
                # Voltage registers
                {'address': 778, 'name': 'voltage_l1_l2', 'category': 'voltage', 'unit': 'V', 'scale_factor': 10.0},
                {'address': 782, 'name': 'voltage_l1_n', 'category': 'voltage', 'unit': 'V', 'scale_factor': 10.0},
                # Current registers
                {'address': 768, 'name': 'current_l1', 'category': 'current', 'unit': 'A', 'scale_factor': 100.0},
                # Power registers
                {'address': 794, 'name': 'active_power_total', 'category': 'power', 'unit': 'kW', 'scale_factor': 100.0},
                # Frequency
                {'address': 790, 'name': 'frequency', 'category': 'frequency', 'unit': 'Hz', 'scale_factor': 10.0},
                # Add more as needed...
            ]
            
            for i, reg_data in enumerate(standard_registers):
                ModbusRegister.objects.create(
                    device_model=energy_meter,
                    order=i,
                    data_type='uint16',
                    **reg_data
                )
            
            self.stdout.write('Created default device model with standard registers')
