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


class LiveInsightsView(APIView):
    """
    Queries InfluxDB directly on each request and returns live comparative
    insights. Yesterday and same-day-last-week windows are capped at the same
    elapsed time as today, so all three periods are directly comparable.
    """

    INFLUX_URL = 'http://localhost:8086'
    INFLUX_TOKEN = 'PQF2DMjfNtn__ooeubqDTUaiXegywYbzUBNyTjpvd7qoUrmq9PpGVyS8lybnmf-sszI7V1HEwZWdSvgkEGfzcQ=='
    INFLUX_ORG = 'DATABRIDGE'
    INFLUX_BUCKET = 'databridge'
    # Raw data exists from ~2026-03-28 onwards; 1m downsampled covers older history.
    # Both are queried together so all time windows have complete coverage.
    INFLUX_MEAS_FILTER = '(r._measurement == "energy_measurements" or r._measurement == "energy_measurements_1m")'

    ELECTRICITY_DEVICE = 'Ombre Apparel LT-1 Main'
    FLOW_DEVICE = 'Ombre Apparel Flow meter'
    PRODUCTION_THRESHOLD_W = 10_000

    def _query_api(self):
        from influxdb_client import InfluxDBClient
        return InfluxDBClient(url=self.INFLUX_URL, token=self.INFLUX_TOKEN, org=self.INFLUX_ORG).query_api()

    def _flux(self, q):
        return [r for t in self._query_api().query(q) for r in t.records]

    # ── Single-query stats (mean, peak, count) ───────────────────────────────

    def _elec_stats(self, start, stop):
        """Mean power (W), peak power (W), record count — single Flux query."""
        records = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.ELECTRICITY_DEVICE}"
         and r._field == "Active Three-phase Power")
  |> reduce(
       fn: (r, accumulator) => ({{
         sum:   accumulator.sum   + r._value,
         count: accumulator.count + 1.0,
         max:   if r._value > accumulator.max then r._value else accumulator.max
       }}),
       identity: {{sum: 0.0, count: 0.0, max: 0.0}}
     )
''')
        if not records:
            return {'mean_w': 0.0, 'peak_w': 0.0, 'has_data': False}
        v = records[0].values
        count = v.get('count', 0)
        if count == 0:
            return {'mean_w': 0.0, 'peak_w': 0.0, 'has_data': False}
        return {
            'mean_w': v['sum'] / count,
            'peak_w': v['max'],
            'has_data': True,
        }

    def _flow_stats(self, start, stop):
        """Flow volume (counter delta), peak & mean instantaneous flow."""
        # Counter delta
        hi = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.FLOW_DEVICE}"
         and r._field == "Total Amount of Flow")
  |> max()
''')
        lo = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.FLOW_DEVICE}"
         and r._field == "Total Amount of Flow")
  |> min()
''')
        has_data = bool(hi and lo)
        max_val = (hi[0].get_value() or 0) if hi else 0
        min_val = (lo[0].get_value() or 0) if lo else 0
        volume = max(0.0, max_val - min_val)

        # Peak instantaneous flow
        peak_r = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.FLOW_DEVICE}"
         and r._field == "Instantaneous Flow")
  |> max()
''')
        peak_flow = round((peak_r[0].get_value() or 0.0), 2) if peak_r else 0.0

        # Mean instantaneous flow (non-zero only)
        mean_r = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.FLOW_DEVICE}"
         and r._field == "Instantaneous Flow")
  |> filter(fn: (r) => r._value > 0)
  |> mean()
''')
        mean_flow = round((mean_r[0].get_value() or 0.0), 2) if mean_r else 0.0

        return {
            'volume': round(volume, 0),
            'peak_flow': peak_flow,
            'mean_flow': mean_flow,
            'has_data': has_data,
        }

    def _hourly_power(self, start, stop):
        records = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.ELECTRICITY_DEVICE}"
         and r._field == "Active Three-phase Power")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
''')
        return [{'time': r.get_time().isoformat(), 'power_w': round(r.get_value() or 0, 1)} for r in records]

    def _power_quality(self, start, stop):
        records = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.ELECTRICITY_DEVICE}"
         and (r._field == "Active Three-phase Power" or r._field == "Apparent Three-phase Power"))
  |> filter(fn: (r) => r._value > {self.PRODUCTION_THRESHOLD_W})
  |> group(columns: ["_field"])
  |> mean()
