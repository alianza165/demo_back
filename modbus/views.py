# modbus/views.py
import time
import json
import os
import subprocess
from pathlib import Path
import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.http import JsonResponse
from .models import DeviceModel, ModbusDevice, ModbusRegister, ConfigurationLog
from .serializers import (
    DeviceModelSerializer, ModbusDeviceSerializer, ModbusDeviceCreateSerializer,
    ConfigurationLogSerializer, DeviceModelWithRegistersSerializer
)
from .grafana_manager import GrafanaConfigurationManager
from django.utils import timezone

logger = logging.getLogger(__name__)


class DeviceModelWithRegistersViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet specifically for device models with their registers"""
    queryset = DeviceModel.objects.all().prefetch_related('register_templates')
    serializer_class = DeviceModelWithRegistersSerializer
    permission_classes = [AllowAny]
    
    # Optional: Add filtering
    def get_queryset(self):
        queryset = DeviceModel.objects.all().prefetch_related('register_templates')
        
        # Filter by active status if provided
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            is_active = is_active.lower() == 'true'
            queryset = queryset.filter(is_active=is_active)
            
        return queryset

class DeviceModelViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for predefined device models"""
    queryset = DeviceModel.objects.filter(is_active=True)
    permission_classes = [AllowAny]
    
    def list(self, request):
        """Get list of all active device models"""
        device_models = DeviceModel.objects.filter(is_active=True).order_by('manufacturer', 'name')
        
        data = [
            {
                'id': model.id,
                'name': model.name,
                'manufacturer': model.manufacturer,
                'model_number': model.model_number,
                'description': model.description,
            }
            for model in device_models
        ]
        
        return Response(data)
    
    @action(detail=True, methods=['get'])
    def registers(self, request, pk=None):
        """Get registers for a specific device model"""
        device_model = self.get_object()
        registers = ModbusRegister.objects.filter(
            device_model=device_model, 
            is_active=True
        ).order_by('order', 'address')
        
        data = [
            {
                'id': reg.id,
                'address': reg.address,
                'name': reg.name,
                'data_type': reg.data_type,
                'scale_factor': reg.scale_factor,
                'unit': reg.unit,
                'category': reg.category,
                'visualization_type': reg.visualization_type,
            }
            for reg in registers
        ]
        
        return Response(data)


def device_models_list(request):
    """Get list of all active device models"""
    device_models = DeviceModel.objects.filter(is_active=True).order_by('manufacturer', 'name')
    
    data = [
        {
            'id': model.id,
            'name': model.name,
            'manufacturer': model.manufacturer,
            'model_number': model.model_number,
            'description': model.description,
        }
        for model in device_models
    ]
    
    return JsonResponse(data, safe=False)

