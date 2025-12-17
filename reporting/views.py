"""
API views for reporting dashboard.
"""
import logging
from datetime import datetime, timedelta, date
from typing import Optional
from django.utils import timezone
from django.db.models import Sum, Avg, Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination

from .models import (
    ProductionData,
    EfficiencyBenchmark,
    Target,
    MonthlyAggregate,
    DailyAggregate,
    EngineeringDashboard,
    CapacityLoad,
)
from .serializers import (
    ProductionDataSerializer,
    EfficiencyBenchmarkSerializer,
    TargetSerializer,
    MonthlyAggregateSerializer,
    DailyAggregateSerializer,
    DashboardDataCardSerializer,
    EnergyMixSerializer,
    EnergyMixComponentSerializer,
    MonthlyTrendDataSerializer,
    EfficiencyMetricSerializer,
    EngineeringDashboardSerializer,
    CapacityLoadSerializer,
)
from modbus.models import ModbusDevice
from .services.process_mapper import ProcessMapper
from .services.steam_converter import SteamConverter

logger = logging.getLogger(__name__)


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class ProductionDataViewSet(viewsets.ModelViewSet):
    """ViewSet for production data."""
    queryset = ProductionData.objects.all()
    serializer_class = ProductionDataSerializer
    filterset_fields = ['device', 'date', 'shift_type']
    search_fields = ['device__name', 'notes']
    ordering_fields = ['date', 'units_produced']
    ordering = ['-date']


class EfficiencyBenchmarkViewSet(viewsets.ModelViewSet):
    """ViewSet for efficiency benchmarks."""
    queryset = EfficiencyBenchmark.objects.all()
    serializer_class = EfficiencyBenchmarkSerializer
    filterset_fields = ['device', 'benchmark_type', 'metric_name', 'is_active']
    search_fields = ['metric_name']
    ordering_fields = ['benchmark_value', 'created_at']
    ordering = ['-created_at']


class TargetViewSet(viewsets.ModelViewSet):
    """ViewSet for targets."""
    queryset = Target.objects.all()
    serializer_class = TargetSerializer
    filterset_fields = ['device', 'metric_name', 'target_period', 'is_on_track']
    search_fields = ['metric_name']
    ordering_fields = ['period_start', 'target_value']
    ordering = ['-period_start']


class MonthlyAggregateViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for monthly aggregates."""
    queryset = MonthlyAggregate.objects.all()
    serializer_class = MonthlyAggregateSerializer
    filterset_fields = ['device', 'month']
    ordering_fields = ['month', 'total_energy_kwh']
    ordering = ['-month']


class DailyAggregateViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for daily aggregates."""
    queryset = DailyAggregate.objects.all()
    serializer_class = DailyAggregateSerializer
    filterset_fields = ['device', 'date', 'is_overtime']
    search_fields = ['device__name', 'device__process_area', 'device__floor', 'device__load_type']
    ordering_fields = ['date', 'total_energy_kwh']
    ordering = ['-date']
    
    def get_queryset(self):
        """Add filtering by process_area, floor, load_type."""
        queryset = super().get_queryset()
        
        process_area = self.request.query_params.get('process_area')
        floor = self.request.query_params.get('floor')
        load_type = self.request.query_params.get('load_type')
        
        if process_area:
            queryset = queryset.filter(device__process_area=process_area)
        if floor:
            queryset = queryset.filter(device__floor=floor)
        if load_type:
            queryset = queryset.filter(device__load_type=load_type)
        
        return queryset


class EngineeringDashboardViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for engineering dashboard data."""
    queryset = EngineeringDashboard.objects.all()
    serializer_class = EngineeringDashboardSerializer
    filterset_fields = ['date']
    ordering_fields = ['date']
    ordering = ['-date']


class CapacityLoadViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for capacity load data."""
    queryset = CapacityLoad.objects.filter(is_active=True)
    serializer_class = CapacityLoadSerializer
    filterset_fields = ['equipment_type', 'process_area', 'location', 'is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'total_load_kw']
    ordering = ['process_area', 'location', 'name']


class DashboardView(APIView):
    """
    Main dashboard endpoint.
    Returns data cards, energy mix, trends, and efficiency metrics.
    """
    
    def get(self, request):
        """
        Get dashboard data for specified date range and devices.
        
        Query params:
        - date: YYYY-MM-DD (default: today)
        - month: YYYY-MM (for monthly view)
        - devices: comma-separated device IDs
        - process: filter by process type (denim, washing, finishing, sewing)
        - device_type: filter by device type (electricity, flowmeter, temp_gauge)
        - energy_type: filter by energy type (electricity, steam, both) - 'both' converts steam to cost equivalent
        - page: page number for paginated table (default: 1)
        - page_size: items per page (default: 20)
        """
        # Parse query parameters
        target_date_str = request.query_params.get('date')
        target_month_str = request.query_params.get('month')
        device_ids = request.query_params.get('devices', '').split(',')
        device_ids = [int(d) for d in device_ids if d.isdigit()]
        process_filter = request.query_params.get('process')
        device_type_filter = request.query_params.get('device_type')  # electricity, flowmeter, temp_gauge
        energy_type_filter = request.query_params.get('energy_type', 'both')  # electricity, steam, both
        floor_filter = request.query_params.get('floor')
        load_type_filter = request.query_params.get('load_type')
        is_overtime_filter = request.query_params.get('is_overtime')
        is_overtime = is_overtime_filter and is_overtime_filter.lower() == 'true'
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))
        
        # Determine target date/month
        if target_month_str:
            # Monthly view
            target_month = datetime.strptime(target_month_str, '%Y-%m').date().replace(day=1)
            response_data = self._get_monthly_dashboard(
                target_month, device_ids, process_filter, 
                device_type_filter, energy_type_filter, floor_filter, load_type_filter, is_overtime, page, page_size
            )
        else:
            # Daily view
            if target_date_str:
                target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
            else:
                target_date = timezone.now().date()
            
            response_data = self._get_daily_dashboard(
                target_date, device_ids, process_filter,
                device_type_filter, energy_type_filter, floor_filter, load_type_filter, is_overtime
            )
        
        return Response(response_data)
    
    def _get_daily_dashboard(
        self, target_date: date, device_ids: list, process_filter: Optional[str],
        device_type_filter: Optional[str], energy_type_filter: str,
        floor_filter: Optional[str] = None, load_type_filter: Optional[str] = None,
        is_overtime: bool = False
    ):
        """Get daily dashboard data."""
        # Filter devices
        devices_query = ModbusDevice.objects.filter(is_active=True)
        if device_ids:
            devices_query = devices_query.filter(id__in=device_ids)
        if process_filter:
            devices_query = devices_query.filter(process_area=process_filter)
        if device_type_filter:
            devices_query = devices_query.filter(device_type=device_type_filter)
        if floor_filter:
            devices_query = devices_query.filter(floor=floor_filter)
        if load_type_filter:
            devices_query = devices_query.filter(load_type=load_type_filter)
        
        devices = list(devices_query)
        
        # Get daily aggregates for target date
        daily_aggregates = DailyAggregate.objects.filter(
            date=target_date,
            is_overtime=is_overtime
        )
        if device_ids:
            daily_aggregates = daily_aggregates.filter(device_id__in=device_ids)
        else:
            daily_aggregates = daily_aggregates.filter(device_id__in=[d.id for d in devices])
        
        # Apply energy type filter
        daily_aggregates = self._filter_by_energy_type(daily_aggregates, devices, energy_type_filter)
        
        # Data cards
        data_cards = self._calculate_data_cards(daily_aggregates, target_date, energy_type_filter)
        
        # Energy mix
        energy_mix = self._calculate_energy_mix(daily_aggregates, devices)
        
        return {
            'date': target_date.isoformat(),
            'view_type': 'daily',
            'data_cards': data_cards,
            'energy_mix': energy_mix,
        }
    
    def _get_monthly_dashboard(
        self, target_month: date, device_ids: list, process_filter: Optional[str],
        device_type_filter: Optional[str], energy_type_filter: str,
        floor_filter: Optional[str] = None, load_type_filter: Optional[str] = None,
        is_overtime: bool = False, page: int = 1, page_size: int = 20
    ):
        """Get monthly dashboard data with enhanced filtering."""
        # Filter devices
        devices_query = ModbusDevice.objects.filter(is_active=True)
        if device_ids:
            devices_query = devices_query.filter(id__in=device_ids)
        if process_filter:
            devices_query = devices_query.filter(process_area=process_filter)
        if device_type_filter:
            devices_query = devices_query.filter(device_type=device_type_filter)
        if floor_filter:
            devices_query = devices_query.filter(floor=floor_filter)
        if load_type_filter:
            devices_query = devices_query.filter(load_type=load_type_filter)
        
        devices = list(devices_query)
        
        # Get monthly aggregate
        monthly_aggregates = MonthlyAggregate.objects.filter(month=target_month)
        if device_ids:
            monthly_aggregates = monthly_aggregates.filter(device_id__in=device_ids)
        
        # Apply energy type filter
        monthly_aggregates = self._filter_by_energy_type(monthly_aggregates, devices, energy_type_filter)
        
        # Data cards (with energy type consideration)
        data_cards = self._calculate_monthly_data_cards(monthly_aggregates, target_month, energy_type_filter)
        
        # Energy mix by process (using process mapper)
        energy_mix = self._calculate_monthly_energy_mix_by_process(monthly_aggregates, devices)
        
        # Department-specific energy mix (pie charts per department)
        department_energy_mix = self._calculate_department_energy_mix(monthly_aggregates, devices)
        
        # Monthly trends by process and component
        trends = self._calculate_monthly_trends_by_process(target_month, device_ids, process_filter)
        
        # Detailed device breakdown table (paginated)
        device_table = self._calculate_device_breakdown_table(
            target_month, devices, energy_type_filter, page, page_size
        )
        
        # Consumption table data
        consumption_table = self._calculate_consumption_table(target_month, device_ids)
        
        # Efficiency metrics with targets
        efficiency_metrics = self._calculate_efficiency_metrics_enhanced(target_month, device_ids)
        
        return {
            'month': target_month.strftime('%Y-%m'),
            'view_type': 'monthly',
            'data_cards': data_cards,
            'energy_mix': energy_mix,
            'monthly_trends': trends,
            'consumption_table': consumption_table,
            'device_table': device_table,  # New detailed paginated table
            'department_energy_mix': department_energy_mix,  # Pie charts per department
            'efficiency_metrics': efficiency_metrics,
        }
    
    def _get_device_display_name(self, device: ModbusDevice) -> str:
        """Get display name for device using process_area and floor."""
        parts = []
        if device.process_area and device.process_area != 'general':
            parts.append(device.get_process_area_display())
        if device.floor and device.floor != 'none':
            parts.append(device.get_floor_display())
        if device.load_type and device.load_type != 'none':
            parts.append(device.get_load_type_display())
        
        if parts:
            return f"{device.name} ({', '.join(parts)})"
        else:
            return device.name
    
    def _filter_by_energy_type(self, aggregates, devices, energy_type_filter: str):
        """
        Filter aggregates by energy type.
        - electricity: only electricity analyzers
        - steam: only flowmeters
        - both or empty: all devices (show both), conversion happens in data card calculation
        """
        if energy_type_filter == 'electricity':
            # Only electricity analyzers
            electricity_device_ids = [d.id for d in devices if d.device_type == 'electricity']
            return aggregates.filter(device_id__in=electricity_device_ids) if electricity_device_ids else aggregates.none()
        elif energy_type_filter == 'steam':
            # Only flowmeters
            flowmeter_device_ids = [d.id for d in devices if d.device_type == 'flowmeter']
            return aggregates.filter(device_id__in=flowmeter_device_ids) if flowmeter_device_ids else aggregates.none()
        else:  # 'both' or empty - show all devices
            # Return all aggregates without filtering by device type
            return aggregates
    
    def _calculate_data_cards(self, daily_aggregates, target_date: date, energy_type_filter: str = 'both'):
        """Calculate data card values with energy type filtering."""
        if not daily_aggregates.exists():
            return [
                {
                    'title': 'Total Energy',
                    'value': None,
                    'unit': 'kWh' if energy_type_filter != 'steam' else 'm³',
                    'change': None,
                    'change_percentage': None,
                    'trend': None,
                },
            {
                'title': 'Total Cost',
                'value': None,
                'unit': 'PKR',
                'change': None,
                'change_percentage': None,
                'trend': None,
            },
                {
                    'title': 'Efficiency',
                    'value': None,
                    'unit': 'kWh/Garment',
                    'change': None,
                    'change_percentage': None,
                    'trend': None,
                },
            ]
        
        # Get devices for conversion
        device_map = {d.id: d for d in ModbusDevice.objects.filter(id__in=[agg.device_id for agg in daily_aggregates if agg.device_id])}
        
        total_energy = 0.0
        total_cost = 0.0
        
        for agg in daily_aggregates:
            device = device_map.get(agg.device_id)
            if not device:
                continue
            
            # Handle flowmeter (steam) vs electricity differently
            if device.device_type == 'flowmeter':
                # Flowmeter stores volume in m³, convert to energy and cost
                # Note: total_energy_kwh in aggregate may already be converted or may be volume_m3
                # For now, assume it's volume_m3 and convert
                volume_m3 = agg.total_energy_kwh  # This might be volume, not energy
                steam_data = SteamConverter.get_steam_energy_equivalent(volume_m3)
                cost_pkr = steam_data['cost_pkr']
                
                if energy_type_filter == 'both':
                    # Add cost for comparison
                    total_cost += cost_pkr
                elif energy_type_filter == 'steam':
                    # Show steam volume and cost
                    total_energy += volume_m3  # Store as m³ for steam
                    total_cost += cost_pkr
            else:
                # Electricity
                total_energy += agg.total_energy_kwh
                # Convert electricity cost to PKR
                electricity_cost_pkr = SteamConverter.kwh_to_cost_pkr(
                    agg.total_energy_kwh, 
                    is_electricity=True
                )
                total_cost += electricity_cost_pkr
        
        # Previous day for comparison
        prev_date = target_date - timedelta(days=1)
        device_ids = [agg.device_id for agg in daily_aggregates if agg.device_id]
        prev_aggregates = DailyAggregate.objects.filter(
            date=prev_date,
            device_id__in=device_ids
        ) if device_ids else DailyAggregate.objects.none()
        
        # Apply same energy type filter to previous aggregates
        prev_devices = [d for d in device_map.values()]
        prev_aggregates = self._filter_by_energy_type(prev_aggregates, prev_devices, energy_type_filter)
        
        prev_energy = 0.0
        for agg in prev_aggregates:
            device = device_map.get(agg.device_id)
            if device:
                if device.device_type == 'flowmeter':
                    # For flowmeters, don't add to energy if "both" filter (only cost)
                    if energy_type_filter == 'steam':
                        prev_energy += agg.total_energy_kwh  # This is volume_m3
                else:
                    prev_energy += agg.total_energy_kwh
        
        energy_change = total_energy - prev_energy if prev_energy > 0 else None
        energy_change_pct = ((total_energy - prev_energy) / prev_energy * 100) if prev_energy > 0 else None
        
        # Efficiency
        efficiency_aggregates = [agg for agg in daily_aggregates if agg.efficiency_kwh_per_unit]
        avg_efficiency = sum(agg.efficiency_kwh_per_unit for agg in efficiency_aggregates) / len(efficiency_aggregates) if efficiency_aggregates else None
        
        return [
            {
                'title': 'Total Energy',
                'value': round(total_energy, 2),
                'unit': 'kWh',
                'change': round(energy_change, 2) if energy_change is not None else None,
                'change_percentage': round(energy_change_pct, 2) if energy_change_pct is not None else None,
                'trend': 'up' if energy_change and energy_change > 0 else 'down' if energy_change and energy_change < 0 else 'stable',
            },
            {
                'title': 'Total Cost',
                'value': round(total_cost, 2),
                'unit': 'PKR',
                'change': None,
                'change_percentage': None,
                'trend': None,
            },
            {
                'title': 'Efficiency',
                'value': round(avg_efficiency, 2) if avg_efficiency else None,
                'unit': 'kWh/Garment',
                'change': None,
                'change_percentage': None,
                'trend': None,
            },
        ]
    
    def _calculate_monthly_data_cards(self, monthly_aggregates, target_month: date, energy_type_filter: str = 'both'):
        """Calculate monthly data card values with energy type filtering."""
        if not monthly_aggregates.exists():
            return [
                {
                    'title': 'Total Energy',
                    'value': None,
                    'unit': 'kWh',
                    'change': None,
                    'change_percentage': None,
                    'trend': None,
                },
            {
                'title': 'Total Cost',
                'value': None,
                'unit': 'PKR',
                'change': None,
                'change_percentage': None,
                'trend': None,
            },
                {
                    'title': 'Efficiency',
                    'value': None,
                    'unit': 'kWh/Garment',
                    'change': None,
                    'change_percentage': None,
                    'trend': None,
                },
            ]
        
        # Get devices for conversion
        device_map = {d.id: d for d in ModbusDevice.objects.filter(id__in=[agg.device_id for agg in monthly_aggregates if agg.device_id])}
        
        total_energy = 0.0
        total_cost = 0.0
        
        for agg in monthly_aggregates:
            device = device_map.get(agg.device_id)
            if not device:
                continue
            
            if device.device_type == 'flowmeter':
                # Flowmeter: volume in m³, convert to cost
                volume_m3 = agg.total_energy_kwh  # May be stored as volume
                steam_data = SteamConverter.get_steam_energy_equivalent(volume_m3)
                cost_pkr = steam_data['cost_pkr']
                
                if energy_type_filter == 'both':
                    total_cost += cost_pkr
                elif energy_type_filter == 'steam':
                    total_energy += volume_m3  # Show as m³
                    total_cost += cost_pkr
            else:
                # Electricity
                total_energy += agg.total_energy_kwh
                electricity_cost_pkr = SteamConverter.kwh_to_cost_pkr(
                    agg.total_energy_kwh,
                    is_electricity=True
                )
                total_cost += electricity_cost_pkr
        
        # Previous month for comparison
        prev_month = (target_month - timedelta(days=32)).replace(day=1)
        device_ids = [agg.device_id for agg in monthly_aggregates if agg.device_id]
        prev_aggregates = MonthlyAggregate.objects.filter(
            month=prev_month,
            device_id__in=device_ids
        ) if device_ids else MonthlyAggregate.objects.none()
        
        prev_devices = [d for d in device_map.values()]
        prev_aggregates = self._filter_by_energy_type(prev_aggregates, prev_devices, energy_type_filter)
        
        prev_energy = 0.0
        for agg in prev_aggregates:
            device = device_map.get(agg.device_id)
            if device:
                if device.device_type == 'flowmeter':
                    if energy_type_filter == 'steam':
                        prev_energy += agg.total_energy_kwh  # volume_m3
                else:
                    prev_energy += agg.total_energy_kwh
        
        energy_change = total_energy - prev_energy if prev_energy > 0 else None
        energy_change_pct = ((total_energy - prev_energy) / prev_energy * 100) if prev_energy > 0 else None
        
        # Efficiency
        efficiency_aggregates = [agg for agg in monthly_aggregates if agg.efficiency_kwh_per_unit]
        avg_efficiency = sum(agg.efficiency_kwh_per_unit for agg in efficiency_aggregates) / len(efficiency_aggregates) if efficiency_aggregates else None
        
        return [
            {
                'title': 'Total Energy',
                'value': round(total_energy, 2),
                'unit': 'kWh',
                'change': round(energy_change, 2) if energy_change is not None else None,
                'change_percentage': round(energy_change_pct, 2) if energy_change_pct is not None else None,
                'trend': 'up' if energy_change and energy_change > 0 else 'down' if energy_change and energy_change < 0 else 'stable',
            },
            {
                'title': 'Total Cost',
                'value': round(total_cost, 2),
                'unit': 'PKR',
                'change': None,
                'change_percentage': None,
                'trend': None,
            },
            {
                'title': 'Efficiency',
                'value': round(avg_efficiency, 2) if avg_efficiency else None,
                'unit': 'kWh/Garment',
                'change': None,
                'change_percentage': None,
                'trend': None,
            },
        ]
    
    def _calculate_energy_mix(self, daily_aggregates, devices):
        """Calculate energy mix breakdown."""
        energy_mixes = []
        
        if not devices:
            return energy_mixes
        
        # Handle both QuerySet and list
        if isinstance(daily_aggregates, list):
            aggregates_list = daily_aggregates
        else:
            aggregates_list = list(daily_aggregates)
        
        for device in devices:
            device_agg = next((agg for agg in aggregates_list if agg.device == device), None)
            if not device_agg:
                continue
            
            breakdown = device_agg.component_breakdown or {}
            total = device_agg.total_energy_kwh
            
            if total == 0:
                continue
            
            components = []
            component_colors = {
                'machines': '#FF6384',
                'lights': '#FFCE56',
                'hvac': '#36A2EB',
                'exhaust_fan': '#4BC0C0',
                'office': '#9966FF',
                'laser': '#FF9F40',
            }
            
            for component, value in breakdown.items():
                percentage = (value / total * 100) if total > 0 else 0
                components.append({
                    'name': component.replace('_', ' ').title(),
                    'value': round(value, 2),
                    'percentage': round(percentage, 2),
                    'color': component_colors.get(component.lower()),
                })
            
            # Calculate load (average power)
            load_kw = device_agg.avg_power_kw if device_agg else 0
            
            # Get display name
            display_name = self._get_device_display_name(device)
            
            energy_mixes.append({
                'device_name': display_name,
                'total_kwh': round(total, 2),
                'load_kw': round(load_kw, 2),
                'components': sorted(components, key=lambda x: x['value'], reverse=True),
            })
        
        return energy_mixes
    
    def _calculate_monthly_energy_mix(self, monthly_aggregates, devices):
        """Calculate monthly energy mix."""
        return self._calculate_energy_mix(
            [DailyAggregate(
                device=agg.device,
                date=agg.month,
                total_energy_kwh=agg.total_energy_kwh,
                avg_power_kw=0,
                component_breakdown=agg.component_breakdown,
            ) for agg in monthly_aggregates],
            devices
        )
    
    def _calculate_monthly_energy_mix_by_process(self, monthly_aggregates, devices):
        """Calculate energy mix breakdown by process (Denim, Washing, Finishing, Sewing)."""
        # Get process breakdowns from mapper
        process_breakdowns = ProcessMapper.get_all_process_breakdowns(
            devices, list(monthly_aggregates)
        )
        
        energy_mixes = []
        component_colors = {
            'machines': '#FF6384',
            'lights': '#FFCE56',
            'hvac': '#36A2EB',
            'exhaust_fan': '#4BC0C0',
            'office': '#9966FF',
            'laser': '#FF9F40',
        }
        
        for process_name, breakdown in process_breakdowns.items():
            total_kwh = sum(breakdown.values())
            
            if total_kwh == 0:
                continue
            
            components = []
            for component, value in breakdown.items():
                percentage = (value / total_kwh * 100) if total_kwh > 0 else 0
                components.append({
                    'name': component.replace('_', ' ').title(),
                    'value': round(value, 2),
                    'percentage': round(percentage, 2),
                    'color': component_colors.get(component.lower()),
                })
            
            # Estimate average power (rough calculation)
            avg_power_kw = total_kwh / 720  # Approximate hours in a month
            
            energy_mixes.append({
                'process_name': process_name.title(),
                'device_name': process_name.title(),  # For compatibility
                'total_kwh': round(total_kwh, 2),
                'load_kw': round(avg_power_kw, 2),
                'components': sorted(components, key=lambda x: x['value'], reverse=True),
            })
        
        return energy_mixes
    
    def _calculate_department_energy_mix(self, monthly_aggregates, devices):
        """
        Calculate energy mix breakdown by department.
        Returns pie chart data for each department showing component distribution.
        """
        # Group aggregates by department
        department_data = {}
        device_map = {d.id: d for d in devices}
        
        for agg in monthly_aggregates:
            device = device_map.get(agg.device_id)
            if not device or not device.process_area or device.process_area == 'general':
                continue
            
            department = device.process_area.lower()  # Use process_area as department
            if department not in department_data:
                department_data[department] = {
                    'total_kwh': 0,
                    'components': {},
                    'device_count': 0,
                }
            
            department_data[department]['total_kwh'] += agg.total_energy_kwh
            department_data[department]['device_count'] += 1
            
            # Aggregate component breakdown
            breakdown = agg.component_breakdown or {}
            for component, value in breakdown.items():
                department_data[department]['components'][component] = (
                    department_data[department]['components'].get(component, 0) + value
                )
        
        # Format for frontend (pie charts)
        energy_mixes = []
        component_colors = {
            'machines': '#FF6384',
            'lights': '#FFCE56',
            'hvac': '#36A2EB',
            'exhaust_fan': '#4BC0C0',
            'office': '#9966FF',
            'laser': '#FF9F40',
        }
        
        for department, data in department_data.items():
            total_kwh = data['total_kwh']
            if total_kwh == 0:
                continue
            
            components = []
            for component, value in data['components'].items():
                percentage = (value / total_kwh * 100) if total_kwh > 0 else 0
                components.append({
                    'name': component.replace('_', ' ').title(),
                    'value': round(value, 2),
                    'percentage': round(percentage, 2),
                    'color': component_colors.get(component.lower(), '#999999'),
                })
            
            # Estimate average power
            avg_power_kw = total_kwh / 720  # Approximate hours in a month
            
            energy_mixes.append({
                'department_name': department.title(),
                'device_name': f"{department.title()} Department",  # For compatibility
                'total_kwh': round(total_kwh, 2),
                'load_kw': round(avg_power_kw, 2),
                'device_count': data['device_count'],
                'components': sorted(components, key=lambda x: x['value'], reverse=True),
            })
        
        return energy_mixes
    
    def _calculate_device_breakdown_table(
        self, target_month: date, devices: list, energy_type_filter: str,
        page: int, page_size: int
    ):
        """
        Calculate detailed device breakdown table with pagination.
        Returns paginated list of devices with their consumption metrics.
        """
        monthly_aggregates = MonthlyAggregate.objects.filter(month=target_month)
        monthly_aggregates = monthly_aggregates.filter(device_id__in=[d.id for d in devices])
        
        # Apply energy type filter
        monthly_aggregates = self._filter_by_energy_type(monthly_aggregates, devices, energy_type_filter)
        
        device_map = {d.id: d for d in devices}
        
        table_rows = []
        for agg in monthly_aggregates:
            device = device_map.get(agg.device_id)
            if not device:
                continue
            
            breakdown = agg.component_breakdown or {}
            total_energy = agg.total_energy_kwh
            
            # Calculate cost based on device type
            if device.device_type == 'flowmeter':
                # Steam: convert m³ to PKR
                volume_m3 = total_energy  # May be stored as volume
                steam_data = SteamConverter.get_steam_energy_equivalent(volume_m3)
                total_cost = steam_data['cost_pkr']
            else:
                # Electricity: convert kWh to PKR
                total_cost = SteamConverter.kwh_to_cost_pkr(total_energy, is_electricity=True)
            
            # Get display name
            display_name = self._get_device_display_name(device)
            
            table_rows.append({
                'device_id': device.id,
                'device_name': display_name,
                'device_type': device.get_device_type_display(),
                'location': device.location or '-',
                'department': device.process_area or '-',  # Use process_area as department
                'process': device.process_area or '-',  # Use process_area as process
                'process_area': device.process_area or '-',
                'floor': device.floor or '-',
                'load_type': device.load_type or '-',
                'machine_type': device.application_type or '-',  # Use application_type instead
                'total_energy_kwh': round(total_energy, 2),
                'avg_daily_energy_kwh': round(agg.avg_daily_energy_kwh if hasattr(agg, 'avg_daily_energy_kwh') else 0, 2),
                'peak_power_kw': round(agg.peak_power_kw if hasattr(agg, 'peak_power_kw') else 0, 2),
                'total_cost_usd': round(total_cost, 2),
                'component_breakdown': breakdown,
                'units_produced': agg.total_units_produced if hasattr(agg, 'total_units_produced') else None,
                'efficiency_kwh_per_unit': round(agg.efficiency_kwh_per_unit, 2) if agg.efficiency_kwh_per_unit else None,
            })
        
        # Pagination
        total_count = len(table_rows)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_rows = table_rows[start_idx:end_idx]
        
        return {
            'results': paginated_rows,
            'count': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': (total_count + page_size - 1) // page_size if total_count > 0 else 1,
        }
    
    def _calculate_monthly_trends(self, target_month: date, device_ids: list, process_filter: Optional[str]):
        """Calculate monthly trends with color zones."""
        # Get last 6 months of data
        months = []
        for i in range(6):
            month = (target_month - timedelta(days=32 * i)).replace(day=1)
            months.append(month)
        months.reverse()
        
        trends = {}
        
        # Get monthly aggregates for these months
        monthly_data = MonthlyAggregate.objects.filter(
            month__in=months,
        )
        if device_ids:
            monthly_data = monthly_data.filter(device_id__in=device_ids)
        
        # Group by component and calculate trends
        components = ['lights', 'machines', 'hvac', 'exhaust_fan', 'office', 'laser']
        
        for component in components:
            component_trend = []
            for month in months:
                month_data = monthly_data.filter(month=month)
                component_total = sum(
                    (agg.component_breakdown or {}).get(component, 0) for agg in month_data
                )
                
                # Determine zone (green/yellow/red) - thresholds can be configured
                zone = self._determine_zone(component, component_total, 'monthly')
                
                component_trend.append({
                    'month': month.strftime('%Y-%m'),
                    'value': round(component_total, 2),
                    'zone': zone,
                    'target': None,  # Could add targets per component
                })
            
            trends[component] = component_trend
        
        return trends
    
    def _calculate_monthly_trends_by_process(self, target_month: date, device_ids: list, process_filter: Optional[str]):
        """Calculate monthly trends by process and component with color zones."""
        # Get last 6 months
        months = []
        for i in range(6):
            month = (target_month - timedelta(days=32 * i)).replace(day=1)
            months.append(month)
        months.reverse()
        
        # Get devices
        devices_query = ModbusDevice.objects.filter(is_active=True)
        if device_ids:
            devices_query = devices_query.filter(id__in=device_ids)
        devices = list(devices_query)
        
        # Get monthly aggregates
        monthly_data = MonthlyAggregate.objects.filter(month__in=months)
        if device_ids:
            monthly_data = monthly_data.filter(device_id__in=device_ids)
        
        trends = {}
        
        # For each process, calculate component trends
        for process_name in ProcessMapper.PROCESSES:
            if process_filter and process_name != process_filter.lower():
                continue
            
            # Get process breakdown for each month
            for month in months:
                month_aggregates = monthly_data.filter(month=month)
                process_breakdowns = ProcessMapper.get_all_process_breakdowns(devices, list(month_aggregates))
                
                process_breakdown = process_breakdowns.get(process_name, {})
                
                # Create trends for each component in this process
                for component, energy in process_breakdown.items():
                    trend_key = f"{component}_{process_name}"
                    if trend_key not in trends:
                        trends[trend_key] = []
                    
                    # Determine zone
                    zone = self._determine_zone(component, energy, 'monthly')
                    
                    trends[trend_key].append({
                        'month': month.strftime('%b'),
                        'value': round(energy, 2),
                        'zone': zone,
                        'process': process_name,
                        'component': component,
                    })
            
            # Also calculate overall kWh/G trend for machines
            machines_trend_key = f"machines_kwh_g_{process_name}"
            trends[machines_trend_key] = []
            for month in months:
                month_aggregates = monthly_data.filter(month=month)
                # Get efficiency data if available
                total_energy = sum(agg.total_energy_kwh for agg in month_aggregates)
                total_units = sum(
                    (agg.total_units_produced for agg in month_aggregates if agg.total_units_produced),
                    start=0
                )
                
                kwh_per_unit = (total_energy / total_units) if total_units > 0 else 0
                
                # Get target for this metric
                target = self._get_target_for_metric(month, 'kwh_per_garment', process_name)
                target_value = target.target_value if target else None
                
                zone = 'green'
                if target_value:
                    if kwh_per_unit > target_value * 1.1:
                        zone = 'red'
                    elif kwh_per_unit > target_value:
                        zone = 'yellow'
                
                trends[machines_trend_key].append({
                    'month': month.strftime('%b'),
                    'value': round(kwh_per_unit, 2),
                    'target': round(target_value, 2) if target_value else None,
                    'zone': zone,
                    'process': process_name,
                })
        
        return trends
    
    def _calculate_consumption_table(self, target_month: date, device_ids: list):
        """Calculate consumption table data (kWh, Garments, kWh/Garment)."""
        # Get last 6 months
        months = []
        for i in range(6):
            month = (target_month - timedelta(days=32 * i)).replace(day=1)
            months.append(month)
        months.reverse()
        
        table_data = []
        
        # Get devices
        devices_query = ModbusDevice.objects.filter(is_active=True)
        if device_ids:
            devices_query = devices_query.filter(id__in=device_ids)
        devices = list(devices_query)
        
        for month in months:
            monthly_aggregates = MonthlyAggregate.objects.filter(month=month)
            if device_ids:
                monthly_aggregates = monthly_aggregates.filter(device_id__in=device_ids)
            
            # Calculate totals across all devices
            total_energy = sum(agg.total_energy_kwh for agg in monthly_aggregates)
            total_garments = sum(
                (agg.total_units_produced for agg in monthly_aggregates if agg.total_units_produced),
                start=0
            )
            overall_kwh_g = (total_energy / total_garments) if total_garments > 0 else 0
            
            # Get process-specific data
            process_data = {}
            for process_name in ProcessMapper.PROCESSES:
                process_breakdowns = ProcessMapper.get_all_process_breakdowns(devices, list(monthly_aggregates))
                process_breakdown = process_breakdowns.get(process_name, {})
                process_energy = sum(process_breakdown.values())
                
                # Get production for this process (if available)
                # For demo, estimate based on total
                process_garments = int(total_garments * 0.25)  # Rough estimate
                process_kwh_g = (process_energy / process_garments) if process_garments > 0 else 0
                
                process_data[process_name] = {
                    'energy': round(process_energy, 2),
                    'garments': process_garments,
                    'kwh_g': round(process_kwh_g, 2),
                }
            
            table_data.append({
                'month': month.strftime('%b'),
                'total_energy': round(total_energy, 2),
                'total_garments': total_garments,
                'overall_kwh_g': round(overall_kwh_g, 2),
                'processes': process_data,
            })
        
        # Calculate averages
        if table_data:
            avg_energy = sum(row['total_energy'] for row in table_data) / len(table_data)
            avg_garments = sum(row['total_garments'] for row in table_data) / len(table_data)
            avg_kwh_g = sum(row['overall_kwh_g'] for row in table_data) / len(table_data)
            
            table_data.append({
                'month': 'AVG',
                'total_energy': round(avg_energy, 2),
                'total_garments': int(avg_garments),
                'overall_kwh_g': round(avg_kwh_g, 2),
                'processes': {},  # Could calculate process averages too
            })
        
        return table_data
    
    def _calculate_efficiency_metrics_enhanced(self, target_month: date, device_ids: list):
        """Calculate enhanced efficiency metrics with targets for all processes."""
        # Get last 6 months
        months = []
        for i in range(6):
            month = (target_month - timedelta(days=32 * i)).replace(day=1)
            months.append(month)
        months.reverse()
        
        metrics = {}
        
        # Get devices
        devices_query = ModbusDevice.objects.filter(is_active=True)
        if device_ids:
            devices_query = devices_query.filter(id__in=device_ids)
        devices = list(devices_query)
        
        # For each process, calculate efficiency trends
        for process_name in ProcessMapper.PROCESSES:
            process_metrics = []
            
            for month in months:
                monthly_aggregates = MonthlyAggregate.objects.filter(month=month)
                if device_ids:
                    monthly_aggregates = monthly_aggregates.filter(device_id__in=device_ids)
                
                # Get process breakdown
                process_breakdowns = ProcessMapper.get_all_process_breakdowns(devices, list(monthly_aggregates))
                process_breakdown = process_breakdowns.get(process_name, {})
                process_energy = sum(process_breakdown.values())
                
                # Get production (estimated for demo)
                total_units = sum(
                    (agg.total_units_produced for agg in monthly_aggregates if agg.total_units_produced),
                    start=0
                )
                process_units = int(total_units * 0.25)  # Rough estimate
                kwh_g = (process_energy / process_units) if process_units > 0 else 0
                
                # Get target
                target = self._get_target_for_metric(month, 'kwh_per_garment', process_name)
                target_value = target.target_value if target else None
                
                # Determine zone
                zone = 'green'
                if target_value:
                    if kwh_g > target_value * 1.1:
                        zone = 'red'
                    elif kwh_g > target_value:
                        zone = 'yellow'
                
                process_metrics.append({
                    'month': month.strftime('%b'),
                    'achieved': round(kwh_g, 2),
                    'target': round(target_value, 2) if target_value else None,
                    'zone': zone,
                })
            
            metrics[process_name] = process_metrics
        
        # Overall efficiency
        overall_metrics = []
        for month in months:
            monthly_aggregates = MonthlyAggregate.objects.filter(month=month)
            if device_ids:
                monthly_aggregates = monthly_aggregates.filter(device_id__in=device_ids)
            
            total_energy = sum(agg.total_energy_kwh for agg in monthly_aggregates)
            total_units = sum(
                (agg.total_units_produced for agg in monthly_aggregates if agg.total_units_produced),
                start=0
            )
            overall_kwh_g = (total_energy / total_units) if total_units > 0 else 0
            
            # Get overall target
            target = self._get_target_for_metric(month, 'kwh_per_garment', 'overall')
            target_value = target.target_value if target else 80.0  # Default target
            
            zone = 'green'
            if overall_kwh_g > target_value * 1.1:
                zone = 'red'
            elif overall_kwh_g > target_value:
                zone = 'yellow'
            
            overall_metrics.append({
                'month': month.strftime('%b'),
                'achieved': round(overall_kwh_g, 2),
                'target': round(target_value, 2),
                'zone': zone,
            })
        
        metrics['overall'] = overall_metrics
        
        return metrics
    
    def _get_target_for_metric(self, month: date, metric_name: str, process: str) -> Optional[Target]:
        """Get target for a specific metric, month, and process."""
        try:
            month_start = month
            month_end = (month + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            
            # Try to find process-specific target first
            target = Target.objects.filter(
                metric_name=metric_name,
                period_start__lte=month_start,
                period_end__gte=month_end,
                target_period='monthly',
            ).first()
            
            return target
        except Exception:
            return None
    
    def _determine_zone(self, component: str, value: float, period: str) -> str:
        """
        Determine color zone (green/yellow/red) based on value.
        Thresholds should be configurable - using defaults for now.
        """
        # These thresholds should ideally come from configuration or benchmarks
        thresholds = {
            'lights': {'green': 17000, 'yellow': 19000},
            'machines': {'green': 35000, 'yellow': 45000},
            'exhaust_fan': {'green': 11000, 'yellow': 13000},
            'hvac': {'green': 4500, 'yellow': 5500},
        }
        
        if component.lower() not in thresholds:
            return 'green'
        
        thresh = thresholds[component.lower()]
        
        if value <= thresh['green']:
            return 'green'
        elif value <= thresh['yellow']:
            return 'yellow'
        else:
            return 'red'


class EnergyMixView(APIView):
    """Energy mix breakdown endpoint."""
    
    def get(self, request):
        date_str = request.query_params.get('date')
        month_str = request.query_params.get('month')
        device_ids = request.query_params.get('devices', '').split(',')
        device_ids = [int(d) for d in device_ids if d.isdigit()]
        
        if month_str:
            target_month = datetime.strptime(month_str, '%Y-%m').date().replace(day=1)
            aggregates = MonthlyAggregate.objects.filter(month=target_month)
        elif date_str:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            aggregates = DailyAggregate.objects.filter(date=target_date)
        else:
            target_date = timezone.now().date()
            aggregates = DailyAggregate.objects.filter(date=target_date)
        
        if device_ids:
            aggregates = aggregates.filter(device_id__in=device_ids)
        
        # Convert to common format and calculate mix
        energy_mixes = []
        for agg in aggregates:
            breakdown = agg.component_breakdown or {}
            total = agg.total_energy_kwh if hasattr(agg, 'total_energy_kwh') else 0
            
            if total == 0:
                continue
            
            components = []
            for component, value in breakdown.items():
                components.append({
                    'name': component.replace('_', ' ').title(),
                    'value': round(value, 2),
                    'percentage': round((value / total * 100), 2),
                })
            
            if agg.device:
                # Use process_area and floor for display name
                parts = []
                if agg.device.process_area and agg.device.process_area != 'general':
                    parts.append(agg.device.get_process_area_display())
                if agg.device.floor and agg.device.floor != 'none':
                    parts.append(agg.device.get_floor_display())
                
                if parts:
                    device_name = f"{agg.device.name} ({', '.join(parts)})"
                else:
                    device_name = agg.device.name
            else:
                device_name = 'Overall'
            energy_mixes.append({
                'device_name': device_name,
                'total_kwh': round(total, 2),
                'load_kw': round(getattr(agg, 'avg_power_kw', 0), 2),
                'components': sorted(components, key=lambda x: x['value'], reverse=True),
            })
        
        return Response(energy_mixes)
