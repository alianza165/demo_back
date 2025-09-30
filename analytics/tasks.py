from celery import shared_task
from analytics.aggregation_service import DataAggregationService

@shared_task
def aggregate_hourly_data():
    """Celery task to run hourly aggregation"""
    service = DataAggregationService()
    service.aggregate_hourly_data(hours_back=24)

@shared_task
def calculate_daily_shifts():
    """Celery task to calculate shift data for previous day"""
    from django.utils import timezone
    service = DataAggregationService()
    
    yesterday = timezone.now().date() - timedelta(days=1)
    service.calculate_shift_energy(shift_date=yesterday)

@shared_task
def generate_device_comparisons():
    """Generate device comparisons for the last 24 hours"""
    from django.utils import timezone
    service = DataAggregationService()
    
    end_time = timezone.now()
    start_time = end_time - timedelta(hours=24)
    
    service.compare_devices(start_time, end_time)
