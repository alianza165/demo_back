"""
Benchmark calculation service.
Calculates efficiency benchmarks from historical data.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from django.utils import timezone
from django.db.models import Avg, Min, Q
from django.db import transaction

from ..models import EfficiencyBenchmark, ProductionData, DailyAggregate
from modbus.models import ModbusDevice
# Benchmark service uses pre-aggregated data from DailyAggregate/MonthlyAggregate models
# No direct InfluxDB client needed

logger = logging.getLogger(__name__)


class BenchmarkCalculationService:
    """
    Service to calculate efficiency benchmarks from historical data.
    Supports calculation of best day/week/month, averages, and medians.
    Uses pre-aggregated data from DailyAggregate/MonthlyAggregate models.
    """
    
    def __init__(self):
        pass  # No InfluxDB client needed - uses Django models
    
    def calculate_benchmark(
        self,
        device: Optional[ModbusDevice],
        metric_name: str,
        benchmark_type: str,
        days_back: int = 90,
        force_recalculate: bool = False
    ) -> Optional[EfficiencyBenchmark]:
        """
        Calculate a benchmark for a specific device and metric.
        
        Args:
            device: Device to calculate for (None for overall)
            metric_name: Metric name (e.g., 'kwh_per_garment')
            benchmark_type: Type of benchmark (best_day, best_week, best_month, average, median)
            days_back: Number of days of historical data to use
            force_recalculate: Force recalculation even if benchmark exists
        
        Returns:
            EfficiencyBenchmark instance or None
        """
        # Check if benchmark already exists
        if not force_recalculate:
            benchmark = EfficiencyBenchmark.objects.filter(
                device=device,
                metric_name=metric_name,
                benchmark_type=benchmark_type,
                is_active=True
            ).first()
            
            if benchmark:
                logger.info(f"Benchmark already exists: {benchmark}")
                return benchmark
        
        # Calculate based on type
        if benchmark_type == 'best_day':
            value, period_start, period_end, days_used = self._calculate_best_day(
                device, metric_name, days_back
            )
        elif benchmark_type == 'best_week':
            value, period_start, period_end, days_used = self._calculate_best_week(
                device, metric_name, days_back
            )
        elif benchmark_type == 'best_month':
            value, period_start, period_end, days_used = self._calculate_best_month(
                device, metric_name, days_back
            )
        elif benchmark_type == 'average':
            value, period_start, period_end, days_used = self._calculate_average(
                device, metric_name, days_back
            )
        elif benchmark_type == 'median':
            value, period_start, period_end, days_used = self._calculate_median(
                device, metric_name, days_back
            )
        else:
            logger.error(f"Unknown benchmark type: {benchmark_type}")
            return None
        
        if value is None:
            logger.warning(f"Could not calculate benchmark for {device} - {metric_name} - {benchmark_type}")
            return None
        
        # Create or update benchmark
        with transaction.atomic():
            benchmark, created = EfficiencyBenchmark.objects.update_or_create(
                device=device,
                benchmark_type=benchmark_type,
                metric_name=metric_name,
                defaults={
                    'benchmark_value': value,
                    'period_start': period_start,
                    'period_end': period_end,
                    'calculated_from_days': days_used,
                    'is_active': True,
                }
            )
            
            logger.info(f"{'Created' if created else 'Updated'} benchmark: {benchmark}")
            return benchmark
    
    def _calculate_best_day(
        self,
        device: Optional[ModbusDevice],
        metric_name: str,
        days_back: int
    ) -> tuple:
        """Calculate best day benchmark (lowest kWh/garment)."""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days_back)
        
        # Get daily aggregates with production data
        queryset = DailyAggregate.objects.filter(
            date__gte=start_date,
            date__lte=end_date,
        )
        
        if device:
            queryset = queryset.filter(device=device)
        
        # Filter to records with efficiency data
        queryset = queryset.exclude(efficiency_kwh_per_unit__isnull=True)
        queryset = queryset.filter(efficiency_kwh_per_unit__gt=0)
        
        if not queryset.exists():
            return None, None, None, 0
        
        # Get best (lowest) efficiency day
        best_day = queryset.order_by('efficiency_kwh_per_unit').first()
        
        days_used = queryset.count()
        return (
            best_day.efficiency_kwh_per_unit,
            best_day.date,
            best_day.date,
            days_used
        )
    
    def _calculate_best_week(
        self,
        device: Optional[ModbusDevice],
        metric_name: str,
        days_back: int
    ) -> tuple:
        """Calculate best week benchmark (lowest average kWh/garment)."""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days_back)
        
        # Get daily aggregates
        queryset = DailyAggregate.objects.filter(
            date__gte=start_date,
            date__lte=end_date,
        )
        
        if device:
            queryset = queryset.filter(device=device)
        
        queryset = queryset.exclude(efficiency_kwh_per_unit__isnull=True)
        queryset = queryset.filter(efficiency_kwh_per_unit__gt=0)
        
        if not queryset.exists():
            return None, None, None, 0
        
        # Group by week and calculate averages
        daily_values = list(queryset.values_list('date', 'efficiency_kwh_per_unit'))
        
        # Group into weeks (7-day windows)
        week_averages = []
        for i in range(len(daily_values) - 6):
            week_data = daily_values[i:i+7]
            week_start = week_data[0][0]
            week_end = week_data[-1][0]
            week_avg = sum(val[1] for val in week_data) / len(week_data)
            week_averages.append((week_avg, week_start, week_end))
        
        if not week_averages:
            return None, None, None, 0
        
        # Get best week (lowest average)
        best_week = min(week_averages, key=lambda x: x[0])
        
        days_used = len(daily_values)
        return best_week[0], best_week[1], best_week[2], days_used
    
    def _calculate_best_month(
        self,
        device: Optional[ModbusDevice],
        metric_name: str,
        days_back: int
    ) -> tuple:
        """Calculate best month benchmark."""
        # Use MonthlyAggregate if available, otherwise calculate from daily
        from ..models import MonthlyAggregate
        
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days_back)
        
        queryset = MonthlyAggregate.objects.filter(
            month__gte=start_date.replace(day=1),
            month__lte=end_date.replace(day=1),
        )
        
        if device:
            queryset = queryset.filter(device=device)
        
        queryset = queryset.exclude(efficiency_kwh_per_unit__isnull=True)
        queryset = queryset.filter(efficiency_kwh_per_unit__gt=0)
        
        if not queryset.exists():
            return None, None, None, 0
        
        best_month = queryset.order_by('efficiency_kwh_per_unit').first()
        
        months_used = queryset.count()
        return (
            best_month.efficiency_kwh_per_unit,
            best_month.month,
            best_month.month + timedelta(days=32).replace(day=1) - timedelta(days=1),
            months_used * 30  # Approximate
        )
    
    def _calculate_average(
        self,
        device: Optional[ModbusDevice],
        metric_name: str,
        days_back: int
    ) -> tuple:
        """Calculate average benchmark."""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days_back)
        
        queryset = DailyAggregate.objects.filter(
            date__gte=start_date,
            date__lte=end_date,
        )
        
        if device:
            queryset = queryset.filter(device=device)
        
        queryset = queryset.exclude(efficiency_kwh_per_unit__isnull=True)
        queryset = queryset.filter(efficiency_kwh_per_unit__gt=0)
        
        result = queryset.aggregate(avg=Avg('efficiency_kwh_per_unit'))
        avg_value = result.get('avg')
        
        if avg_value is None:
            return None, None, None, 0
        
        days_used = queryset.count()
        return avg_value, start_date, end_date, days_used
    
    def _calculate_median(
        self,
        device: Optional[ModbusDevice],
        metric_name: str,
        days_back: int
    ) -> tuple:
        """Calculate median benchmark."""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days_back)
        
        queryset = DailyAggregate.objects.filter(
            date__gte=start_date,
            date__lte=end_date,
        )
        
        if device:
            queryset = queryset.filter(device=device)
        
        queryset = queryset.exclude(efficiency_kwh_per_unit__isnull=True)
        queryset = queryset.filter(efficiency_kwh_per_unit__gt=0)
        
        values = list(queryset.values_list('efficiency_kwh_per_unit', flat=True))
        
        if not values:
            return None, None, None, 0
        
        values.sort()
        n = len(values)
        if n % 2 == 0:
            median_value = (values[n//2 - 1] + values[n//2]) / 2
        else:
            median_value = values[n//2]
        
        return median_value, start_date, end_date, len(values)
    
    def calculate_all_benchmarks(
        self,
        devices: Optional[List[ModbusDevice]] = None,
        days_back: int = 90
    ) -> List[EfficiencyBenchmark]:
        """Calculate benchmarks for all active devices."""
        if devices is None:
            devices = list(ModbusDevice.objects.filter(is_active=True))
        
        benchmarks = []
        metric_names = ['kwh_per_garment', 'kwh_per_unit']
        benchmark_types = ['best_day', 'best_week', 'best_month', 'average']
        
        # Overall benchmarks (device=None)
        for metric_name in metric_names:
            for benchmark_type in benchmark_types:
                try:
                    benchmark = self.calculate_benchmark(
                        device=None,
                        metric_name=metric_name,
                        benchmark_type=benchmark_type,
                        days_back=days_back
                    )
                    if benchmark:
                        benchmarks.append(benchmark)
                except Exception as e:
                    logger.error(f"Error calculating overall benchmark {metric_name} {benchmark_type}: {e}")
        
        # Device-specific benchmarks
        for device in devices:
            for metric_name in metric_names:
                for benchmark_type in benchmark_types:
                    try:
                        benchmark = self.calculate_benchmark(
                            device=device,
                            metric_name=metric_name,
                            benchmark_type=benchmark_type,
                            days_back=days_back
                        )
                        if benchmark:
                            benchmarks.append(benchmark)
                    except Exception as e:
                        logger.error(f"Error calculating benchmark for {device.name} {metric_name} {benchmark_type}: {e}")
        
        return benchmarks



