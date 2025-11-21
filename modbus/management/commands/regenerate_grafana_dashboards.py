from django.core.management.base import BaseCommand
from modbus.models import ModbusDevice
from modbus.grafana_manager import GrafanaConfigurationManager
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Regenerate all Grafana dashboards for all devices'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--device-id',
            type=int,
            help='Regenerate dashboard for a specific device ID only'
        )
    
    def handle(self, *args, **options):
        try:
            grafana_manager = GrafanaConfigurationManager()
            
            # Ensure datasource exists first
            self.stdout.write("Ensuring InfluxDB datasource exists in Grafana...")
            if not grafana_manager.ensure_datasource_exists():
                self.stdout.write(
                    self.style.ERROR('Failed to ensure datasource exists')
                )
                return
            
            # Get devices
            if options['device_id']:
                devices = ModbusDevice.objects.filter(id=options['device_id'])
                if not devices.exists():
                    self.stdout.write(
                        self.style.ERROR(f'Device with ID {options["device_id"]} not found')
                    )
                    return
            else:
                devices = ModbusDevice.objects.all()
            
            self.stdout.write(f"Found {devices.count()} device(s) to process")
            self.stdout.write("=" * 60)
            
            success_count = 0
            failed_count = 0
            
            for device in devices:
                self.stdout.write(f"Regenerating dashboard for: {device.name} (ID: {device.id})")
                try:
                    success, result = grafana_manager.create_or_update_device_dashboard(device)
                    if success:
                        self.stdout.write(
                            self.style.SUCCESS(f'  ✓ Success: {result}')
                        )
                        success_count += 1
                    else:
                        self.stdout.write(
                            self.style.ERROR(f'  ✗ Failed: {result}')
                        )
                        failed_count += 1
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'  ✗ Error: {str(e)}')
                    )
                    logger.error(f"Error regenerating dashboard for {device.name}: {e}")
                    failed_count += 1
                self.stdout.write("")
            
            self.stdout.write("=" * 60)
            self.stdout.write(
                self.style.SUCCESS(f'Completed: {success_count} succeeded, {failed_count} failed')
            )
                
        except Exception as e:
            logger.error(f"Error in regenerate_grafana_dashboards command: {e}")
            self.stdout.write(
                self.style.ERROR(f'Command failed: {e}')
            )

