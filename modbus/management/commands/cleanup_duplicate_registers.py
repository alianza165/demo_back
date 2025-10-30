# modbus/management/commands/cleanup_duplicate_registers.py
from django.core.management.base import BaseCommand
from modbus.models import ModbusRegister

class Command(BaseCommand):
    help = 'Clean up registers that have both device_model and device set, keeping only the device instance'
    
    def handle(self, *args, **options):
        self.stdout.write('Cleaning up duplicate registers...')
        
        # Find registers that have both device_model and device set
        problem_registers = ModbusRegister.objects.filter(
            device_model__isnull=False,
            device__isnull=False
        )
        
        count = problem_registers.count()
        
        if count == 0:
            self.stdout.write(self.style.SUCCESS('No duplicate registers found. All good!'))
            return
        
        self.stdout.write(f'Found {count} registers with both device_model and device set.')
        
        # For each problematic register, clear the device_model (keep the device)
        for register in problem_registers:
            self.stdout.write(
                f'  - Clearing device_model from register "{register.name}" '
                f'(address: {register.address}, device: {register.device.name})'
            )
            register.device_model = None
            register.save()
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully cleaned up {count} duplicate registers!')
        )
        
        # Also find registers with neither FK set (orphaned registers)
        orphaned = ModbusRegister.objects.filter(
            device_model__isnull=True,
            device__isnull=True
        ).count()
        
        if orphaned > 0:
            self.stdout.write(
                self.style.WARNING(f'Found {orphaned} orphaned registers (no parent). '
                                 f'These will not be cleaned automatically.')
            )

