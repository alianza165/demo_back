import math
from datetime import timedelta

import pandas as pd
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Sum, Avg, Max
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import EnergySummary, ShiftEnergyData, ShiftDefinition
from .serializers import (
    EnergySummarySerializer, 
    ShiftEnergyDataSerializer,
    ShiftDefinitionSerializer,
    EnergyAnalyticsQuerySerializer,
)
from .energy_service import (
    EnergyAnalyticsError,
    run_energy_analytics,
    render_csv,
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


def _df_to_records(df: pd.DataFrame, precision: int = 3) -> list[dict]:
    if df.empty:
        return []
    rounded = df.copy()
    numeric_cols = rounded.select_dtypes(include=["float", "int"]).columns
    rounded[numeric_cols] = rounded[numeric_cols].round(precision)
    return (
        rounded.replace({pd.NA: None, math.nan: None})
        .to_dict(orient="records")
    )


class EnergyAnalyticsSummaryView(APIView):
    """
    Returns daily summaries, hourly comparisons, trend data, and performance scores.
    """

    def get(self, request):
        serializer = EnergyAnalyticsQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        devices = serializer.get_devices()
        params = serializer.validated_data

        try:
            result = run_energy_analytics(
                start=params.get("start"),
                end=params.get("end"),
                days=params.get("days", 8),
                devices=devices or None,
                target_kwh=params.get("target_kwh"),
            )
        except EnergyAnalyticsError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        include_hourly = params.get("include_hourly", True)
        include_trend = params.get("include_trend", True)

        response_payload = {
            "analysis_window": {
                "start": result.start.isoformat(),
                "end": result.end.isoformat(),
            },
            "devices": result.device_filter or devices or [],
            "daily_summary": _df_to_records(result.daily_summary),
            "performance_scores": result.performance_scores,
        }

        if include_hourly:
            response_payload["hourly_comparison"] = _df_to_records(result.hourly_comparison)

        if include_trend:
            response_payload["trend"] = _df_to_records(result.trend)
            response_payload["anomalies"] = _df_to_records(result.anomalies)

        # Overall score (average of device scores)
        if result.performance_scores:
            overall = [
                scores.get("overall_score")
                for scores in result.performance_scores.values()
                if scores.get("overall_score") is not None
            ]
            if overall:
                response_payload["overall_score"] = round(sum(overall) / len(overall), 2)

        return Response(response_payload)


class EnergyAnalyticsReportView(APIView):
    """
    Streams a CSV report for the requested analytics window.
    """

    def get(self, request):
        serializer = EnergyAnalyticsQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        devices = serializer.get_devices()
        params = serializer.validated_data
        section = request.query_params.get("section", "all").lower()

        try:
            result = run_energy_analytics(
                start=params.get("start"),
                end=params.get("end"),
                days=params.get("days", 8),
                devices=devices or None,
                target_kwh=params.get("target_kwh"),
            )
        except EnergyAnalyticsError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        frames = {}
        if section in ("hourly", "all"):
            frames["hourly"] = result.hourly
        if section in ("daily", "all"):
            frames["daily"] = result.daily
        if section in ("summary", "all"):
            frames["daily_summary"] = result.daily_summary

        if not frames:
            return Response({"detail": "Invalid section parameter."}, status=status.HTTP_400_BAD_REQUEST)

        csv_content = render_csv(frames)
        filename = f"energy_report_{result.start.date()}_{result.end.date()}.csv"
        response = HttpResponse(csv_content, content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