''')
        vals = {r.get_field(): r.get_value() or 0.0 for r in records}
        active = vals.get('Active Three-phase Power', 0.0)
        apparent = vals.get('Apparent Three-phase Power', 0.0)
        pf = round(active / apparent, 4) if apparent > 0 else None
        return {'active_w': active, 'apparent_va': apparent, 'power_factor': pf}

    def _phase_currents(self, start, stop):
        records = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.ELECTRICITY_DEVICE}"
         and (r._field == "L1 Current" or r._field == "L2 Current" or r._field == "L3 Current"))
  |> filter(fn: (r) => r._value > 10)
  |> group(columns: ["_field"])
  |> mean()
''')
        return {r.get_field(): round(r.get_value() or 0.0, 2) for r in records}

    @staticmethod
    def _energy_kwh(mean_w, hours):
        return round(mean_w * hours / 1000.0, 1)

    @staticmethod
    def _pct(current, reference):
        if reference and reference > 0:
            return round((current - reference) / reference * 100, 1)
        return None

    @staticmethod
    def _fmt(dt):
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    def get(self, request):
        from datetime import datetime, timedelta, timezone as dt_tz

        now = datetime.now(dt_tz.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elapsed = now - today_start                          # timedelta since midnight
        elapsed_hrs = elapsed.total_seconds() / 3600

        yesterday_start  = today_start - timedelta(days=1)
        lwsd_start       = today_start - timedelta(weeks=1)  # same day last week

        # ── "Up to current time" stops for fair comparison ───────────────
        # e.g. if it is 06:30 now, compare today 00–06:30 vs
        # yesterday 00–06:30 vs same-day-last-week 00–06:30
        yest_same_time   = yesterday_start + elapsed
        lwsd_same_time   = lwsd_start + elapsed

        # This week Mon→now
        days_since_mon   = now.weekday()
        this_week_start  = today_start - timedelta(days=days_since_mon)
        week_hrs         = (now - this_week_start).total_seconds() / 3600

        # Same calendar week ~4 weeks ago (Mon→Sun full week)
        prev_week_start  = this_week_start - timedelta(weeks=4)
        prev_week_end    = prev_week_start + timedelta(weeks=1)

        # Last 7 days — used for power quality / phase averages
        last7_start      = today_start - timedelta(days=7)

        f = self._fmt
        now_s      = f(now)
        today_s    = f(today_start)
        yest_s     = f(yesterday_start)
        yest_st_s  = f(yest_same_time)     # yesterday up-to-same-time
        lwsd_s     = f(lwsd_start)
        lwsd_st_s  = f(lwsd_same_time)     # last-week same-day up-to-same-time
        week_s     = f(this_week_start)
        pw_s       = f(prev_week_start)
        pw_e       = f(prev_week_end)
        l7_s       = f(last7_start)

        # Human-readable cutoff label shown in UI, e.g. "06:32 UTC"
        cutoff_label = now.strftime('%H:%M UTC')

        try:
            # ── Electricity ──────────────────────────────────────────────
            td   = self._elec_stats(today_s, now_s)
            yd   = self._elec_stats(yest_s,  yest_st_s)   # same elapsed hours
            lwsd = self._elec_stats(lwsd_s,  lwsd_st_s)   # same elapsed hours

            td_kwh   = self._energy_kwh(td['mean_w'],   elapsed_hrs)
            yd_kwh   = self._energy_kwh(yd['mean_w'],   elapsed_hrs)
            lwsd_kwh = self._energy_kwh(lwsd['mean_w'], elapsed_hrs)

            wk_stats = self._elec_stats(week_s, now_s)
            wk_kwh   = self._energy_kwh(wk_stats['mean_w'], week_hrs)

            pw_stats = self._elec_stats(pw_s, pw_e)
            pw_kwh   = self._energy_kwh(pw_stats['mean_w'], 168.0)

            pq = self._power_quality(l7_s, now_s)
            pf = pq['power_factor']

            currents = self._phase_currents(l7_s, now_s)
            l1 = currents.get('L1 Current', 0)
            l2 = currents.get('L2 Current', 0)
            l3 = currents.get('L3 Current', 0)

            if l1 > 0 and l2 > 0 and l3 > 0:
                avg_i   = (l1 + l2 + l3) / 3
                max_dev = max(abs(l1 - avg_i), abs(l2 - avg_i), abs(l3 - avg_i))
                imb_pct = round(max_dev / avg_i * 100, 1)
                hi_phase = max([('L1', l1), ('L2', l2), ('L3', l3)], key=lambda x: x[1])[0]
                lo_phase = min([('L1', l1), ('L2', l2), ('L3', l3)], key=lambda x: x[1])[0]
            else:
                avg_i = imb_pct = 0
                hi_phase = lo_phase = 'N/A'

            td_hourly = self._hourly_power(today_s, now_s)
            yd_hourly = self._hourly_power(yest_s,  yest_st_s)

            # ── Flowmeter ────────────────────────────────────────────────
            td_flow   = self._flow_stats(today_s, now_s)
            yd_flow   = self._flow_stats(yest_s,  yest_st_s)
            lwsd_flow = self._flow_stats(lwsd_s,  lwsd_st_s)

            # ── Operational insights ─────────────────────────────────────
            insights = []

            if pf is not None and pf < 0.95:
                insights.append({
                    'category': 'Power Quality',
                    'severity': 'warning' if pf >= 0.90 else 'critical',
                    'title': f'Power factor {pf:.3f} — below 0.95 penalty threshold',
                    'detail': (
                        f'Average production-hour PF is {pf:.3f}. Pakistani DISCOs typically '
                        f'apply a surcharge when PF falls below 0.95. The dominant reactive '
                        f'component is inductive (~30 kVAR during peak production), indicating '
                        f'motor-heavy loads without capacitor compensation.'
                    ),
                    'action': 'Install a ~15–20 kVAR automatic power factor correction (APFC) bank.',
                })

            if imb_pct and imb_pct > 10:
                insights.append({
                    'category': 'Phase Balance',
                    'severity': 'critical' if imb_pct > 20 else 'warning',
                    'title': f'Phase current imbalance {imb_pct:.1f}% — standard is ≤10%',
                    'detail': (
                        f'{hi_phase} carries the highest load (avg {max(l1, l2, l3):.1f} A) '
                        f'while {lo_phase} carries the least (avg {min(l1, l2, l3):.1f} A). '
                        f'Average: {avg_i:.1f} A. Imbalance causes excess neutral current, '
                        f'uneven transformer winding stress, and higher I²R losses on {hi_phase}.'
                    ),
                    'action': f'Redistribute single-phase loads from {hi_phase} to {lo_phase} on the MCC.',
                })

            if lwsd['has_data'] and lwsd_kwh > 0:
                drift = self._pct(td_kwh, lwsd_kwh)
                if drift is not None and abs(drift) > 15:
                    direction = 'higher' if drift > 0 else 'lower'
                    insights.append({
                        'category': 'Consumption Trend',
                        'severity': 'info',
                        'title': f'Today is {abs(drift):.1f}% {direction} than same day last week (to {cutoff_label})',
                        'detail': f'Today: {td_kwh} kWh vs same day last week: {lwsd_kwh} kWh — both measured over {elapsed_hrs:.1f} h.',
                        'action': 'Verify with production schedule — check for idle equipment or unusual loads.',
                    })

            if yd_flow['has_data'] and yd_flow['volume'] > 0:
                fdrift = self._pct(td_flow['volume'], yd_flow['volume'])
                if fdrift is not None and abs(fdrift) > 20:
                    direction = 'higher' if fdrift > 0 else 'lower'
                    insights.append({
                        'category': 'Water Consumption',
                        'severity': 'info',
                        'title': f'Water flow today is {abs(fdrift):.1f}% {direction} than yesterday (to {cutoff_label})',
                        'detail': f'Today: {td_flow["volume"]:.0f} units vs yesterday: {yd_flow["volume"]:.0f} units — same {elapsed_hrs:.1f} h window.',
                        'action': 'Cross-check with production batch size to assess water efficiency.',
                    })

            return Response({
                'generated_at': now.isoformat(),
                'cutoff_label': cutoff_label,
                'elapsed_hours': round(elapsed_hrs, 2),
                'electricity': {
                    'device': self.ELECTRICITY_DEVICE,
                    'today': {
                        'energy_kwh': td_kwh,
                        'mean_power_kw': round(td['mean_w'] / 1000, 2),
                        'peak_kw': round(td['peak_w'] / 1000, 1),
                        'hours_elapsed': round(elapsed_hrs, 1),
                        'has_data': td['has_data'],
                    },
                    'yesterday': {
                        'date': yesterday_start.strftime('%Y-%m-%d'),
                        'energy_kwh': yd_kwh,
                        'mean_power_kw': round(yd['mean_w'] / 1000, 2),
                        'peak_kw': round(yd['peak_w'] / 1000, 1),
                        'has_data': yd['has_data'],
                    },
                    'same_day_last_week': {
                        'date': lwsd_start.strftime('%Y-%m-%d'),
                        'energy_kwh': lwsd_kwh,
                        'mean_power_kw': round(lwsd['mean_w'] / 1000, 2),
                        'peak_kw': round(lwsd['peak_w'] / 1000, 1),
                        'has_data': lwsd['has_data'],
                    },
                    'this_week': {
                        'week_start': this_week_start.strftime('%Y-%m-%d'),
                        'days_elapsed': days_since_mon + 1,
                        'energy_kwh': wk_kwh,
                        'has_data': wk_stats['has_data'],
                    },
                    'same_week_prev_month': {
                        'week_start': prev_week_start.strftime('%Y-%m-%d'),
                        'week_end': prev_week_end.strftime('%Y-%m-%d'),
                        'energy_kwh': pw_kwh,
                        'has_data': pw_stats['has_data'],
                        'note': 'Full 7-day window 4 weeks ago; no data if collection started recently',
                    },
                    'comparisons': {
                        'today_vs_yesterday_kwh_pct': self._pct(td_kwh, yd_kwh) if yd['has_data'] else None,
                        'today_vs_same_day_last_week_pct': self._pct(td_kwh, lwsd_kwh) if lwsd['has_data'] else None,
                        'peak_today_vs_yesterday_pct': self._pct(td['peak_w'], yd['peak_w']) if yd['has_data'] else None,
                        'this_week_vs_prev_month_same_week_pct': self._pct(wk_kwh, pw_kwh) if pw_stats['has_data'] else None,
                    },
                    'power_quality': {
                        'power_factor': pf,
                        'active_power_kw': round(pq['active_w'] / 1000, 1),
                        'apparent_power_kva': round(pq['apparent_va'] / 1000, 1),
                        'status': (
                            'good' if pf and pf >= 0.95
                            else 'warning' if pf and pf >= 0.90
                            else 'critical'
                        ),
                        'note': 'Averaged over last 7 days, production hours only (>10 kW)',
                    },
                    'phase_balance': {
                        'l1_avg_a': round(l1, 1),
                        'l2_avg_a': round(l2, 1),
                        'l3_avg_a': round(l3, 1),
                        'avg_a': round(avg_i, 1),
                        'imbalance_pct': imb_pct,
                        'highest_phase': hi_phase,
                        'lowest_phase': lo_phase,
                        'status': 'critical' if imb_pct > 20 else ('warning' if imb_pct > 10 else 'good'),
                        'note': 'Averaged over last 7 days, production hours only (current > 10 A)',
                    },
                    'hourly_today': td_hourly,
                    'hourly_yesterday': yd_hourly,
                },
                'flowmeter': {
                    'device': self.FLOW_DEVICE,
                    'today': {
                        'volume_units': td_flow['volume'],
                        'peak_flow_rate': td_flow['peak_flow'],
                        'mean_flow_rate': td_flow['mean_flow'],
                        'hours_elapsed': round(elapsed_hrs, 1),
                        'has_data': td_flow['has_data'],
                    },
                    'yesterday': {
                        'date': yesterday_start.strftime('%Y-%m-%d'),
                        'volume_units': yd_flow['volume'],
                        'peak_flow_rate': yd_flow['peak_flow'],
                        'has_data': yd_flow['has_data'],
                    },
                    'same_day_last_week': {
                        'date': lwsd_start.strftime('%Y-%m-%d'),
                        'volume_units': lwsd_flow['volume'],
                        'has_data': lwsd_flow['has_data'],
                    },
                    'comparisons': {
                        'today_vs_yesterday_pct': self._pct(td_flow['volume'], yd_flow['volume']) if yd_flow['has_data'] else None,
                        'today_vs_same_day_last_week_pct': self._pct(td_flow['volume'], lwsd_flow['volume']) if lwsd_flow['has_data'] else None,
                    },
                    'data_quality': {
                        'temperature_available': False,
                        'pressure_available': False,
                        'heat_meter_incrementing': False,
                        'note': 'Temperature, Pressure, and Heat meter registers read 0 — check sensor wiring and register addresses',
                    },
                },
                'operational_insights': insights,
            })

        except Exception as e:
            import traceback
            return Response({'error': str(e), 'traceback': traceback.format_exc()}, status=500)


class ForecastCompareView(APIView):
    """
    GET /api/analytics/forecast/compare/?date=YYYY-MM-DD
    Returns stored forecast for `date` alongside actual InfluxDB data for that day,
    with per-hour and summary accuracy metrics.
    """

    INFLUX_URL    = 'http://localhost:8086'
    INFLUX_TOKEN  = 'PQF2DMjfNtn__ooeubqDTUaiXegywYbzUBNyTjpvd7qoUrmq9PpGVyS8lybnmf-sszI7V1HEwZWdSvgkEGfzcQ=='
    INFLUX_ORG    = 'DATABRIDGE'
    INFLUX_BUCKET = 'databridge'
    INFLUX_MEAS_FILTER = '(r._measurement == "energy_measurements" or r._measurement == "energy_measurements_1m")'
    ELECTRICITY_DEVICE = 'Ombre Apparel LT-1 Main'
    FLOW_DEVICE        = 'Ombre Apparel Flow meter'

    def _flux(self, q):
        from influxdb_client import InfluxDBClient
        api = InfluxDBClient(url=self.INFLUX_URL, token=self.INFLUX_TOKEN,
                             org=self.INFLUX_ORG).query_api()
        return [r for t in api.query(q) for r in t.records]

    def _actual_hourly(self, start_iso, stop_iso):
        records = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start_iso}, stop: {stop_iso})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.ELECTRICITY_DEVICE}"
         and r._field == "Active Three-phase Power")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
