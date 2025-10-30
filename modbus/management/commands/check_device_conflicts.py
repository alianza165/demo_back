# modbus/management/commands/check_device_conflicts.py
from django.core.management.base import BaseCommand
from django.db.models import Count
from modbus.models import ModbusDevice

class Command(BaseCommand):
    help = 'Check for duplicate slave IDs and conflicts in device configuration'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--fix',
            action='store_true',
            help='Automatically reassign unique slave IDs',
        )
    
    def handle(self, *args, **options):
        self.stdout.write('Checking for device configuration conflicts...\n')
        
        # Check for duplicate slave IDs
        active_devices = ModbusDevice.objects.filter(is_active=True).order_by('address')
        
        # Group by slave ID (device.address)
        slave_id_groups = {}
        for device in active_devices:
            slave_id = device.address
            if slave_id not in slave_id_groups:
                slave_id_groups[slave_id] = []
            slave_id_groups[slave_id].append(device)
        
        # Find conflicts
        conflicts = {sid: devices for sid, devices in slave_id_groups.items() if len(devices) > 1}
        
        if conflicts:
            self.stdout.write(self.style.ERROR(f'\n⚠️  Found {len(conflicts)} duplicate slave IDs:\n'))
            
            for slave_id, devices in conflicts.items():
                self.stdout.write(self.style.WARNING(f'  Slave ID {slave_id} is used by:'))
                for device in devices:
                    self.stdout.write(f'    - {device.name} (ID: {device.id})')
                self.stdout.write('')
            
            # Offer to fix
            if options['fix']:
                self.stdout.write(self.style.SUCCESS('Auto-fixing conflicts...'))
                self.fix_conflicts(active_devices)
            else:
                self.stdout.write(self.style.WARNING(
                    '\nRun with --fix to automatically reassign unique slave IDs.'
                ))
        else:
            self.stdout.write(self.style.SUCCESS('✓ No slave ID conflicts found. All devices have unique IDs.'))
        
        # Show current configuration
        self.stdout.write('\n📋 Current Active Device Configuration:\n')
        for device in active_devices:
            self.stdout.write(
                f'  {device.name:30} | Slave ID: {device.address:2} | Port: {device.port}'
            )
    
    def fix_conflicts(self, devices):
        """Reassign slave IDs to resolve conflicts"""
        # Assign sequential IDs starting from 1
        current_id = 1
        reassigned = []
        
        for device in devices:
            old_id = device.address
            device.address = current_id
            device.save()
            
            if old_id != current_id:
                reassigned.append((device.name, old_id, current_id))
            
            current_id += 1
        
        if reassigned:
            self.stdout.write(self.style.SUCCESS(f'\n✓ Reassigned {len(reassigned)} devices:\n'))
            for name, old_id, new_id in reassigned:
                self.stdout.write(f'  {name}: {old_id} → {new_id}')
        else:
            self.stdout.write(self.style.SUCCESS('\n✓ All devices already have unique IDs.'))
        
        self.stdout.write(
            self.style.WARNING(
                '\n⚠️  Remember to regenerate config with: '
                'POST /api/modbus/devices/apply_all_configurations/'
            )
        )

