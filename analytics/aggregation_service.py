import logging
import os
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from influxdb_client import InfluxDBClient
from .models import EnergySummary, ShiftEnergyData, ShiftDefinition  # Import from analytics
from modbus.models import ModbusDevice  # Import ModbusDevice from modbus

logger = logging.getLogger(__name__)

class DataAggregationService:
    def __init__(self):
        self.influx_client = InfluxDBClient(
            url="http://localhost:8086",
            token="PQF2DMjfNtn__ooeubqDTUaiXegywYbzUBNyTjpvd7qoUrmq9PpGVyS8lybnmf-sszI7V1HEwZWdSvgkEGfzcQ==",
            org="DATABRIDGE"
        )
        self.query_api = self.influx_client.query_api()
    
    def aggregate_hourly_data(self, hours_back=24):
        """Aggregate data from InfluxDB to hourly summaries"""
        try:
            end_time = timezone.now()
            start_time = end_time - timedelta(hours=hours_back)
            
            # Query for active power data
            query = f'''
            from(bucket: "databridge")
              |> range(start: {start_time.isoformat()}, stop: {end_time.isoformat()})
              |> filter(fn: (r) => r["_measurement"] == "energy_measurements")
              |> filter(fn: (r) => r["_field"] == "total_active_power" or r["_field"] == "total_energy")
              |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
              |> yield(name: "mean")
            '''
            
            result = self.query_api.query(query)
            
            with transaction.atomic():
                for table in result:
                    for record in table.records:
                        device_name = record.values.get('device_id')
                        if not device_name:
                            continue
                            
                        # Get or create device from modbus app
                        try:
                            device = ModbusDevice.objects.get(name=device_name)
                        except ModbusDevice.DoesNotExist:
                            logger.warning(f"Device not found: {device_name}")
                            continue
                        
                        # Create hourly summary
                        EnergySummary.objects.update_or_create(
                            device=device,
                            timestamp=record.get_time(),
                            interval_type='hourly',
                            defaults={
                                'total_energy_kwh': record.get_value() or 0,
                                'avg_power_kw': record.get_value() or 0,
                                'tariff_rate': 0.15  # Default rate
                            }
                        )
            
            logger.info(f"Aggregated hourly data for last {hours_back} hours")
            
        except Exception as e:
            logger.error(f"Error aggregating hourly data: {e}")
    
    def calculate_shift_energy(self, shift_date=None):
        """Calculate energy consumption for defined shifts"""
        if not shift_date:
            shift_date = timezone.now().date()
        
        # Import from analytics app, not modbus
        shifts = ShiftDefinition.objects.filter(is_active=True)
        
        for shift in shifts:
            # Calculate shift start and end datetime
            shift_start = timezone.make_aware(
                datetime.combine(shift_date, shift.shift_start)
            )
            shift_end = timezone.make_aware(
                datetime.combine(shift_date, shift.shift_end)
            )
            
            # If shift crosses midnight, adjust end time
            if shift.shift_end < shift.shift_start:
                shift_end += timedelta(days=1)
            
            # Query energy data for this shift
            query = f'''
            from(bucket: "databridge")
              |> range(start: {shift_start.isoformat()}, stop: {shift_end.isoformat()})
              |> filter(fn: (r) => r["_measurement"] == "energy_measurements")
              |> filter(fn: (r) => r["_field"] == "total_active_power")
              |> integral(unit: 1h)
              |> yield(name: "energy")
            '''
            
            try:
                result = self.query_api.query(query)
                
                for table in result:
                    for record in table.records:
                        device_name = record.values.get('device_id')
                        if not device_name:
                            continue
                            
                        # Get device from modbus app
                        try:
                            device = ModbusDevice.objects.get(name=device_name)
                        except ModbusDevice.DoesNotExist:
                            logger.warning(f"Device not found: {device_name}")
                            continue
                        
                        energy_kwh = record.get_value() or 0
                        total_cost = energy_kwh * (shift.tariff_rate if hasattr(shift, 'tariff_rate') else 0.15)
                        
                        # Calculate energy per unit if production data exists
                        energy_per_unit = None
                        cost_per_unit = None
                        if shift.units_produced and shift.units_produced > 0:
                            energy_per_unit = energy_kwh / shift.units_produced
                            cost_per_unit = total_cost / shift.units_produced
                        
                        ShiftEnergyData.objects.update_or_create(
                            shift=shift,
                            device=device,
                            shift_date=shift_date,
                            defaults={
                                'total_energy_kwh': energy_kwh,
                                'avg_power_kw': energy_kwh / ((shift_end - shift_start).total_seconds() / 3600),
                                'peak_power_kw': self._get_peak_power(device, shift_start, shift_end),
                                'units_produced': shift.units_produced,
                                'energy_per_unit': energy_per_unit,
                                'cost_per_unit': cost_per_unit,
                                'total_cost': total_cost,
                                'tariff_rate': shift.tariff_rate if hasattr(shift, 'tariff_rate') else 0.15
                            }
                        )
                        
            except Exception as e:
                logger.error(f"Error calculating shift energy for {shift.name}: {e}")
    
    def _get_peak_power(self, device, start_time, end_time):
        """Get peak power for a device during a time range"""
        query = f'''
        from(bucket: "databridge")
          |> range(start: {start_time.isoformat()}, stop: {end_time.isoformat()})
          |> filter(fn: (r) => r["_measurement"] == "energy_measurements")
          |> filter(fn: (r) => r["_field"] == "total_active_power")
          |> filter(fn: (r) => r["device_id"] == "{device.name}")
          |> max()
        '''
        
        try:
            result = self.query_api.query(query)
            for table in result:
                for record in table.records:
                    return record.get_value() or 0
        except Exception as e:
            logger.error(f"Error getting peak power: {e}")
        
        return 0
    
    def compare_devices(self, start_time, end_time):
        """Compare energy consumption between devices"""
        comparison_data = {}
        
        devices = ModbusDevice.objects.filter(is_active=True)
        
        for device in devices:
            query = f'''
            from(bucket: "databridge")
              |> range(start: {start_time.isoformat()}, stop: {end_time.isoformat()})
              |> filter(fn: (r) => r["_measurement"] == "energy_measurements")
              |> filter(fn: (r) => r["_field"] == "total_active_power")
              |> filter(fn: (r) => r["device_id"] == "{device.name}")
              |> integral(unit: 1h)
              |> yield(name: "energy")
            '''
            
            try:
                result = self.query_api.query(query)
                total_energy = 0
                
                for table in result:
                    for record in table.records:
                        total_energy += record.get_value() or 0
                
                comparison_data[device.id] = {
                    'energy_kwh': total_energy,
                    'cost': total_energy * 0.15,  # Default tariff
                    'device_name': device.name
                }
                
            except Exception as e:
                logger.error(f"Error comparing device {device.name}: {e}")
        
        # Store comparison
        from .models import DeviceComparison
        DeviceComparison.objects.create(
            timestamp=timezone.now(),
            interval_type='custom',
            comparison_data=comparison_data
        )
        
        return comparison_data
