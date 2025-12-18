from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Sum, Avg, Max, Min, Count, Q, F
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from django.utils import timezone
from datetime import datetime, timedelta
from .models import EnergySummary, ShiftDefinition, ShiftEnergyData
from modbus.models import ModbusDevice
from .serializers import EnergySummarySerializer, ShiftDefinitionSerializer, ShiftEnergyDataSerializer


class EnergySummaryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing energy summaries.
    """
    queryset = EnergySummary.objects.all()
    serializer_class = EnergySummarySerializer
    filterset_fields = ['device', 'interval_type']
    search_fields = ['device__name']
    ordering_fields = ['timestamp', 'total_energy_kwh']
    ordering = ['-timestamp']

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by date range
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date:
            queryset = queryset.filter(timestamp__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__lte=end_date)
        
        # Filter by process area
        process_area = self.request.query_params.get('process_area')
        if process_area:
            queryset = queryset.filter(device__process_area=process_area)
        
        # Filter by floor
        floor = self.request.query_params.get('floor')
        if floor:
            queryset = queryset.filter(device__floor=floor)
        
        # Filter by load type
        load_type = self.request.query_params.get('load_type')
        if load_type:
            queryset = queryset.filter(device__load_type=load_type)
        
        # Filter by device IDs
        device_ids = self.request.query_params.get('device_ids')
        if device_ids:
            device_id_list = [int(id) for id in device_ids.split(',')]
            queryset = queryset.filter(device_id__in=device_id_list)
        
        return queryset.select_related('device')

    @action(detail=False, methods=['get'], url_path='dashboard-stats', url_name='dashboard-stats')
    def dashboard_stats(self, request):
        """Get dashboard statistics"""
        queryset = self.get_queryset()
        
        # Apply filters
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        process_area = request.query_params.get('process_area')
        floor = request.query_params.get('floor')
        include_main = request.query_params.get('include_main', 'false').lower() == 'true'
        
        if start_date:
            queryset = queryset.filter(timestamp__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__lte=end_date)
        if process_area:
            queryset = queryset.filter(device__process_area=process_area)
        if floor:
            queryset = queryset.filter(device__floor=floor)
        
        daily_data = queryset.filter(interval_type='daily')
        
        # Separate main feeders and consumers
        consumers_data = daily_data.exclude(device__load_type='MAIN')
        main_feeders_data = daily_data.filter(device__load_type='MAIN')
        
        stats = {
            'total_energy_kwh': daily_data.aggregate(Sum('total_energy_kwh'))['total_energy_kwh__sum'] or 0,
            'avg_daily_energy_kwh': daily_data.aggregate(Avg('total_energy_kwh'))['total_energy_kwh__avg'] or 0,
            'peak_daily_energy_kwh': daily_data.aggregate(Max('total_energy_kwh'))['total_energy_kwh__max'] or 0,
            'total_cost': daily_data.aggregate(Sum('energy_cost'))['energy_cost__sum'] or 0,
            'device_count': daily_data.values('device').distinct().count(),
            'day_count': daily_data.values('timestamp__date').distinct().count(),
            # Separate stats for consumers and main feeders
            'consumers_energy_kwh': consumers_data.aggregate(Sum('total_energy_kwh'))['total_energy_kwh__sum'] or 0,
            'main_feeders_energy_kwh': main_feeders_data.aggregate(Sum('total_energy_kwh'))['total_energy_kwh__sum'] or 0,
            'consumers_count': consumers_data.values('device').distinct().count(),
            'main_feeders_count': main_feeders_data.values('device').distinct().count(),
        }
        
        return Response(stats)

    @action(detail=False, methods=['get'], url_path='trends', url_name='trends')
    def trends(self, request):
        """Get energy trends over time"""
        queryset = self.get_queryset().filter(interval_type='daily')
        
        # Option to include/exclude main feeders
        include_main = request.query_params.get('include_main', 'false').lower() == 'true'
        if not include_main:
            queryset = queryset.exclude(device__load_type='MAIN')
        
        # Group by date
        group_by = request.query_params.get('group_by', 'day')  # day, week, month
        
        if group_by == 'week':
            queryset = queryset.annotate(period=TruncWeek('timestamp'))
        elif group_by == 'month':
            queryset = queryset.annotate(period=TruncMonth('timestamp'))
        else:
            queryset = queryset.annotate(period=TruncDate('timestamp'))
        
        trends = queryset.values('period').annotate(
            total_energy=Sum('total_energy_kwh'),
            avg_power=Avg('avg_power_kw'),
            record_count=Count('id')
        ).order_by('period')
        
        return Response(list(trends))

    @action(detail=False, methods=['get'], url_path='by-process-area', url_name='by-process-area')
    def by_process_area(self, request):
        """Get energy breakdown by process area (excluding main feeders)"""
        queryset = self.get_queryset().filter(interval_type='daily')
        
        # Exclude main feeders (load_type='MAIN') from process area breakdown
        # as they are incoming feeders, not consumers
        queryset = queryset.exclude(device__load_type='MAIN')
        
        # Calculate total for percentage calculation
        total_energy = queryset.aggregate(Sum('total_energy_kwh'))['total_energy_kwh__sum'] or 0
        
        breakdown = queryset.values('device__process_area').annotate(
            total_energy=Sum('total_energy_kwh'),
            avg_daily=Avg('total_energy_kwh'),
            device_count=Count('device', distinct=True),
            record_count=Count('id')
        ).order_by('-total_energy')
        
        # Add percentage calculation
        result = []
        for item in breakdown:
            percentage = (item['total_energy'] / total_energy * 100) if total_energy > 0 else 0
            result.append({
                **item,
                'percentage': round(percentage, 2)
            })
        
        return Response(result)

    @action(detail=False, methods=['get'], url_path='by-floor', url_name='by-floor')
    def by_floor(self, request):
        """Get energy breakdown by floor (excluding main feeders)"""
        queryset = self.get_queryset().filter(interval_type='daily')
        
        # Exclude main feeders from floor breakdown
        queryset = queryset.exclude(device__load_type='MAIN')
        
        breakdown = queryset.values('device__floor').annotate(
            total_energy=Sum('total_energy_kwh'),
            avg_daily=Avg('total_energy_kwh'),
            device_count=Count('device', distinct=True),
            record_count=Count('id')
        ).order_by('-total_energy')
        
        return Response(list(breakdown))

    @action(detail=False, methods=['get'], url_path='by-device', url_name='by-device')
    def by_device(self, request):
        """Get energy breakdown by device"""
        queryset = self.get_queryset().filter(interval_type='daily')
        
        # Option to include/exclude main feeders
        include_main = request.query_params.get('include_main', 'false').lower() == 'true'
        if not include_main:
            queryset = queryset.exclude(device__load_type='MAIN')
        
        limit = int(request.query_params.get('limit', 20))
        
        breakdown = queryset.values(
            'device__id', 'device__name', 'device__process_area', 
            'device__floor', 'device__load_type'
        ).annotate(
            total_energy=Sum('total_energy_kwh'),
            avg_daily=Avg('total_energy_kwh'),
            peak_daily=Max('total_energy_kwh'),
            record_count=Count('id')
        ).order_by('-total_energy')[:limit]
        
        return Response(list(breakdown))

    @action(detail=False, methods=['get'], url_path='main-feeders', url_name='main-feeders')
    def main_feeders(self, request):
        """Get main feeders (incoming feeders) data separately"""
        queryset = self.get_queryset().filter(interval_type='daily', device__load_type='MAIN')
        
        breakdown = queryset.values(
            'device__id', 'device__name', 'device__process_area', 
            'device__floor'
        ).annotate(
            total_energy=Sum('total_energy_kwh'),
            avg_daily=Avg('total_energy_kwh'),
            peak_daily=Max('total_energy_kwh'),
            record_count=Count('id')
        ).order_by('-total_energy')
        
        return Response(list(breakdown))

    def _infer_sub_department(self, device_name):
        """Infer sub-department from device name"""
        name_lower = device_name.lower()
        
        if 'office' in name_lower or 'offices' in name_lower:
            return 'Offices'
        elif 'light' in name_lower or 'lp' in name_lower:
            return 'Lights'
        elif 'hvac' in name_lower:
            return 'HVAC'
        elif 'exhaust' in name_lower or 'exast' in name_lower:
            return 'Exhaust'
        elif 'ups' in name_lower:
            return 'UPS'
        elif 'main' in name_lower or 'mpb' in name_lower:
            return 'Main'
        elif 'misc' in name_lower:
            return 'Misc'
        elif 'mcc' in name_lower or 'machine' in name_lower or 'btd' in name_lower or 'laser' in name_lower or 'cutter' in name_lower or 'stitching' in name_lower or 'hanger' in name_lower:
            return 'Machine'
        else:
            return 'Other'

    @action(detail=False, methods=['get'], url_path='by-sub-department', url_name='by-sub-department')
    def by_sub_department(self, request):
        """Get energy breakdown by sub-department within each process area"""
        queryset = self.get_queryset().filter(interval_type='daily')
        
        # Exclude main feeders
        queryset = queryset.exclude(device__load_type='MAIN')
        
        # Get all devices with their sub-departments
        devices_data = queryset.values(
            'device__id', 'device__name', 'device__process_area'
        ).annotate(
            total_energy=Sum('total_energy_kwh')
        )
        
        # Group by process area and sub-department
        result = {}
        for item in devices_data:
            process_area = item['device__process_area'] or 'general'
            sub_dept = self._infer_sub_department(item['device__name'])
            energy = item['total_energy']
            
            if process_area not in result:
                result[process_area] = {}
            if sub_dept not in result[process_area]:
                result[process_area][sub_dept] = {
                    'total_energy': 0,
                    'device_count': 0,
                    'devices': []
                }
            
            result[process_area][sub_dept]['total_energy'] += energy
            result[process_area][sub_dept]['device_count'] += 1
            result[process_area][sub_dept]['devices'].append({
                'id': item['device__id'],
                'name': item['device__name'],
                'energy': energy
            })
        
        # Calculate percentages and format response
        formatted_result = []
        for process_area, sub_depts in result.items():
            total_area_energy = sum(d['total_energy'] for d in sub_depts.values())
            
            area_data = {
                'process_area': process_area,
                'total_energy': total_area_energy,
                'sub_departments': []
            }
            
            for sub_dept, data in sorted(sub_depts.items(), key=lambda x: x[1]['total_energy'], reverse=True):
                percentage = (data['total_energy'] / total_area_energy * 100) if total_area_energy > 0 else 0
                area_data['sub_departments'].append({
                    'sub_department': sub_dept,
                    'total_energy': round(data['total_energy'], 2),
                    'percentage': round(percentage, 2),
                    'device_count': data['device_count']
                })
            
            formatted_result.append(area_data)
        
        return Response(formatted_result)

    @action(detail=False, methods=['get'], url_path='heatmap-data', url_name='heatmap-data')
    def heatmap_data(self, request):
        """Get heatmap data (device vs date)"""
        queryset = self.get_queryset().filter(interval_type='daily')
        
        # Option to include/exclude main feeders
        include_main = request.query_params.get('include_main', 'false').lower() == 'true'
        if not include_main:
            queryset = queryset.exclude(device__load_type='MAIN')
        
        # Get date range
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        if not start_date or not end_date:
            # Default to last 30 days
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=30)
        
        queryset = queryset.filter(
            timestamp__date__gte=start_date,
            timestamp__date__lte=end_date
        )
        
        # Get data grouped by device and date
        data = queryset.values(
            'device__id', 'device__name', 'timestamp__date'
        ).annotate(
            energy=Sum('total_energy_kwh')
        ).order_by('device__name', 'timestamp__date')
        
        # Transform to heatmap format
        devices = {}
        dates = set()
        
        for item in data:
            device_id = item['device__id']
            device_name = item['device__name']
            date = item['timestamp__date'].isoformat()
            energy = item['energy']
            
            dates.add(date)
            if device_id not in devices:
                devices[device_id] = {
                    'id': device_id,
                    'name': device_name,
                    'data': {}
                }
            devices[device_id]['data'][date] = energy
        
        return Response({
            'devices': list(devices.values()),
            'dates': sorted(list(dates))
        })


class ShiftEnergyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ShiftEnergyData.objects.all()
    serializer_class = ShiftEnergyDataSerializer
    filterset_fields = ['shift', 'device', 'shift_date']
    ordering = ['-shift_date']


class ShiftDefinitionViewSet(viewsets.ModelViewSet):
    queryset = ShiftDefinition.objects.all()
    serializer_class = ShiftDefinitionSerializer
    filterset_fields = ['is_active']


class EnergyAnalyticsSummaryView(APIView):
    """
    Comprehensive energy analytics summary endpoint.
    """
    def get(self, request):
        # Get filter parameters
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        process_area = request.query_params.get('process_area')
        floor = request.query_params.get('floor')
        load_type = request.query_params.get('load_type')
        device_ids = request.query_params.get('device_ids')
        
        # Build queryset
        queryset = EnergySummary.objects.filter(interval_type='daily').select_related('device')
        
        if start_date:
            queryset = queryset.filter(timestamp__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__lte=end_date)
        if process_area:
            queryset = queryset.filter(device__process_area=process_area)
        if floor:
            queryset = queryset.filter(device__floor=floor)
        if load_type:
            queryset = queryset.filter(device__load_type=load_type)
        if device_ids:
            device_id_list = [int(id) for id in device_ids.split(',')]
            queryset = queryset.filter(device_id__in=device_id_list)
        
        # Overall stats
        overall_stats = queryset.aggregate(
            total_energy=Sum('total_energy_kwh'),
            avg_daily=Avg('total_energy_kwh'),
            peak_daily=Max('total_energy_kwh'),
            min_daily=Min('total_energy_kwh'),
            total_cost=Sum('energy_cost'),
            device_count=Count('device', distinct=True),
            day_count=Count('timestamp__date', distinct=True)
        )
        
        # Separate main feeders from consumers
        main_feeders = queryset.filter(device__load_type='MAIN')
        consumers = queryset.exclude(device__load_type='MAIN')
        
        # Process area breakdown (consumers only)
        process_breakdown = consumers.values('device__process_area').annotate(
            total_energy=Sum('total_energy_kwh'),
            avg_daily=Avg('total_energy_kwh'),
            device_count=Count('device', distinct=True),
            percentage=F('total_energy') * 100.0 / overall_stats['total_energy'] if overall_stats['total_energy'] else 0
        ).order_by('-total_energy')
        
        # Floor breakdown (consumers only)
        floor_breakdown = consumers.values('device__floor').annotate(
            total_energy=Sum('total_energy_kwh'),
            avg_daily=Avg('total_energy_kwh'),
            device_count=Count('device', distinct=True),
            percentage=F('total_energy') * 100.0 / overall_stats['total_energy'] if overall_stats['total_energy'] else 0
        ).order_by('-total_energy')
        
        # Top devices (consumers only)
        top_devices = consumers.values(
            'device__id', 'device__name', 'device__process_area', 'device__floor'
        ).annotate(
            total_energy=Sum('total_energy_kwh'),
            avg_daily=Avg('total_energy_kwh'),
            peak_daily=Max('total_energy_kwh')
        ).order_by('-total_energy')[:10]
        
        # Main feeders summary
        main_feeders_summary = main_feeders.values(
            'device__id', 'device__name', 'device__process_area', 'device__floor'
        ).annotate(
            total_energy=Sum('total_energy_kwh'),
            avg_daily=Avg('total_energy_kwh'),
            peak_daily=Max('total_energy_kwh')
        ).order_by('-total_energy')
        
        # Daily trends (consumers only for process analysis)
        daily_trends = consumers.annotate(
            date=TruncDate('timestamp')
        ).values('date').annotate(
            total_energy=Sum('total_energy_kwh'),
            avg_power=Avg('avg_power_kw'),
            device_count=Count('device', distinct=True)
        ).order_by('date')
        
        return Response({
            'overall_stats': overall_stats,
            'process_breakdown': list(process_breakdown),
            'floor_breakdown': list(floor_breakdown),
            'top_devices': list(top_devices),
            'main_feeders': list(main_feeders_summary),
            'daily_trends': list(daily_trends)
        })


class EnergyAnalyticsReportView(APIView):
    """
    Streams a CSV report for the requested analytics window.
    """
    def get(self, request):
        # Implementation for CSV export if needed
        return Response({"detail": "CSV export not implemented yet"})