''')
        out = {}
        for r in records:
            t = r.get_time()
            if t is None:
                continue
            h_utc = t.hour
            h_pkt = (h_utc + 5) % 24
            out[h_utc] = {
                'hour_utc': h_utc,
                'hour_pkt': h_pkt,
                'label':    f"{h_pkt:02d}:00",
                'actual_kw': round((r.get_value() or 0) / 1000, 2),
            }
        return out

    def _actual_day_stats(self, start_iso, stop_iso):
        el_r = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start_iso}, stop: {stop_iso})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.ELECTRICITY_DEVICE}"
         and r._field == "Active Three-phase Power")
  |> reduce(
       fn: (r, accumulator) => ({{
         sum: accumulator.sum + r._value,
         count: accumulator.count + 1.0,
         max: if r._value > accumulator.max then r._value else accumulator.max
       }}),
       identity: {{sum: 0.0, count: 0.0, max: 0.0}}
     )
''')
        flow_hi = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start_iso}, stop: {stop_iso})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.FLOW_DEVICE}"
         and r._field == "Total Amount of Flow")
  |> max()
''')
        flow_lo = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start_iso}, stop: {stop_iso})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.FLOW_DEVICE}"
         and r._field == "Total Amount of Flow")
  |> min()
''')
        has_data = False
        mean_kw = peak_kw = total_kwh = 0.0
        if el_r:
            v = el_r[0].values
            c = v.get('count', 0)
            if c > 0:
                mean_w   = v['sum'] / c
                peak_w   = v['max']
                mean_kw  = round(mean_w / 1000, 2)
                peak_kw  = round(peak_w / 1000, 2)
                total_kwh = round(mean_w * 24 / 1000, 1)
                has_data = True

        flow_vol = 0
        if flow_hi and flow_lo:
            flow_vol = max(0, (flow_hi[0].get_value() or 0) - (flow_lo[0].get_value() or 0))

        return {
            'has_data':    has_data,
            'mean_kw':     mean_kw,
            'peak_kw':     peak_kw,
            'total_kwh':   total_kwh,
            'flow_volume': round(flow_vol, 0),
        }

    @staticmethod
    def _pct_error(forecast, actual):
        if actual and actual > 0:
            return round((forecast - actual) / actual * 100, 1)
        return None

    @staticmethod
    def _mae(pairs):
        valid = [(f, a) for f, a in pairs if a is not None and a > 0]
        if not valid:
            return None
        return round(sum(abs(f - a) for f, a in valid) / len(valid), 2)

    def get(self, request):
        import traceback as tb
        try:
            from datetime import date as dt_date
            from analytics.models import ForecastRecord

            date_str = request.query_params.get('date')
            if not date_str:
                rec = ForecastRecord.objects.filter(
                    forecast_date__lt=dt_date.today()
                ).first()
                if not rec:
                    return Response({'error': 'No past forecasts found'}, status=404)
            else:
                try:
                    target_date = dt_date.fromisoformat(date_str)
                except ValueError:
                    return Response({'error': 'date must be YYYY-MM-DD'}, status=400)
                try:
                    rec = ForecastRecord.objects.get(forecast_date=target_date)
                except ForecastRecord.DoesNotExist:
                    return Response({'error': f'No forecast saved for {date_str}'}, status=404)

            forecast_date = rec.forecast_date
            start_iso = forecast_date.strftime('%Y-%m-%dT00:00:00Z')
            stop_iso  = forecast_date.strftime('%Y-%m-%dT23:59:59Z')

            actual_hourly_map = self._actual_hourly(start_iso, stop_iso)
            actual_stats      = self._actual_day_stats(start_iso, stop_iso)

            stored_hourly = rec.forecast_json.get('hourly', [])
            merged_hourly = []
            for h in stored_hourly:
                h_utc = h['hour_utc']
                actual = actual_hourly_map.get(h_utc)
                actual_kw = actual['actual_kw'] if actual else None
                merged_hourly.append({
                    'hour_utc':    h_utc,
                    'label':       h['label'],
                    'ref_kw':      h.get('ref_kw'),
                    'forecast_kw': h.get('projected_kw'),
                    'actual_kw':   actual_kw,
                    'error_kw':    round(h.get('projected_kw', 0) - (actual_kw or 0), 2) if actual_kw is not None else None,
                    'error_pct':   self._pct_error(h.get('projected_kw', 0), actual_kw),
                })

            stored_forecast = rec.forecast_json.get('forecast', {})
            mae = self._mae([
                (h['forecast_kw'], h['actual_kw'])
                for h in merged_hourly
                if h['forecast_kw'] is not None
            ])
            total_kwh_error_pct = self._pct_error(
                stored_forecast.get('total_kwh', 0),
                actual_stats['total_kwh']
            )
            peak_error_pct = self._pct_error(
                stored_forecast.get('peak_kw', 0),
                actual_stats['peak_kw']
            )

            accuracy_status = 'good'
            if total_kwh_error_pct is not None and abs(total_kwh_error_pct) > 10:
                accuracy_status = 'warning'
            if total_kwh_error_pct is not None and abs(total_kwh_error_pct) > 20:
                accuracy_status = 'critical'

            return Response({
                'forecast_date':   forecast_date.isoformat(),
                'forecast_label':  forecast_date.strftime('%A, %d %b %Y'),
                'saved_at':        rec.saved_at.isoformat(),
                'has_actual_data': actual_stats['has_data'],

                'forecast_summary':  stored_forecast,
                'actual_summary':    actual_stats,
                'targets':           rec.forecast_json.get('targets', {}),
                'weather':           rec.forecast_json.get('weather', {}),
                'temperature_model': rec.forecast_json.get('temperature_model', {}),

                'accuracy': {
                    'total_kwh_forecast':  stored_forecast.get('total_kwh'),
                    'total_kwh_actual':    actual_stats['total_kwh'],
                    'total_kwh_error_pct': total_kwh_error_pct,
                    'peak_kw_forecast':    stored_forecast.get('peak_kw'),
                    'peak_kw_actual':      actual_stats['peak_kw'],
                    'peak_error_pct':      peak_error_pct,
                    'hourly_mae_kw':       mae,
                    'status':              accuracy_status,
                },

                'hourly': merged_hourly,
            })

        except Exception as e:
            return Response({'error': str(e), 'traceback': tb.format_exc()}, status=500)


