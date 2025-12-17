"""
Management command to aggregate daily aggregates into monthly aggregates.
This creates MonthlyAggregate records from existing DailyAggregate data.
"""
from django.core.management.base import BaseCommand
from django.db.models import Sum, Avg, Max, Min, Count
from django.utils import timezone
from datetime import datetime, date
from reporting.models import DailyAggregate, MonthlyAggregate
from modbus.models import ModbusDevice


class Command(BaseCommand):
    help = 'Aggregate daily aggregates into monthly aggregates'

    def add_arguments(self, parser):
        parser.add_argument(
            '--month',
            type=str,
            help='Month to aggregate (YYYY-MM format). If not provided, aggregates all months with daily data.'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Aggregate all months with daily data'
        )

    def handle(self, *args, **options):
        if options['month']:
            # Aggregate specific month
            try:
                month_date = datetime.strptime(options['month'], '%Y-%m').date().replace(day=1)
                self.aggregate_month(month_date)
            except ValueError:
                self.stdout.write(self.style.ERROR(f'Invalid month format: {options["month"]}. Use YYYY-MM'))
        else:
            # Aggregate all months
            self.stdout.write('Aggregating all months from daily data...')
            
            # Get all unique month dates from daily aggregates
            daily_dates = DailyAggregate.objects.values_list('date', flat=True).distinct()
            months = set()
            for d in daily_dates:
                months.add(date(d.year, d.month, 1))
            
            months = sorted(months)
            self.stdout.write(f'Found {len(months)} months to aggregate')
            
            for month_date in months:
                self.aggregate_month(month_date)
            
            self.stdout.write(self.style.SUCCESS(f'Successfully aggregated {len(months)} months'))

    def aggregate_month(self, month_date: date):
        """Aggregate all daily data for a specific month into monthly aggregates."""
        from datetime import timedelta
        
        month_start = month_date
        if month_date.day != 1:
            month_start = month_date.replace(day=1)
        
        # Calculate month end
        if month_start.month == 12:
            month_end = date(month_start.year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)
        
        # Get all daily aggregates for this month
        daily_aggs = DailyAggregate.objects.filter(
            date__gte=month_start,
            date__lte=month_end,
            is_overtime=False  # Only aggregate regular hours, not overtime
        )
        
        if not daily_aggs.exists():
            self.stdout.write(self.style.WARNING(f'  No daily data found for {month_start.strftime("%Y-%m")}'))
            return
        
        # Group by device
        devices = daily_aggs.values_list('device', flat=True).distinct()
        
        created_count = 0
        updated_count = 0
        
        for device_id in devices:
            if device_id is None:
                continue
            
            device_dailies = daily_aggs.filter(device_id=device_id)
            
            # Calculate aggregates
            total_energy = sum(agg.total_energy_kwh for agg in device_dailies)
            avg_daily_energy = total_energy / device_dailies.count() if device_dailies.exists() else 0
            peak_power = max((agg.peak_power_kw for agg in device_dailies), default=0)
            
            # Aggregate component breakdown
            component_breakdown = {}
            for agg in device_dailies:
                if agg.component_breakdown:
                    for component, value in agg.component_breakdown.items():
                        component_breakdown[component] = component_breakdown.get(component, 0) + value
            
            # Get production data if available
            total_units = sum((agg.units_produced for agg in device_dailies if agg.units_produced), start=0)
            efficiency = (total_energy / total_units) if total_units > 0 else None
            
            # Calculate cost
            total_cost = sum(agg.total_cost for agg in device_dailies)
            
            # Calculate data completeness
            expected_days = (month_end - month_start).days + 1
            actual_days = device_dailies.count()
            data_completeness = (actual_days / expected_days * 100) if expected_days > 0 else 100
            
            try:
                device = ModbusDevice.objects.get(id=device_id)
            except ModbusDevice.DoesNotExist:
                continue
            
            monthly_agg, created = MonthlyAggregate.objects.get_or_create(
                device=device,
                month=month_start,
                defaults={
                    'total_energy_kwh': total_energy,
                    'avg_daily_energy_kwh': avg_daily_energy,
                    'peak_power_kw': peak_power,
                    'component_breakdown': component_breakdown,
                    'total_units_produced': total_units if total_units > 0 else None,
                    'efficiency_kwh_per_unit': efficiency,
                    'total_cost': total_cost,
                    'tariff_rate': 0.15,  # Default
                    'data_completeness': data_completeness,
                }
            )
            
            if created:
                created_count += 1
            else:
                # Update existing
                monthly_agg.total_energy_kwh = total_energy
                monthly_agg.avg_daily_energy_kwh = avg_daily_energy
                monthly_agg.peak_power_kw = peak_power
                monthly_agg.component_breakdown = component_breakdown
                monthly_agg.total_units_produced = total_units if total_units > 0 else None
                monthly_agg.efficiency_kwh_per_unit = efficiency
                monthly_agg.total_cost = total_cost
                monthly_agg.data_completeness = data_completeness
                monthly_agg.save()
                updated_count += 1
        
        self.stdout.write(
            f'  {month_start.strftime("%Y-%m")}: Created {created_count}, Updated {updated_count} monthly aggregates'
        )

