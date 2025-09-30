from django.core.management.base import BaseCommand
from analytics.aggregation_service import DataAggregationService
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Aggregate energy data from InfluxDB to PostgreSQL'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=24,
            help='Number of hours to aggregate back from current time'
        )
        parser.add_argument(
            '--shifts',
            action='store_true',
            help='Calculate shift energy data'
        )
    
    def handle(self, *args, **options):
        try:
            service = DataAggregationService()
            
            self.stdout.write("Starting energy data aggregation...")
            
            # Aggregate hourly data
            self.stdout.write("Aggregating hourly data...")
            service.aggregate_hourly_data(hours_back=options['hours'])
            self.stdout.write(
                self.style.SUCCESS('Successfully aggregated hourly data')
            )
            
            # Calculate shift energy if requested
            if options['shifts']:
                self.stdout.write("Calculating shift energy data...")
                service.calculate_shift_energy()
                self.stdout.write(
                    self.style.SUCCESS('Successfully calculated shift energy data')
                )
                
        except Exception as e:
            logger.error(f"Error in aggregation command: {e}")
            self.stdout.write(
                self.style.ERROR(f'Aggregation failed: {e}')
            )