class ForecastView(APIView):
    """
    Produces a next-working-day forecast vs the same weekday last week,
    incorporating a live Lahore temperature uplift from wttr.in.
    All times stored as UTC; PKT = UTC+5 is computed for display labels.
    """

    INFLUX_URL    = 'http://localhost:8086'
    INFLUX_TOKEN  = 'PQF2DMjfNtn__ooeubqDTUaiXegywYbzUBNyTjpvd7qoUrmq9PpGVyS8lybnmf-sszI7V1HEwZWdSvgkEGfzcQ=='
    INFLUX_ORG    = 'DATABRIDGE'
    INFLUX_BUCKET = 'databridge'
    INFLUX_MEAS_FILTER = '(r._measurement == "energy_measurements" or r._measurement == "energy_measurements_1m")'
    ELECTRICITY_DEVICE = 'Ombre Apparel LT-1 Main'
    FLOW_DEVICE        = 'Ombre Apparel Flow meter'

    # Cooling sensitivity model
    COOLING_FRACTION  = 0.28   # 28 % of facility load is cooling
    COOLING_SENS_PCT  = 0.04   # +4 % on cooling per °C above 30 °C baseline
    TEMP_BASELINE_C   = 30.0

    def _query_api(self):
        from influxdb_client import InfluxDBClient
        return InfluxDBClient(url=self.INFLUX_URL, token=self.INFLUX_TOKEN,
                              org=self.INFLUX_ORG).query_api()

    def _flux(self, q):
        return [r for t in self._query_api().query(q) for r in t.records]

    # ── Weather ──────────────────────────────────────────────────────────────

    def _get_weather(self):
        """Fetch Lahore forecast from wttr.in (no API key needed). Falls back gracefully."""
        import urllib.request, json as _json
        try:
            url = 'https://wttr.in/Lahore?format=j1'
            req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'})
            with urllib.request.urlopen(req, timeout=5) as r:
                d = _json.loads(r.read())
            today_w    = d['weather'][0]
            tomorrow_w = d['weather'][1]
            return {
                'today_max_c':    int(today_w['maxtempC']),
                'today_min_c':    int(today_w['mintempC']),
                'tomorrow_max_c': int(tomorrow_w['maxtempC']),
                'tomorrow_min_c': int(tomorrow_w['mintempC']),
                'tomorrow_desc':  tomorrow_w['hourly'][4]['weatherDesc'][0]['value'],
                'source': 'wttr.in',
            }
        except Exception:
            return {
                'today_max_c': 33, 'today_min_c': 19,
                'tomorrow_max_c': 38, 'tomorrow_min_c': 24,
                'tomorrow_desc': 'Hot & sunny (forecast unavailable)',
                'source': 'fallback',
            }

    # ── Hourly profiles ──────────────────────────────────────────────────────

    def _hourly_power(self, start_iso, stop_iso):
        """Return list[{hour_utc, hour_pkt, label_pkt, power_kw}] for a full day."""
        records = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start_iso}, stop: {stop_iso})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.ELECTRICITY_DEVICE}"
         and r._field == "Active Three-phase Power")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: true)
