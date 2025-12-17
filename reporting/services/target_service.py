"""
Target tracking service.
Tracks progress towards targets and determines if on track.
"""
import logging
from datetime import datetime, timedelta, date
from typing import Optional, List
from django.utils import timezone
from django.db import transaction
from django.db.models import Avg

from ..models import Target, DailyAggregate, MonthlyAggregate

logger = logging.getLogger(__name__)


class TargetTrackingService:
    """Service to track target progress and calculate on-track status."""
    
    def update_target_progress(self, target: Optional[Target] = None) -> List[Target]:
        """
        Update progress for a target or all active targets.
        Calculates if targets are on track based on daily trends.
        """
        if target:
            targets = [target]
        else:
            targets = Target.objects.filter(
                period_start__lte=timezone.now().date(),
                period_end__gte=timezone.now().date()
            )
        
        updated_targets = []
        
        for target in targets:
            try:
                self._update_single_target(target)
                updated_targets.append(target)
            except Exception as e:
                logger.error(f"Error updating target {target.id}: {e}")
        
        return updated_targets
    
    def _update_single_target(self, target: Target):
        """Update progress for a single target."""
        today = timezone.now().date()
        
        # Calculate current value based on period type
        if target.target_period == 'monthly':
            current_value = self._calculate_monthly_progress(target, today)
        elif target.target_period == 'weekly':
            current_value = self._calculate_weekly_progress(target, today)
        else:
            current_value = self._calculate_custom_progress(target, today)
        
        # Determine if on track
        is_on_track = self._calculate_on_track(target, current_value, today)
        
        # Update target
        with transaction.atomic():
            target.current_value = current_value
            target.is_on_track = is_on_track
            target.save()
            
            logger.info(f"Updated target {target.id}: current={current_value:.2f}, on_track={is_on_track}")
    
    def _calculate_monthly_progress(self, target: Target, today: date) -> float:
        """Calculate current progress for monthly target."""
        month_start = target.period_start
        month_end = target.period_end
        
        # Get daily aggregates for the month so far
        daily_aggregates = DailyAggregate.objects.filter(
            date__gte=month_start,
            date__lte=min(today, month_end),
        )
        
        if target.device:
            daily_aggregates = daily_aggregates.filter(device=target.device)
        else:
            # Aggregate across all devices
            pass
        
        # Calculate based on metric
        if 'kwh_per_garment' in target.metric_name or 'kwh_per_unit' in target.metric_name:
            # Efficiency metric - calculate average
            daily_aggregates = daily_aggregates.exclude(efficiency_kwh_per_unit__isnull=True)
            if daily_aggregates.exists():
                result = daily_aggregates.aggregate(avg=Avg('efficiency_kwh_per_unit'))
                return result['avg'] or 0
            return 0
        elif 'total_energy' in target.metric_name or 'kwh' in target.metric_name:
            # Total energy metric
            total = sum(agg.total_energy_kwh for agg in daily_aggregates)
            return total
        else:
            # Default: sum of metric
            return sum(getattr(agg, target.metric_name, 0) or 0 for agg in daily_aggregates)
    
    def _calculate_weekly_progress(self, target: Target, today: date) -> float:
        """Calculate current progress for weekly target."""
        week_start = target.period_start
        week_end = target.period_end
        
        daily_aggregates = DailyAggregate.objects.filter(
            date__gte=week_start,
            date__lte=min(today, week_end),
        )
        
        if target.device:
            daily_aggregates = daily_aggregates.filter(device=target.device)
        
        if 'kwh_per_garment' in target.metric_name or 'kwh_per_unit' in target.metric_name:
            daily_aggregates = daily_aggregates.exclude(efficiency_kwh_per_unit__isnull=True)
            if daily_aggregates.exists():
                result = daily_aggregates.aggregate(avg=Avg('efficiency_kwh_per_unit'))
                return result['avg'] or 0
            return 0
        elif 'total_energy' in target.metric_name:
            return sum(agg.total_energy_kwh for agg in daily_aggregates)
        else:
            return sum(getattr(agg, target.metric_name, 0) or 0 for agg in daily_aggregates)
    
    def _calculate_custom_progress(self, target: Target, today: date) -> float:
        """Calculate progress for custom period."""
        return self._calculate_monthly_progress(target, today)  # Use monthly logic as default
    
    def _calculate_on_track(self, target: Target, current_value: float, today: date) -> bool:
        """
        Determine if target is on track based on:
        1. Current progress vs expected progress
        2. Daily trend analysis
        """
        period_days = (target.period_end - target.period_start).days + 1
        days_elapsed = (min(today, target.period_end) - target.period_start).days + 1
        days_remaining = period_days - days_elapsed
        
        if days_remaining <= 0:
            # Period ended - check if target was met
            if 'kwh_per_garment' in target.metric_name or 'kwh_per_unit' in target.metric_name:
                # Lower is better for efficiency metrics
                return current_value <= target.target_value
            else:
                # Higher is better for total metrics
                return current_value >= target.target_value
        
        # Calculate expected progress
        progress_ratio = days_elapsed / period_days
        
        if 'kwh_per_garment' in target.metric_name or 'kwh_per_unit' in target.metric_name:
            # For efficiency: if current is better than target, we're on track
            # Also check trend: if improving, likely to meet target
            if current_value <= target.target_value:
                return True
            
            # Check trend: get last 7 days of efficiency
            week_ago = today - timedelta(days=7)
            recent_aggregates = DailyAggregate.objects.filter(
                date__gte=week_ago,
                date__lte=today,
            ).exclude(efficiency_kwh_per_unit__isnull=True)
            
            if target.device:
                recent_aggregates = recent_aggregates.filter(device=target.device)
            
            if recent_aggregates.count() >= 3:
                values = sorted([agg.efficiency_kwh_per_unit for agg in recent_aggregates])
                # If trend is improving (decreasing), we might catch up
                trend_improving = values[-1] < values[0]  # Latest is better than oldest
                
                # Projection: if improving, check if we can reach target
                if trend_improving and current_value <= target.target_value * 1.1:  # Within 10%
                    return True
            
            return False
        else:
            # For total metrics: check if we're ahead of schedule
            expected_value = target.target_value * progress_ratio
            
            if current_value >= expected_value:
                return True
            
            # Check trend: if accelerating, might catch up
            week_ago = today - timedelta(days=7)
            recent_aggregates = DailyAggregate.objects.filter(
                date__gte=week_ago,
                date__lte=today,
            )
            
            if target.device:
                recent_aggregates = recent_aggregates.filter(device=target.device)
            
            if recent_aggregates.count() >= 3:
                daily_totals = [agg.total_energy_kwh for agg in recent_aggregates.order_by('date')]
                # Check if daily rate is increasing
                if len(daily_totals) >= 3:
                    recent_avg = sum(daily_totals[-3:]) / 3
                    earlier_avg = sum(daily_totals[:3]) / 3 if len(daily_totals) >= 6 else daily_totals[0]
                    
                    if recent_avg > earlier_avg * 1.1:  # 10% improvement
                        # Project if this rate continues
                        projected_total = current_value + (recent_avg * days_remaining)
                        if projected_total >= target.target_value:
                            return True
            
            return False
    
    def create_target_from_benchmark(
        self,
        benchmark,
        target_period: str = 'monthly',
        period_start: Optional[date] = None
    ) -> Target:
        """Create a target from a benchmark."""
        if period_start is None:
            if target_period == 'monthly':
                period_start = timezone.now().date().replace(day=1)
            elif target_period == 'weekly':
                # Start of current week (Monday)
                today = timezone.now().date()
                days_since_monday = today.weekday()
                period_start = today - timedelta(days=days_since_monday)
            else:
                period_start = timezone.now().date()
        
        # Calculate period end
        if target_period == 'monthly':
            period_end = (period_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        elif target_period == 'weekly':
            period_end = period_start + timedelta(days=6)
        else:
            period_end = period_start + timedelta(days=30)
        
        target, created = Target.objects.get_or_create(
            device=benchmark.device,
            metric_name=benchmark.metric_name,
            target_period=target_period,
            period_start=period_start,
            defaults={
                'target_value': benchmark.benchmark_value,
                'benchmark_used': benchmark,
            }
        )
        
        return target





