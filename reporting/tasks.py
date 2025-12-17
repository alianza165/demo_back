"""
Celery tasks for reporting app.
Coordinates with downsampling to ensure data is available.
"""
import logging
from datetime import datetime, timedelta
from celery import shared_task
from django.utils import timezone

from .services.aggregation_service import ReportingAggregationService
from .services.benchmark_service import BenchmarkCalculationService
from .services.target_service import TargetTrackingService

logger = logging.getLogger(__name__)


@shared_task(name='reporting.tasks.aggregate_daily_data')
def aggregate_daily_data(target_date_str: str = None, device_id: int = None):
    """
    Aggregate daily data for yesterday (or specified date).
    
    This task should run after downsampling to ensure data is available.
    Recommended schedule: Daily at 1 AM (gives downsampling time to complete).
    """
    try:
        service = ReportingAggregationService()
        
        if target_date_str:
            from datetime import datetime
            target_date = datetime.fromisoformat(target_date_str).date()
        else:
            # Default to yesterday
            target_date = (timezone.now() - timedelta(days=1)).date()
        
        device = None
        if device_id:
            from modbus.models import ModbusDevice
            try:
                device = ModbusDevice.objects.get(id=device_id)
            except ModbusDevice.DoesNotExist:
                logger.warning(f"Device {device_id} not found")
        
        aggregates = service.aggregate_daily_data(target_date=target_date, device=device)
        
        logger.info(f"Daily aggregation completed: {len(aggregates)} aggregates created/updated for {target_date}")
        return f"Processed {len(aggregates)} daily aggregates"
        
    except Exception as e:
        logger.error(f"Error in aggregate_daily_data task: {e}", exc_info=True)
        raise


@shared_task(name='reporting.tasks.aggregate_monthly_data')
def aggregate_monthly_data(target_month_str: str = None, device_id: int = None):
    """
    Aggregate monthly data for last month (or specified month).
    
    Recommended schedule: 1st of month at 2 AM.
    """
    try:
        service = ReportingAggregationService()
        
        if target_month_str:
            from datetime import datetime
            target_month = datetime.fromisoformat(target_month_str).date().replace(day=1)
        else:
            # Default to last month
            today = timezone.now().date()
            target_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        
        device = None
        if device_id:
            from modbus.models import ModbusDevice
            try:
                device = ModbusDevice.objects.get(id=device_id)
            except ModbusDevice.DoesNotExist:
                logger.warning(f"Device {device_id} not found")
        
        aggregates = service.aggregate_monthly_data(target_month=target_month, device=device)
        
        logger.info(f"Monthly aggregation completed: {len(aggregates)} aggregates created/updated for {target_month}")
        return f"Processed {len(aggregates)} monthly aggregates"
        
    except Exception as e:
        logger.error(f"Error in aggregate_monthly_data task: {e}", exc_info=True)
        raise


@shared_task(name='reporting.tasks.calculate_benchmarks')
def calculate_benchmarks(days_back: int = 90, device_id: int = None):
    """
    Calculate efficiency benchmarks from historical data.
    
    Recommended schedule: Weekly (e.g., Sunday at 3 AM).
    """
    try:
        service = BenchmarkCalculationService()
        
        devices = None
        if device_id:
            from modbus.models import ModbusDevice
            try:
                devices = [ModbusDevice.objects.get(id=device_id)]
            except ModbusDevice.DoesNotExist:
                logger.warning(f"Device {device_id} not found")
        
        benchmarks = service.calculate_all_benchmarks(devices=devices, days_back=days_back)
        
        logger.info(f"Benchmark calculation completed: {len(benchmarks)} benchmarks created/updated")
        return f"Processed {len(benchmarks)} benchmarks"
        
    except Exception as e:
        logger.error(f"Error in calculate_benchmarks task: {e}", exc_info=True)
        raise


@shared_task(name='reporting.tasks.update_target_progress')
def update_target_progress(target_id: int = None):
    """
    Update progress for targets and calculate on-track status.
    
    Recommended schedule: Daily at 4 AM (after daily aggregation).
    """
    try:
        service = TargetTrackingService()
        
        target = None
        if target_id:
            try:
                target = Target.objects.get(id=target_id)
            except Target.DoesNotExist:
                logger.warning(f"Target {target_id} not found")
        
        updated_targets = service.update_target_progress(target=target)
        
        logger.info(f"Target progress update completed: {len(updated_targets)} targets updated")
        return f"Updated {len(updated_targets)} targets"
        
    except Exception as e:
        logger.error(f"Error in update_target_progress task: {e}", exc_info=True)
        raise


@shared_task(name='reporting.tasks.backfill_daily_aggregates')
def backfill_daily_aggregates(days_back: int = 30, device_id: int = None):
    """
    Backfill daily aggregates for past days.
    Useful for initial setup or catching up after downtime.
    """
    try:
        service = ReportingAggregationService()
        
        device = None
        if device_id:
            from modbus.models import ModbusDevice
            try:
                device = ModbusDevice.objects.get(id=device_id)
            except ModbusDevice.DoesNotExist:
                logger.warning(f"Device {device_id} not found")
        
        today = timezone.now().date()
        aggregates_created = 0
        
        for i in range(1, days_back + 1):
            target_date = today - timedelta(days=i)
            aggregates = service.aggregate_daily_data(target_date=target_date, device=device)
            aggregates_created += len(aggregates)
        
        logger.info(f"Backfill completed: {aggregates_created} daily aggregates created/updated")
        return f"Backfilled {aggregates_created} daily aggregates"
        
    except Exception as e:
        logger.error(f"Error in backfill_daily_aggregates task: {e}", exc_info=True)
        raise


# Import Target here to avoid circular imports
from .models import Target