''')
        out = []
        for r in records:
            t = r.get_time()
            if t is None:
                continue
            h_utc = t.hour
            h_pkt = (h_utc + 5) % 24
            out.append({
                'hour_utc': h_utc,
                'hour_pkt': h_pkt,
                'label':    f"{h_pkt:02d}:00",
                'power_kw': round((r.get_value() or 0) / 1000, 2),
            })
        return sorted(out, key=lambda x: x['hour_utc'])

    def _hourly_flow(self, start_iso, stop_iso):
        records = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start_iso}, stop: {stop_iso})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.FLOW_DEVICE}"
         and r._field == "Instantaneous Flow")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: true)
''')
        out = []
        for r in records:
            t = r.get_time()
            if t is None:
                continue
            h_utc = t.hour
            h_pkt = (h_utc + 5) % 24
            out.append({
                'hour_utc': h_utc,
                'hour_pkt': h_pkt,
                'label':    f"{h_pkt:02d}:00",
                'flow':     round(r.get_value() or 0, 2),
            })
        return sorted(out, key=lambda x: x['hour_utc'])

    def _day_stats(self, start_iso, stop_iso):
        """Mean, peak, total kWh, phase currents, implied PF."""
        # Electricity
        el_r = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start_iso}, stop: {stop_iso})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.ELECTRICITY_DEVICE}"
         and r._field == "Active Three-phase Power")
  |> reduce(
       fn: (r, accumulator) => ({{
         sum: accumulator.sum + r._value,
         count: accumulator.count + 1.0,
         max: if r._value > accumulator.max then r._value else accumulator.max
       }}),
       identity: {{sum: 0.0, count: 0.0, max: 0.0}}
     )
