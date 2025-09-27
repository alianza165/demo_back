# modbus/views.py
import time
import json
import os
import subprocess
from pathlib import Path
import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.http import JsonResponse
from .models import DeviceModel, ModbusDevice, ModbusRegister, ConfigurationLog
from .serializers import (
    DeviceModelSerializer, ModbusDeviceSerializer, ModbusDeviceCreateSerializer,
    ConfigurationLogSerializer
)

logger = logging.getLogger(__name__)

class DeviceModelViewSet(viewsets.ModelViewSet):
    queryset = DeviceModel.objects.all()
    serializer_class = DeviceModelSerializer
    permission_classes = [AllowAny]

class ModusDeviceViewSet(viewsets.ModelViewSet):
    queryset = ModbusDevice.objects.all().prefetch_related('registers')
    permission_classes = [AllowAny]
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ModbusDeviceCreateSerializer
        return ModbusDeviceSerializer
    
    @action(detail=True, methods=['post'])
    def apply_configuration(self, request, pk=None):
        """Apply configuration for a specific device (includes all active devices)"""
        device = self.get_object()
        
        config_log = ConfigurationLog.objects.create(
            device=device,
            status='pending'
        )
        
        try:
            # Get ALL active devices to include in the config
            active_devices = ModbusDevice.objects.filter(is_active=True)
            
            logger.info(f"Applying configuration for {active_devices.count()} active devices")
            # Generate configuration file with ALL active devices
            config_data = self.generate_multi_device_config(active_devices)
            
            # Write configuration to file
            success = self.write_configuration_file(config_data)
            
            if success:
                config_log.status = 'applied'
                config_log.log_message = f"Configuration applied for {active_devices.count()} active devices"
                config_log.save()
                
                device_names_list = [device.name for device in active_devices]  # Changed to device_names_list
                logger.info(f"Configuration applied for devices: {', '.join(device_names_list)}")
                
                return Response({
                    'status': 'success', 
                    'message': f'Configuration applied for {active_devices.count()} active devices. The modbus service will automatically reload.',
                    'log_id': config_log.id,
                    'devices_applied': active_devices.count(),
                    'device_names': device_names_list
                })
            else:
                config_log.status = 'failed'
                config_log.log_message = "Failed to write configuration file"
                config_log.save()
                
                return Response({
                    'status': 'error', 
                    'message': 'Failed to write configuration file'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            config_log.status = 'failed'
            config_log.log_message = str(e)
            config_log.save()

            logger.error(f"Error applying configuration: {e}")
            
            return Response({
                'status': 'error', 
                'message': f'Error applying configuration: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'])
    def apply_all_configurations(self, request):
        """Apply configuration for all active devices at once"""
        try:
            active_devices = ModbusDevice.objects.filter(is_active=True)
            
            if not active_devices.exists():
                return Response({
                    'status': 'error', 
                    'message': 'No active devices found'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            config_data = self.generate_multi_device_config(active_devices)
            success = self.write_configuration_file(config_data)
            
            if success:
                # Create log entry for the operation
                device_names = [device.name for device in active_devices]
                logger.info(f"Configuration applied for all {active_devices.count()} active devices: {', '.join(device_names)}")

                
                return Response({
                    'status': 'success', 
                    'message': f'Configuration applied for {active_devices.count()} active devices',
                    'devices_count': active_devices.count(),
                    'device_names': device_names
                })
            else:
                return Response({
                    'status': 'error', 
                    'message': 'Failed to write configuration file'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            logger.error(f"Error applying all configurations: {e}")
            return Response({
                'status': 'error', 
                'message': f'Error applying configurations: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['get'])
    def config_logs(self, request, pk=None):
        """Get configuration logs for a specific device"""
        device = self.get_object()
        logs = ConfigurationLog.objects.filter(device=device).order_by('-created_at')
        serializer = ConfigurationLogSerializer(logs, many=True)
        return Response(serializer.data)
    
    def update(self, request, *args, **kwargs):
        # Get the device before update to check if is_active is changing
        device_id = kwargs.get('pk')
        old_is_active = None
        if device_id:
            try:
                old_device = ModbusDevice.objects.get(id=device_id)
                old_is_active = old_device.is_active
            except ModbusDevice.DoesNotExist:
                pass
        
        # Perform the update
        response = super().update(request, *args, **kwargs)
        
        # If the update was successful, check if we need to apply config
        if response.status_code == status.HTTP_200_OK and device_id:
            try:
                device = ModbusDevice.objects.get(id=device_id)
                new_is_active = device.is_active
                
                # Only auto-apply if is_active status changed
                if old_is_active is not None and old_is_active != new_is_active:
                    active_devices = ModbusDevice.objects.filter(is_active=True)
                    config_data = self.generate_multi_device_config(active_devices)
                    success = self.write_configuration_file(config_data)
                    
                    if success:
                        logger.info(f"Auto-applied configuration after device {device.name} activation change: {old_is_active} -> {new_is_active}")
                    else:
                        logger.error(f"Failed to auto-apply configuration after device {device.name} update")
                
            except Exception as e:
                logger.error(f"Error in update post-processing: {e}")
        
        return response
    
    def generate_multi_device_config(self, devices):
        """Generate configuration for multiple devices on the same RS485 bus"""
        # Determine common settings from the first active device or use defaults
        first_device = devices.first()
        if first_device:
            global_port = first_device.port
            global_baudrate = first_device.baud_rate
            global_parity = first_device.parity
            global_stopbits = first_device.stop_bits
            global_bytesize = first_device.byte_size
            global_timeout = first_device.timeout
        else:
            # Default values if no devices
            global_port = '/dev/ttyUSB0'
            global_baudrate = 9600
            global_parity = 'N'
            global_stopbits = 1
            global_bytesize = 8
            global_timeout = 3
        
        config_data = {
            'devices': {},
            'global_config': {
                'port': global_port,
                'baudrate': global_baudrate,
                'stopbits': global_stopbits,
                'bytesize': global_bytesize,
                'parity': global_parity,
                'timeout': global_timeout
            }
        }
        
        for device in devices:
            device_config = {
                'name': device.name,
                'slave_id': device.address,  # Unique address for each device
                'parameters': {}
            }
            
            # Add device-specific config if different from global
            if device.port != global_port:
                device_config['port'] = device.port
            if device.baud_rate != global_baudrate:
                device_config['baudrate'] = device.baud_rate
            if device.parity != global_parity:
                device_config['parity'] = device.parity
            if device.stop_bits != global_stopbits:
                device_config['stopbits'] = device.stop_bits
            if device.byte_size != global_bytesize:
                device_config['bytesize'] = device.byte_size
            if device.timeout != global_timeout:
                device_config['timeout'] = device.timeout
            
            # Add registers as parameters
            for register in device.registers.filter(is_active=True).order_by('order'):
                device_config['parameters'][register.address] = (
                    register.name,
                    register.scale_factor,
                    register.unit or ''
                )
            
            config_data['devices'][f'device_{device.id}'] = device_config
        
        return config_data
    
    def write_configuration_file(self, config_data):
        """Write configuration to /etc/modbus_monitor/config.json"""
        try:
            config_dir = Path('/etc/modbus_monitor')
            config_file = config_dir / 'config.json'
            
            # Ensure directory exists
            config_dir.mkdir(parents=True, exist_ok=True)
            
            # Write configuration file
            with open(config_file, 'w') as f:
                json.dump(config_data, f, indent=2)
            
            # Set proper permissions
            os.chmod(config_file, 0o644)
            
            # Change ownership to the service user
            subprocess.run(['sudo', 'chown', 'debian:debian', str(config_file)], check=True)
            
            logger.info(f"Configuration file written to {config_file}")
            logger.info(f"Configuration includes {len(config_data['devices'])} devices")
            
            # Log the device names for verification
            device_names = [device_config['name'] for device_config in config_data['devices'].values()]
            logger.info(f"Configured devices: {', '.join(device_names)}")
            
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Permission error writing configuration file: {e}")
            # Try without sudo chown
            try:
                os.chmod(config_file, 0o666)
                logger.info("Used alternative permission setting")
                return True
            except Exception as e2:
                logger.error(f"Alternative permission setting also failed: {e2}")
                return False
        except Exception as e:
            logger.error(f"Error writing configuration file: {e}")
            return False
    
    def restart_modbus_service(self):
        """Restart the modbus-monitor service to apply changes"""
        try:
            logger.info("Attempting to restart modbus-monitor service...")
            
            # Use a single restart command
            restart_result = subprocess.run(
                ['sudo', 'systemctl', 'restart', 'modbus-monitor.service'],
                capture_output=True, 
                text=True, 
                timeout=30
            )
            
            logger.info(f"Restart result: {restart_result.returncode}")
            
            if restart_result.returncode == 0:
                logger.info("Modbus service restart command executed successfully")
                
                # Wait a moment and check status
                time.sleep(3)
                
                status_result = subprocess.run(
                    ['systemctl', 'is-active', 'modbus-monitor.service'],
                    capture_output=True, 
                    text=True
                )
                
                if status_result.returncode == 0:
                    logger.info("Modbus service is active and running")
                    return True
                else:
                    logger.warning("Restart command succeeded but service may not be active")
                    return True
            else:
                logger.error(f"Restart command failed: {restart_result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("Service restart timed out")
            return False
        except Exception as e:
            logger.error(f"Error restarting service: {e}")
            return False

class ConfigurationLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ConfigurationLog.objects.all().order_by('-created_at')
    serializer_class = ConfigurationLogSerializer
    permission_classes = [AllowAny]

# Health check endpoints
def health_check(request):
    """Basic health check"""
    return JsonResponse({
        'status': 'healthy',
        'service': 'modbus-monitor-api',
        'timestamp': time.time(),
        'active_devices': ModbusDevice.objects.filter(is_active=True).count()
    })

def influxdb_health_check(request):
    """InfluxDB health check"""
    try:
        from influxdb_client import InfluxDBClient
        client = InfluxDBClient(
            url='http://localhost:8086',
            token='PQF2DMjfNtn__ooeubqDTUaiXegywYbzUBNyTjpvd7qoUrmq9PpGVyS8lybnmf-sszI7V1HEwZWdSvgkEGfzcQ==',
            org='DATABRIDGE'
        )
        health = client.health()
        return JsonResponse({
            'status': 'healthy' if health.status == 'pass' else 'unhealthy',
            'message': health.message,
            'influxdb_status': health.status
        })
    except Exception as e:
        return JsonResponse({
            'status': 'unhealthy',
            'error': str(e)
        }, status=500)

def modbus_health_check(request):
    """Modbus service health check"""
    try:
        # Check if the service is running
        result = subprocess.run(
            ['systemctl', 'is-active', 'modbus-monitor.service'],
            capture_output=True, 
            text=True
        )
        
        is_active = result.returncode == 0
        
        # Check if config file exists
        config_exists = os.path.exists('/etc/modbus_monitor/config.json')
        
        return JsonResponse({
            'status': 'healthy' if is_active else 'unhealthy',
            'service_active': is_active,
            'config_file_exists': config_exists,
            'service_status': result.stdout.strip() if is_active else result.stderr.strip()
        })
    except Exception as e:
        return JsonResponse({
            'status': 'unhealthy',
            'error': str(e)
        }, status=500)

def config_status(request):
    """Check current configuration status"""
    try:
        config_path = '/etc/modbus_monitor/config.json'
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config_data = json.load(f)
            
            return JsonResponse({
                'status': 'configured',
                'devices_count': len(config_data.get('devices', {})),
                'device_names': [device['name'] for device in config_data.get('devices', {}).values()],
                'global_config': config_data.get('global_config', {})
            })
        else:
            return JsonResponse({
                'status': 'not_configured',
                'message': 'Configuration file does not exist'
            })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'error': str(e)
        }, status=500)
