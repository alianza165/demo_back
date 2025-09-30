from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum, Avg, Max
from .models import EnergySummary, ShiftEnergyData, ShiftDefinition
from .serializers import (
    EnergySummarySerializer, 
    ShiftEnergyDataSerializer,
    ShiftDefinitionSerializer
)

class EnergySummaryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = EnergySummary.objects.all()
    serializer_class = EnergySummarySerializer
    
    def get_queryset(self):
        queryset = EnergySummary.objects.all()
        
        # Filter by device if provided
        device_id = self.request.query_params.get('device_id')
        if device_id:
            queryset = queryset.filter(device_id=device_id)
            
        # Filter by time range
        days = int(self.request.query_params.get('days', 7))
        start_date = timezone.now() - timedelta(days=days)
        queryset = queryset.filter(timestamp__gte=start_date)
        
        return queryset.order_by('timestamp')
    
    @action(detail=False, methods=['get'])
    def by_device(self, request):
        device_id = request.query_params.get('device_id')
        days = int(request.query_params.get('days', 7))
        
        if not device_id:
            return Response(
                {'error': 'device_id parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        start_date = timezone.now() - timedelta(days=days)
        
        summaries = EnergySummary.objects.filter(
            device_id=device_id,
            timestamp__gte=start_date
        ).order_by('timestamp')
        
        serializer = self.get_serializer(summaries, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def compare_devices(self, request):
        """Compare energy consumption between devices"""
        days = int(request.query_params.get('days', 7))
        start_date = timezone.now() - timedelta(days=days)
        
        # Get energy totals by device
        device_totals = EnergySummary.objects.filter(
            timestamp__gte=start_date,
            interval_type='hourly'
        ).values(
            'device_id', 
            'device__name'
        ).annotate(
            total_energy=Sum('total_energy_kwh'),
            avg_power=Avg('avg_power_kw'),
            max_power=Max('max_power_kw')
        ).order_by('-total_energy')
        
        # Format the response
        result = []
        for item in device_totals:
            result.append({
                'device_id': item['device_id'],
                'device_name': item['device__name'],
                'total_energy': round(item['total_energy'] or 0, 2),
                'total_cost': round((item['total_energy'] or 0) * 0.15, 2),
                'avg_power': round(item['avg_power'] or 0, 2),
                'max_power': round(item['max_power'] or 0, 2),
            })
        
        return Response(result)

class ShiftEnergyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ShiftEnergyData.objects.all()
    serializer_class = ShiftEnergyDataSerializer
    
    def get_queryset(self):
        queryset = ShiftEnergyData.objects.all()
        
        # Filter by time range
        days = int(self.request.query_params.get('days', 30))
        start_date = timezone.now().date() - timedelta(days=days)
        queryset = queryset.filter(shift_date__gte=start_date)
        
        return queryset.order_by('-shift_date', 'shift__name')
    
    @action(detail=False, methods=['get'])
    def efficiency_report(self, request):
        """Get energy efficiency metrics (kWh per unit)"""
        days = int(request.query_params.get('days', 30))
        start_date = timezone.now().date() - timedelta(days=days)
        
        efficient_shifts = ShiftEnergyData.objects.filter(
            shift_date__gte=start_date,
            units_produced__gt=0
        ).order_by('energy_per_unit')
        
        serializer = self.get_serializer(efficient_shifts, many=True)
        return Response(serializer.data)

class ShiftDefinitionViewSet(viewsets.ModelViewSet):
    queryset = ShiftDefinition.objects.all()
    serializer_class = ShiftDefinitionSerializer
