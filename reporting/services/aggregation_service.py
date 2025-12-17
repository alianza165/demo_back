"""
Aggregation service for daily and monthly data aggregation.
Coordinates with downsampling to use appropriate data sources.
"""
import logging
from datetime import datetime, timedelta, date
from typing import Optional, Dict, List
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Avg, Max, Min

# Use HTTP requests for InfluxDB v1
import requests
from modbus.models import ModbusDevice
from ..models import DailyAggregate, MonthlyAggregate, ProductionData

logger = logging.getLogger(__name__)


class ReportingAggregationService:
    """
    Service for aggregating energy data for reporting dashboards.
    Uses downsampled data when available for performance.
    """
    
    def __init__(self):
        # InfluxDB v1 uses HTTP API
        self.influx_url = "http://localhost:8086"
        self.database = "databridge"
    
    def aggregate_daily_data(
        self,
        target_date: Optional[date] = None,
        device: Optional[ModbusDevice] = None
    ) -> List[DailyAggregate]:
        """
        Aggregate daily data for a specific date or yesterday if not specified.
        Uses downsampled data when available (energy_measurements_1m for data older than 5 days).
        """
        if target_date is None:
            target_date = (timezone.now() - timedelta(days=1)).date()
        
        start_datetime = timezone.make_aware(datetime.combine(target_date, datetime.min.time()))
        end_datetime = start_datetime + timedelta(days=1)
        
        # Determine which devices to process
        if device:
            devices = [device]
        else:
            devices = ModbusDevice.objects.filter(is_active=True)
        
        aggregates = []
        
        for device in devices:
            try:
                aggregate = self._aggregate_device_daily(device, target_date, start_datetime, end_datetime)
                if aggregate:
                    aggregates.append(aggregate)
            except Exception as e:
                logger.error(f"Error aggregating daily data for {device.name} on {target_date}: {e}")
        
        return aggregates
    
    def _aggregate_device_daily(
        self,
        device: ModbusDevice,
        target_date: date,
        start_datetime: datetime,
        end_datetime: datetime
    ) -> Optional[DailyAggregate]:
        """Aggregate daily data for a single device."""
        
        # Determine which measurement to use based on date
        # Recent data (last 5 days): use raw or 1m downsampled
        # Older data: use 1m or 5m downsampled
        days_ago = (timezone.now().date() - target_date).days
        
        if days_ago <= 5:
            # Recent data - prefer raw with 1m aggregation
            measurement = "energy_measurements"
            aggregation_window = "1m"
        elif days_ago <= 35:
            # Use 1-minute downsampled
            measurement = "energy_measurements_1m"
            aggregation_window = None
        elif days_ago <= 215:
            # Use 5-minute downsampled
            measurement = "energy_measurements_5m"
            aggregation_window = None
        else:
            # Use 1-hour downsampled
            measurement = "energy_measurements_1h"
            aggregation_window = None
        
        # Query energy data
        energy_query = self._build_energy_query(
            device.name,
            start_datetime,
            end_datetime,
            measurement,
            aggregation_window
        )
        
        total_energy = 0.0
        power_values = []
        component_breakdown = {}
        
        try:
            # Use InfluxDB v1 HTTP API
            params = {
                'db': self.database,
                'q': energy_query,
                'epoch': 'ms'
            }
            response = requests.get(f"{self.influx_url}/query", params=params, timeout=10)
            response.raise_for_status()
            result = response.json()
            
            # Parse InfluxDB v1 response format
            if result.get('results') and result['results'][0].get('series'):
                for series in result['results'][0]['series']:
                    columns = series.get('columns', [])
                    values = series.get('values', [])
                    
                    for row in values:
                        # Row format: [time, field1, field2, ...]
                        # Column format: ['time', 'field_name']
                        for i, col in enumerate(columns):
                            if col == 'time' or i == 0:
                                continue
                            field_name = col
                            value = row[i] if i < len(row) else None
                            
                            if value is None:
                                continue
                            
                            # Accumulate total energy
                            if field_name in ['total_energy', 'total_active_power', 'active_power_total']:
                                total_energy += float(value)
                                power_values.append(float(value))
                            
                            # Component breakdown (identify by field names)
                            component = self._identify_component(field_name)
                            if component:
                                component_breakdown[component] = component_breakdown.get(component, 0) + float(value)
        except Exception as e:
            logger.error(f"Error querying InfluxDB for {device.name}: {e}")
            return None
        
        # Calculate power metrics
        avg_power = sum(power_values) / len(power_values) if power_values else 0
        peak_power = max(power_values) if power_values else 0
        
        # Get production data if available
        production = ProductionData.objects.filter(
            device=device,
            date=target_date
        ).first()
        
        units_produced = production.units_produced if production else None
        efficiency_kwh_per_unit = None
        
        if units_produced and units_produced > 0 and total_energy > 0:
            efficiency_kwh_per_unit = total_energy / units_produced
        
        # Calculate cost
        tariff_rate = 0.15  # Default, can be made configurable
        total_cost = total_energy * tariff_rate
        
        # Create or update aggregate
        with transaction.atomic():
            aggregate, created = DailyAggregate.objects.update_or_create(
                device=device,
                date=target_date,
                defaults={
                    'total_energy_kwh': total_energy,
                    'avg_power_kw': avg_power,
                    'peak_power_kw': peak_power,
                    'component_breakdown': component_breakdown,
                    'units_produced': units_produced,
                    'efficiency_kwh_per_unit': efficiency_kwh_per_unit,
                    'total_cost': total_cost,
                }
            )
            
            logger.info(f"{'Created' if created else 'Updated'} daily aggregate for {device.name} on {target_date}")
            return aggregate
    
    def aggregate_monthly_data(
        self,
        target_month: Optional[date] = None,
        device: Optional[ModbusDevice] = None
    ) -> List[MonthlyAggregate]:
        """
        Aggregate monthly data for a specific month or last month if not specified.
        Uses daily aggregates for efficiency, or queries InfluxDB directly.
        """
        if target_month is None:
            # Last month
            today = timezone.now().date()
            target_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        else:
            target_month = target_month.replace(day=1)
        
        month_start = timezone.make_aware(datetime.combine(target_month, datetime.min.time()))
        month_end = (target_month + timedelta(days=32)).replace(day=1)
        month_end_datetime = timezone.make_aware(datetime.combine(month_end, datetime.min.time()))
        
        # Determine devices
        if device:
            devices = [device]
        else:
            devices = ModbusDevice.objects.filter(is_active=True)
        
        aggregates = []
        
        for device in devices:
            try:
                # Try to aggregate from daily aggregates first (more efficient)
                aggregate = self._aggregate_monthly_from_daily(device, target_month)
                
                # If no daily aggregates available, query InfluxDB directly
                if not aggregate:
                    aggregate = self._aggregate_monthly_from_influx(
                        device, target_month, month_start, month_end_datetime
                    )
                
                if aggregate:
                    aggregates.append(aggregate)
            except Exception as e:
                logger.error(f"Error aggregating monthly data for {device.name} in {target_month}: {e}")
        
        return aggregates
    
    def _aggregate_monthly_from_daily(
        self,
        device: ModbusDevice,
        target_month: date
    ) -> Optional[MonthlyAggregate]:
        """Aggregate monthly data from daily aggregates."""
        month_start = target_month
        month_end = (target_month + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        
        daily_aggregates = DailyAggregate.objects.filter(
            device=device,
            date__gte=month_start,
            date__lte=month_end
        )
        
        if not daily_aggregates.exists():
            return None
        
        # Aggregate metrics
        total_energy = sum(agg.total_energy_kwh for agg in daily_aggregates)
        avg_daily_energy = total_energy / daily_aggregates.count()
        peak_power = max((agg.peak_power_kw for agg in daily_aggregates), default=0)
        
        # Combine component breakdowns
        component_breakdown = {}
        for agg in daily_aggregates:
            for component, value in agg.component_breakdown.items():
                component_breakdown[component] = component_breakdown.get(component, 0) + value
        
        # Production data
        total_units = sum(
            (agg.units_produced for agg in daily_aggregates if agg.units_produced),
            start=0
        )
        
        efficiency = None
        if total_units > 0 and total_energy > 0:
            efficiency = total_energy / total_units
        
        # Calculate cost
        total_cost = sum(agg.total_cost for agg in daily_aggregates)
        tariff_rate = 0.15
        
        # Data completeness
        days_in_month = (month_end - month_start).days + 1
        data_completeness = (daily_aggregates.count() / days_in_month) * 100
        
        with transaction.atomic():
            aggregate, created = MonthlyAggregate.objects.update_or_create(
                device=device,
                month=target_month,
                defaults={
                    'total_energy_kwh': total_energy,
                    'avg_daily_energy_kwh': avg_daily_energy,
                    'peak_power_kw': peak_power,
                    'component_breakdown': component_breakdown,
                    'total_units_produced': total_units,
                    'efficiency_kwh_per_unit': efficiency,
                    'total_cost': total_cost,
                    'tariff_rate': tariff_rate,
                    'data_completeness': data_completeness,
                }
            )
            
            logger.info(f"{'Created' if created else 'Updated'} monthly aggregate for {device.name} in {target_month}")
            return aggregate
    
    def _aggregate_monthly_from_influx(
        self,
        device: ModbusDevice,
        target_month: date,
        month_start: datetime,
        month_end: datetime
    ) -> Optional[MonthlyAggregate]:
        """Aggregate monthly data directly from InfluxDB (fallback)."""
        # Use 1m or 5m downsampled data for older months
        days_ago = (timezone.now().date() - target_month).days
        
        if days_ago <= 35:
            measurement = "energy_measurements_1m"
        elif days_ago <= 215:
            measurement = "energy_measurements_5m"
        else:
            measurement = "energy_measurements_1h"
        
        energy_query = self._build_energy_query(
            device.name,
            month_start,
            month_end,
            measurement,
            None
        )
        
        total_energy = 0.0
        component_breakdown = {}
        
        try:
            # Use InfluxDB v1 HTTP API
            params = {
                'db': self.database,
                'q': energy_query,
                'epoch': 'ms'
            }
            response = requests.get(f"{self.influx_url}/query", params=params, timeout=10)
            response.raise_for_status()
            result = response.json()
            
            # Parse InfluxDB v1 response format
            if result.get('results') and result['results'][0].get('series'):
                for series in result['results'][0]['series']:
                    columns = series.get('columns', [])
                    values = series.get('values', [])
                    
                    for row in values:
                        for i, col in enumerate(columns):
                            if col == 'time' or i == 0:
                                continue
                            field_name = col
                            value = row[i] if i < len(row) else None
                            
                            if value is None:
                                continue
                            
                            if field_name in ['total_energy', 'total_active_power', 'active_power_total']:
                                total_energy += float(value)
                            
                            component = self._identify_component(field_name)
                            if component:
                                component_breakdown[component] = component_breakdown.get(component, 0) + float(value)
        except Exception as e:
            logger.error(f"Error querying InfluxDB for monthly aggregate: {e}")
            return None
        
        # Get production data
        production_records = ProductionData.objects.filter(
            device=device,
            date__gte=target_month,
            date__lt=(target_month + timedelta(days=32)).replace(day=1)
        )
        
        total_units = sum(prod.units_produced for prod in production_records)
        efficiency = None
        if total_units > 0 and total_energy > 0:
            efficiency = total_energy / total_units
        
        total_cost = total_energy * 0.15
        
        # Estimate data completeness (rough)
        data_completeness = 100.0  # Could be improved with actual data point counting
        
        with transaction.atomic():
            aggregate, created = MonthlyAggregate.objects.update_or_create(
                device=device,
                month=target_month,
                defaults={
                    'total_energy_kwh': total_energy,
                    'avg_daily_energy_kwh': total_energy / 30,  # Rough estimate
                    'peak_power_kw': 0,  # Would need additional query
                    'component_breakdown': component_breakdown,
                    'total_units_produced': total_units,
                    'efficiency_kwh_per_unit': efficiency,
                    'total_cost': total_cost,
                    'tariff_rate': 0.15,
                    'data_completeness': data_completeness,
                }
            )
            
            return aggregate
    
    def _build_energy_query(
        self,
        device_name: str,
        start: datetime,
        end: datetime,
        measurement: str,
        aggregation_window: Optional[str]
    ) -> str:
        """Build InfluxQL query for energy data (InfluxDB v1)."""
        # Convert datetime to InfluxDB v1 format (RFC3339 or epoch)
        start_str = start.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_str = end.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # Build basic SELECT query
        # Note: InfluxDB v1 doesn't support field filtering in WHERE, so we'll query all fields
        # and filter in the application code
        if aggregation_window:
            # Use GROUP BY time for aggregation
            window_map = {
                '1m': '1m',
                '5m': '5m',
                '1h': '1h'
            }
            group_by = window_map.get(aggregation_window, '1m')
            query = f'SELECT mean(*) FROM "{measurement}" WHERE "device_id" = \'{device_name}\' AND time >= \'{start_str}\' AND time < \'{end_str}\' GROUP BY time({group_by})'
        else:
            query = f'SELECT * FROM "{measurement}" WHERE "device_id" = \'{device_name}\' AND time >= \'{start_str}\' AND time < \'{end_str}\' LIMIT 10000'
        
        return query
    
    def _identify_component(self, field_name: str) -> Optional[str]:
        """Identify energy component from field name."""
        field_lower = field_name.lower()
        
        if 'light' in field_lower:
            return 'lights'
        elif 'machine' in field_lower or 'motor' in field_lower:
            return 'machines'
        elif 'hvac' in field_lower or 'cooling' in field_lower or 'ac' in field_lower:
            return 'hvac'
        elif 'exhaust' in field_lower or 'fan' in field_lower:
            return 'exhaust_fan'
        elif 'office' in field_lower:
            return 'office'
        elif 'laser' in field_lower:
            return 'laser'
        else:
            return None