class ModbusDeviceViewSet(viewsets.ModelViewSet):
    queryset = ModbusDevice.objects.all().prefetch_related('registers')
    permission_classes = [AllowAny]
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ModbusDeviceCreateSerializer
        return ModbusDeviceSerializer
    
    @action(detail=True, methods=['post'])
    def apply_configuration(self, request, pk=None):
        device = self.get_object()
        config_log = ConfigurationLog.objects.create(device=device, status='pending')
        
        try:
            # Get ALL active devices (your existing code)
            active_devices = ModbusDevice.objects.filter(is_active=True)
            config_data = self.generate_multi_device_config(active_devices)
            success = self.write_configuration_file(config_data)
            
            if success:
                # NEW: Update Grafana dashboards
                grafana_manager = GrafanaConfigurationManager()
                grafana_success, grafana_result = grafana_manager.update_device_dashboards(active_devices)
                
                # Update device records with Grafana URLs
                if grafana_success:
                    for device in active_devices:
                        if device.id in grafana_result and grafana_result[device.id]:
                            device.grafana_dashboard_url = grafana_result[device.id]
                            device.last_grafana_sync = timezone.now()
                            device.save()
                
                config_log.status = 'applied'
                message = f"Configuration applied for {active_devices.count()} active devices"
                
                if grafana_success:
                    message += " and Grafana dashboards updated"
                else:
                    message += f" (Grafana update failed: {grafana_result})"
                
                config_log.log_message = message
                config_log.save()
                
                return Response({
                    'status': 'success', 
                    'message': message,
                    'log_id': config_log.id,
                    'devices_applied': active_devices.count(),
                    'device_names': [device.name for device in active_devices],
                    'grafana_updated': grafana_success,
                    'grafana_message': grafana_result if not grafana_success else "Dashboards updated successfully"
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
    def grafana_dashboard(self, request, pk=None):
        """Get Grafana dashboard URL for a device"""
        device = self.get_object()
        
        if device.grafana_dashboard_url:
            return Response({
                'dashboard_url': device.grafana_dashboard_url,
                'device_name': device.name,
                'last_sync': device.last_grafana_sync
            })
        else:
            return Response({
                'error': 'No Grafana dashboard configured for this device',
                'device_name': device.name
            }, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['get'])
    def config_logs(self, request, pk=None):
        """Get configuration logs for a specific device"""
        device = self.get_object()
        logs = ConfigurationLog.objects.filter(device=device).order_by('-created_at')
        serializer = ConfigurationLogSerializer(logs, many=True)
        return Response(serializer.data)
    
    def update(self, request, *args, **kwargs):  # Correct signature
        import logging
        logger = logging.getLogger('django.request')
        
        logger.error("=== VIEWSET UPDATE STARTED ===")
        logger.error(f"Request method: {request.method}")
        logger.error(f"Request path: {request.path}")
        logger.error(f"Request data: {request.data}")
        logger.error(f"Args: {args}")
        logger.error(f"Kwargs: {kwargs}")
        
        # Get the device before update to check if is_active is changing
        device_id = kwargs.get('pk')
        old_is_active = None
        if device_id:
            try:
                old_device = ModbusDevice.objects.get(id=device_id)
                old_is_active = old_device.is_active
                logger.error(f"Old device state - ID: {device_id}, is_active: {old_is_active}")
            except ModbusDevice.DoesNotExist:
                logger.error(f"Device with ID {device_id} does not exist")
                pass
        
        try:
            # Perform the update using parent class
            response = super().update(request, *args, **kwargs)
            logger.error(f"Update response status: {response.status_code}")
            
            # If the update was successful, check if we need to apply config
            if response.status_code == status.HTTP_200_OK and device_id:
                try:
                    device = ModbusDevice.objects.get(id=device_id)
                    new_is_active = device.is_active
                    logger.error(f"New device state - is_active: {new_is_active}")
                    
                    # Only auto-apply if is_active status changed
                    if old_is_active is not None and old_is_active != new_is_active:
                        logger.error(f"Device activation changed: {old_is_active} -> {new_is_active}")
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
            
        except Exception as e:
            logger.error(f"UPDATE FAILED: {str(e)}")
            import traceback
            logger.error(f"FULL TRACEBACK: {traceback.format_exc()}")
            raise
    
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
            
            # Add registers as parameters (ensure they belong exclusively to the device)
            for register in device.registers.filter(is_active=True, device_model__isnull=True).order_by('order'):
                # Build parameter config: [name, scale, unit, data_type, register_count?, word_order?]
                param_config = [
                    register.name,
                    register.scale_factor,
                    register.unit or '',
                    register.data_type
                ]
                # Get effective register count (explicit or auto-calculated)
                register_count = register.register_count if register.register_count > 0 else register.get_register_count()
                
                # Add register_count and word_order if needed (for multi-word registers)
                if register_count > 1 or register.word_order != 'high-low':
                    # Include register_count if it's a multi-word register or word_order is custom
                    if register_count > 1:
                        param_config.append(register_count)
                    elif register.word_order != 'high-low':
                        # Need count to specify word_order, so add calculated count
                        param_config.append(register.get_register_count())
                    
                    # Add word_order if not default
                    if register.word_order != 'high-low':
                        param_config.append(register.word_order)
                
                device_config['parameters'][register.address] = tuple(param_config)
            
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

def realtime_power_data(request):
    """Get real-time data for all active devices (power for electricity, flow for flowmeters)"""
    try:
        from influxdb_client import InfluxDBClient
        from datetime import datetime, timedelta
        
        # Get device type filter from query params (optional)
        device_type_filter = request.GET.get('device_type')  # 'electricity' or 'flowmeter'
        
        # Get all active devices, optionally filtered by type
        active_devices = ModbusDevice.objects.filter(is_active=True)
        if device_type_filter:
            active_devices = active_devices.filter(device_type=device_type_filter)
        
        if not active_devices.exists():
            return JsonResponse({
                'devices': [],
                'timestamp': timezone.now().isoformat()
            })
        
        # Connect to InfluxDB
        client = InfluxDBClient(
            url='http://localhost:8086',
            token='PQF2DMjfNtn__ooeubqDTUaiXegywYbzUBNyTjpvd7qoUrmq9PpGVyS8lybnmf-sszI7V1HEwZWdSvgkEGfzcQ==',
            org='DATABRIDGE'
        )
        query_api = client.query_api()
        
        # Query for latest data for each device
        device_data = []
        for device in active_devices:
            try:
                # For electricity devices, look for power registers
                # For flowmeters, look for flow registers
                if device.device_type == 'flowmeter':
                    # Look for instantaneous flow or total flow
                    value_register = device.registers.filter(
                        name__icontains='instantaneous_flow',
                        is_active=True
                    ).first()
                    
                    if not value_register:
                        value_register = device.registers.filter(
                            name__icontains='flow',
                            is_active=True
                        ).first()
                    
                    default_unit = 'm³/h'
                else:
                    # Electricity analyzer - look for power registers
                    # Try multiple variations to find the total/three-phase power
                    value_register = device.registers.filter(
                        name__icontains='active_power_total',
                        is_active=True
                    ).first()
                    
                    if not value_register:
                        # Try "total_active_power"
                        value_register = device.registers.filter(
                            name__icontains='total_active_power',
                            is_active=True
                        ).first()
                    
                    if not value_register:
                        # Try "Active Three-phase Power" (common in Circutor analyzers)
                        value_register = device.registers.filter(
                            name__icontains='active three-phase power',
                            is_active=True
                        ).first()
                    
                    if not value_register:
                        # Try "three-phase" or "three_phase" variations
                        value_register = device.registers.filter(
                            name__icontains='three-phase',
                            is_active=True
                        ).filter(
                            name__icontains='active'
                        ).first()
                    
                    if not value_register:
                        # Try "three_phase" with underscore
                        value_register = device.registers.filter(
                            name__icontains='three_phase',
                            is_active=True
                        ).filter(
                            name__icontains='active'
                        ).first()
                    
                    if not value_register:
                        # Fallback: any register with "active" and "power" (but not per-phase)
                        value_register = device.registers.filter(
                            name__icontains='active',
                            is_active=True
                        ).filter(
                            name__icontains='power'
                        ).exclude(
                            name__icontains='l1'
                        ).exclude(
                            name__icontains='l2'
                        ).exclude(
                            name__icontains='l3'
                        ).exclude(
                            name__icontains='phase_1'
                        ).exclude(
                            name__icontains='phase_2'
                        ).exclude(
                            name__icontains='phase_3'
                        ).first()
                    
                    default_unit = 'kW'
                
                if value_register:
                    # Get the field name (use influxdb_field_name if available, otherwise use name)
                    field_name = value_register.influxdb_field_name or value_register.name
                    
                    # Query for the latest value (last 5 minutes, get most recent)
                    query = f'''
                    from(bucket: "databridge")
                      |> range(start: -5m)
                      |> filter(fn: (r) => r["_measurement"] == "energy_measurements")
                      |> filter(fn: (r) => r["_field"] == "{field_name}")
                      |> filter(fn: (r) => r["device_id"] == "{device.name}")
                      |> last()
                    '''
                    
                    result = query_api.query(query)
                    value = None
                    last_update = None
                    
                    for table in result:
                        for record in table.records:
                            value = record.get_value()
                            last_update = record.get_time()
                            break
                        if value is not None:
                            break
                    
                    # Apply scale factor if needed
                    if value is not None and value_register.scale_factor:
                        value = value * value_register.scale_factor
                    
                    # Convert W to kW for electricity devices if unit is W
                    display_unit = value_register.unit or default_unit
                    display_value = value
                    if device.device_type == 'electricity' and display_unit == 'W' and value is not None:
                        display_value = value / 1000.0  # Convert W to kW
                        display_unit = 'kW'
                    
                    device_data.append({
                        'id': device.id,
                        'name': device.name,
                        'location': device.location or '',
                        'device_type': device.device_type or 'electricity',  # Default to electricity if not set
                        'power_value': display_value,  # Keep field name for compatibility
                        'unit': display_unit,
                        'last_update': last_update.isoformat() if last_update else None,
                        'is_online': value is not None,
                        'parent_device_id': device.parent_device.id if device.parent_device else None,
                        'parent_device_name': device.parent_device.name if device.parent_device else None
                    })
                else:
                    # No relevant register found
                    device_data.append({
                        'id': device.id,
                        'name': device.name,
                        'location': device.location or '',
                        'device_type': device.device_type or 'electricity',  # Default to electricity if not set
                        'power_value': None,
                        'unit': default_unit,
                        'last_update': None,
                        'is_online': False,
                        'parent_device_id': device.parent_device.id if device.parent_device else None,
                        'parent_device_name': device.parent_device.name if device.parent_device else None
                    })
            except Exception as e:
                logger.error(f"Error fetching data for device {device.name}: {e}")
                device_data.append({
                    'id': device.id,
                    'name': device.name,
                    'location': device.location or '',
                    'device_type': device.device_type or 'electricity',  # Default to electricity if not set
                    'power_value': None,
                    'unit': 'kW' if (device.device_type or 'electricity') == 'electricity' else 'm³/h',
                    'last_update': None,
                    'is_online': False,
                    'error': str(e),
                    'parent_device_id': device.parent_device.id if device.parent_device else None,
                    'parent_device_name': device.parent_device.name if device.parent_device else None
                })
        
        client.close()
        
        return JsonResponse({
            'devices': device_data,
            'timestamp': timezone.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error in realtime_power_data: {e}")
        return JsonResponse({
            'error': str(e),
            'devices': [],
            'timestamp': timezone.now().isoformat()
        }, status=500)

@api_view(['POST'])
def set_device_parent(request, pk):
    """Set parent device for a device in the single-line diagram"""
    try:
        device = ModbusDevice.objects.get(pk=pk)
        parent_id = request.data.get('parent_device_id')
        
        if parent_id is None:
            device.parent_device = None
        else:
            try:
                parent_device = ModbusDevice.objects.get(pk=parent_id)
                # Prevent circular references
                if parent_device.id == device.id:
                    return Response(
                        {'error': 'Device cannot be its own parent'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                # Check for circular reference (parent's parent chain)
                current = parent_device
                depth = 0
                while current.parent_device and depth < 10:  # Max depth check
                    if current.parent_device.id == device.id:
                        return Response(
                            {'error': 'Circular reference detected'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    current = current.parent_device
                    depth += 1
                device.parent_device = parent_device
            except ModbusDevice.DoesNotExist:
                return Response(
                    {'error': f'Parent device with id {parent_id} not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        
        device.save()
        return Response({
            'success': True,
            'device_id': device.id,
            'device_name': device.name,
            'parent_device_id': device.parent_device.id if device.parent_device else None,
            'parent_device_name': device.parent_device.name if device.parent_device else None
        })
    except ModbusDevice.DoesNotExist:
        return Response(
            {'error': f'Device with id {pk} not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Error setting device parent: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