''')
        ap_r = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start_iso}, stop: {stop_iso})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.ELECTRICITY_DEVICE}"
         and r._field == "Apparent Three-phase Power")
  |> mean()
''')
        curr_r = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start_iso}, stop: {stop_iso})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.ELECTRICITY_DEVICE}"
         and (r._field == "L1 Current" or r._field == "L2 Current" or r._field == "L3 Current"))
  |> filter(fn: (r) => r._value > 5)
  |> group(columns: ["_field"])
  |> mean()
''')
        # Flow delta
        flow_hi = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start_iso}, stop: {stop_iso})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.FLOW_DEVICE}"
         and r._field == "Total Amount of Flow")
  |> max()
''')
        flow_lo = self._flux(f'''
from(bucket: "{self.INFLUX_BUCKET}")
  |> range(start: {start_iso}, stop: {stop_iso})
  |> filter(fn: (r) => {self.INFLUX_MEAS_FILTER}
         and r.device_id == "{self.FLOW_DEVICE}"
         and r._field == "Total Amount of Flow")
  |> min()
''')

        mean_w = peak_w = 0.0
        has_data = False
        if el_r:
            v = el_r[0].values
            c = v.get('count', 0)
            if c > 0:
                mean_w   = v['sum'] / c
                peak_w   = v['max']
                has_data = True

        apparent_w = (ap_r[0].get_value() or 0) if ap_r else 0
        pf = round(mean_w / apparent_w, 3) if apparent_w > 0 else None

        currents = {r.get_field(): round(r.get_value() or 0, 1) for r in curr_r}
        l1, l2, l3 = (currents.get('L1 Current', 0),
                      currents.get('L2 Current', 0),
                      currents.get('L3 Current', 0))
        avg_i = (l1 + l2 + l3) / 3 if any([l1, l2, l3]) else 0
        imb   = round(abs(min(l1, l2, l3) - avg_i) / avg_i * 100, 1) if avg_i > 0 else 0

        flow_vol = 0
        if flow_hi and flow_lo:
            flow_vol = max(0, (flow_hi[0].get_value() or 0) - (flow_lo[0].get_value() or 0))

        # 24h energy from mean
        total_kwh = round(mean_w * 24 / 1000, 1)

        return {
            'has_data':    has_data,
            'mean_kw':     round(mean_w / 1000, 2),
            'peak_kw':     round(peak_w / 1000, 2),
            'total_kwh':   total_kwh,
            'apparent_kva': round(apparent_w / 1000, 2),
            'power_factor': pf,
            'l1_a': l1, 'l2_a': l2, 'l3_a': l3,
            'phase_imbalance_pct': imb,
            'flow_volume': round(flow_vol, 0),
        }

    # ── Multi-week reference averaging ──────────────────────────────────────

    def _hourly_power_multi(self, date_ranges):
        """
        Average hourly electricity profiles across multiple reference days.
        Skips any day whose total working-hour load is < 50 kW (holiday/closed).
        """
        from collections import defaultdict
        buckets = defaultdict(list)
        hour_meta = {}

        for start_iso, stop_iso in date_ranges:
            day_data = self._hourly_power(start_iso, stop_iso)
            working_total = sum(h['power_kw'] for h in day_data
                                if 4 <= h['hour_pkt'] <= 22)
            if working_total < 50:
                continue
            for h in day_data:
                utc = h['hour_utc']
                hour_meta[utc] = {'hour_pkt': h['hour_pkt'], 'label': h['label']}
                if h['power_kw'] > 0.1:
                    buckets[utc].append(h['power_kw'])

        if not hour_meta:
            return self._hourly_power(date_ranges[0][0], date_ranges[0][1])

        out = []
        for utc in sorted(hour_meta.keys()):
            vals = buckets.get(utc, [])
            avg_kw = round(sum(vals) / len(vals), 2) if vals else 0.0
            out.append({
                'hour_utc': utc,
                'hour_pkt': hour_meta[utc]['hour_pkt'],
                'label':    hour_meta[utc]['label'],
                'power_kw': avg_kw,
            })
        return out

    def _hourly_flow_multi(self, date_ranges):
        """Average hourly flow profiles across multiple reference days."""
        from collections import defaultdict
        buckets = defaultdict(list)
        hour_meta = {}

        for start_iso, stop_iso in date_ranges:
            day_data = self._hourly_flow(start_iso, stop_iso)
            if sum(h['flow'] for h in day_data) < 10:
                continue
            for h in day_data:
                utc = h['hour_utc']
                hour_meta[utc] = {'hour_pkt': h['hour_pkt'], 'label': h['label']}
                if h['flow'] > 0.01:
                    buckets[utc].append(h['flow'])

        if not hour_meta:
            return self._hourly_flow(date_ranges[0][0], date_ranges[0][1])

        out = []
        for utc in sorted(hour_meta.keys()):
            vals = buckets.get(utc, [])
            out.append({
                'hour_utc': utc,
                'hour_pkt': hour_meta[utc]['hour_pkt'],
                'label':    hour_meta[utc]['label'],
                'flow':     round(sum(vals) / len(vals), 2) if vals else 0.0,
            })
        return out

    def _day_stats_multi(self, date_ranges):
        """Average day-level stats across multiple valid reference days."""
        stats_list = [self._day_stats(s, e) for s, e in date_ranges]
        valid = [s for s in stats_list if s.get('has_data') and s['mean_kw'] > 5]
        if not valid:
            return stats_list[0]

        def _avg(key):
            vals = [s[key] for s in valid if s.get(key) is not None]
            return round(sum(vals) / len(vals), 2) if vals else 0

        return {
            'has_data':            True,
            'mean_kw':             _avg('mean_kw'),
            'peak_kw':             _avg('peak_kw'),
            'total_kwh':           _avg('total_kwh'),
            'apparent_kva':        _avg('apparent_kva'),
            'power_factor':        valid[0]['power_factor'],   # use most-recent week
            'l1_a':                _avg('l1_a'),
            'l2_a':                _avg('l2_a'),
            'l3_a':                _avg('l3_a'),
            'phase_imbalance_pct': _avg('phase_imbalance_pct'),
            'flow_volume':         _avg('flow_volume'),
        }

    # ── Projection ───────────────────────────────────────────────────────────

    def _project_hourly(self, ref_hourly, uplift_frac):
        """Apply temperature uplift to reference hourly profile."""
        out = []
        for h in ref_hourly:
            base = h['power_kw']
            proj = round(base * (1 + uplift_frac), 2) if base > 0.5 else base
            out.append({**h, 'projected_kw': proj})
        return out

    # ── Main handler ─────────────────────────────────────────────────────────

    def get(self, request):
        import traceback
        try:
            from datetime import datetime, timezone, timedelta

            now = datetime.now(timezone.utc)
            wd  = now.weekday()   # 0=Mon … 6=Sun

            # Forecast day: next working day
            if wd == 6:   # Sunday → Monday
                days_ahead = 1
            elif wd == 5: # Saturday → Monday
                days_ahead = 2
            else:         # Mon-Fri → tomorrow
                days_ahead = 1

            # Reference profile: average of last N weeks, same weekday
            N_REF_WEEKS   = 3
            forecast_date = (now + timedelta(days=days_ahead)).replace(
                hour=0, minute=0, second=0, microsecond=0)
            ref_dates     = [forecast_date - timedelta(weeks=w) for w in range(1, N_REF_WEEKS + 1)]
            date_ranges   = [
                (d.strftime('%Y-%m-%dT00:00:00Z'), d.strftime('%Y-%m-%dT23:59:59Z'))
                for d in ref_dates
            ]
            # Primary ref_date (1 week ago) used for display & storage
            ref_date = ref_dates[0]

            # Weather
            weather = self._get_weather()
            # Ref-day seasonal baseline: estimate from recent trend
            # (we don't store historical weather, so we use today's temp minus
            #  a 3-week-averaged weekly rise of ~2 °C/week as a proxy)
            ref_temp_max   = max(28, weather['today_max_c'] - 6)   # ~2 °C/week × 3 weeks back
            fcast_temp_max = weather['tomorrow_max_c']

            # Temperature uplift calculation
            ref_above_base   = max(0, ref_temp_max   - self.TEMP_BASELINE_C)
            fcast_above_base = max(0, fcast_temp_max - self.TEMP_BASELINE_C)
            ref_uplift   = self.COOLING_FRACTION * self.COOLING_SENS_PCT * ref_above_base
            fcast_uplift = self.COOLING_FRACTION * self.COOLING_SENS_PCT * fcast_above_base
            net_uplift   = fcast_uplift - ref_uplift   # incremental vs reference baseline

            # Multi-week averaged reference profiles
            ref_hourly_elec = self._hourly_power_multi(date_ranges)
            ref_hourly_flow = self._hourly_flow_multi(date_ranges)
            ref_stats       = self._day_stats_multi(date_ranges)

            # Projected hourly
            proj_hourly = self._project_hourly(ref_hourly_elec, net_uplift)

            # Projected day totals
            proj_total_kwh  = round(ref_stats['total_kwh'] * (1 + net_uplift), 1)
            proj_peak_kw    = round(ref_stats['peak_kw']   * (1 + net_uplift), 2)
            proj_mean_kw    = round(ref_stats['mean_kw']   * (1 + net_uplift), 2)
            proj_flow       = round(ref_stats['flow_volume'] * 1.03, 0)  # +3% for boiler losses

            # Suggested targets (stretch goal = 2 % below projection)
            target_kwh    = round(proj_total_kwh  * 0.98, 0)
            target_peak   = round(proj_peak_kw    * 0.97, 1)
            target_flow   = round(proj_flow       * 1.05, 0)   # allow 5 % headroom

            # Phase imbalance status
            imb = ref_stats['phase_imbalance_pct']
            imb_status = 'good' if imb < 5 else ('warning' if imb < 15 else 'critical')

            # Build hourly table for frontend (merge ref + projected)
            hourly_table = []
            flow_by_hour = {h['hour_utc']: h['flow'] for h in ref_hourly_flow}
            for h in proj_hourly:
                hourly_table.append({
                    'hour_utc':       h['hour_utc'],
                    'label':          h['label'],
                    'ref_kw':         h['power_kw'],
                    'projected_kw':   h['projected_kw'],
                    'flow_ref':       flow_by_hour.get(h['hour_utc'], 0),
                })

            return Response({
                'generated_at':   now.isoformat(),
                'forecast_date':  forecast_date.strftime('%Y-%m-%d'),
                'forecast_label': forecast_date.strftime('%A, %d %b %Y'),
                'ref_date':       ref_date.strftime('%Y-%m-%d'),
                'ref_label':      ref_date.strftime('%A, %d %b %Y'),
                'ref_weeks':      N_REF_WEEKS,
                'ref_dates':      [d.strftime('%Y-%m-%d') for d in ref_dates],

                'weather': {
                    **weather,
                    'ref_max_c':  ref_temp_max,
                    'delta_c':    fcast_temp_max - ref_temp_max,
                },

                'temperature_model': {
                    'cooling_fraction_pct':  round(self.COOLING_FRACTION * 100),
                    'sensitivity_pct_per_c': round(self.COOLING_SENS_PCT * 100),
                    'ref_uplift_pct':        round(ref_uplift   * 100, 1),
                    'forecast_uplift_pct':   round(fcast_uplift * 100, 1),
                    'net_uplift_pct':        round(net_uplift   * 100, 1),
                },

                'reference_day': {
                    **ref_stats,
                    'date': ref_date.strftime('%Y-%m-%d'),
                },

                'forecast': {
                    'total_kwh':  proj_total_kwh,
                    'peak_kw':    proj_peak_kw,
                    'mean_kw':    proj_mean_kw,
                    'flow_volume': proj_flow,
                },

                'targets': {
                    'energy_kwh':   target_kwh,
                    'peak_kw':      target_peak,
                    'flow_volume':  target_flow,
                    'power_factor': 0.90,
                    'phase_imbalance_pct': 10.0,
                },

                'phase_balance': {
                    'l1_a': ref_stats['l1_a'],
                    'l2_a': ref_stats['l2_a'],
                    'l3_a': ref_stats['l3_a'],
                    'imbalance_pct': imb,
                    'status': imb_status,
                },

                'hourly': hourly_table,
            })

        except Exception as e:
            import traceback
            return Response({'error': str(e), 'traceback': traceback.format_exc()}, status=500)
