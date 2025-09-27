# modbus/services/data_sync.py
from django.utils import timezone
from datetime import datetime, timedelta
from influxdb_client import InfluxDBClient
from ..models import EnergyMeasurement, ModbusDevice
import logging

logger = logging.getLogger(__name__)

class InfluxToPostgresSync:
    def __init__(self):
        self.influx_client = InfluxDBClient(
            url='http://localhost:8086',
            token='PQF2DMjfNtn__ooeubqDTUaiXegywYbzUBNyTjpvd7qoUrmq9PpGVyS8lybnmf-sszI7V1HEwZWdSvgkEGfzcQ==',
            org='DATABRIDGE'
        )
        self.query_api = self.influx_client.query_api()
    
    def sync_device_measurements(self, device, start_time):
        """Sync measurements for a specific device"""
        try:
            # Map device to InfluxDB tag (you might need to adjust this based on your Python script)
            device_tag = "main_analyzer"  # Default, you might want to make this configurable
            
            query = f'''
            from(bucket: "databridge")
                |> range(start: {start_time.isoformat()})
                |> filter(fn: (r) => r._measurement == "energy_measurements")
                |> filter(fn: (r) => r.device_id == "{device_tag}")
                |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
            '''
            
            tables = self.query_api.query(query)
            
            for table in tables:
                for record in table.records:
                    self.create_energy_measurement(device, record)
                    
            logger.info(f"Synced measurements for device {device.name}")
            
        except Exception as e:
            logger.error(f"Error syncing measurements for device {device.name}: {e}")
    
    def create_energy_measurement(self, device, record):
        """Map InfluxDB fields to EnergyMeasurement model"""
        field_mapping = {
            'voltage_v12': 'voltage_l1_l2',
            'voltage_v1n': 'voltage_l1_n',
            'current_phase1': 'current_l1',
            'total_active_power': 'active_power_total',
            'frequency': 'frequency',
            # Add more mappings as needed
        }
        
        measurement_data = {'device': device, 'timestamp': record.get_time()}
        
        for influx_field, model_field in field_mapping.items():
            if hasattr(record, influx_field):
                measurement_data[model_field] = getattr(record, influx_field)
        
        # Create measurement
        EnergyMeasurement.objects.create(**measurement_data)
