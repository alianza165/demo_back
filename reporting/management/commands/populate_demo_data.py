"""
Management command to populate demo data for reporting dashboard.
Creates sample MonthlyAggregate and DailyAggregate records for demonstration.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date, timedelta
from reporting.models import MonthlyAggregate, DailyAggregate, ProductionData
from modbus.models import ModbusDevice
from reporting.services.steam_converter import SteamConverter
import random


class Command(BaseCommand):
    help = 'Populate demo data for reporting dashboard'

    def add_arguments(self, parser):
        parser.add_argument(
            '--months',
            type=int,
            default=6,
            help='Number of months of data to generate (default: 6)'
        )

    def handle(self, *args, **options):
        months_back = options['months']
        
        # Get all active devices
        devices = ModbusDevice.objects.filter(is_active=True)
        if not devices.exists():
            self.stdout.write(self.style.ERROR('No active devices found. Please create devices first.'))
            return
        
        self.stdout.write(f'Generating demo data for {devices.count()} devices...')
        
        # Generate data for last N months
        today = timezone.now().date()
        months_created = 0
        days_created = 0
        
        for month_offset in range(months_back):
            target_month = (today.replace(day=1) - timedelta(days=32 * month_offset)).replace(day=1)
            month_end = (target_month + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            
            for device in devices:
                # Generate monthly aggregate
                monthly_agg, created = MonthlyAggregate.objects.get_or_create(
                    device=device,
                    month=target_month,
                    defaults=self._generate_monthly_data(device, target_month)
                )
                if created:
                    months_created += 1
                
                # Generate daily aggregates for this month
                current_date = target_month
                while current_date <= month_end and current_date <= today:
                    daily_agg, created = DailyAggregate.objects.get_or_create(
                        device=device,
                        date=current_date,
                        defaults=self._generate_daily_data(device, current_date)
                    )
                    if created:
                        days_created += 1
                    current_date += timedelta(days=1)
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully created {months_created} monthly aggregates and {days_created} daily aggregates'
            )
        )

    def _generate_monthly_data(self, device, month):
        """Generate realistic monthly aggregate data."""
        # Base values vary by device type
        if device.device_type == 'flowmeter':
            # Steam flowmeter - volume in m³ (not kWh)
            # Typical steam consumption: 10,000 - 30,000 m³/month
            base_volume_m3 = random.uniform(10000, 30000)  # m³
            base_energy = base_volume_m3  # Store volume as "energy" field (will be converted)
            # Convert to equivalent power (m³/h average)
            base_power = (base_volume_m3 / (30 * 24)) * random.uniform(0.8, 1.2)  # m³/h
        else:
            # Electricity analyzer
            base_energy = random.uniform(50000, 100000)  # kWh
            base_power = random.uniform(1000, 2000)  # kW
        
        # Component breakdown based on device type and department
        component_breakdown = self._generate_component_breakdown(device, base_energy)
        
        # Production data (if applicable)
        total_units = random.randint(100000, 200000) if device.process_area in ['denim', 'washing'] else None
        efficiency = (base_energy / total_units) if total_units else None
        
        return {
            'total_energy_kwh': base_energy,
            'avg_daily_energy_kwh': base_energy / 30,
            'peak_power_kw': base_power,
            'component_breakdown': component_breakdown,
            'total_units_produced': total_units,
            'efficiency_kwh_per_unit': efficiency,
            # Cost calculation based on device type
            'total_cost': (
                SteamConverter.cubic_meters_to_cost_pkr(base_energy) 
                if device.device_type == 'flowmeter' 
                else SteamConverter.kwh_to_cost_pkr(base_energy, is_electricity=True)
            ),
            'tariff_rate': 35.0,  # PKR per kWh for electricity (default, flowmeters don't use this but field is required)
            'data_completeness': random.uniform(95, 100),
        }

    def _generate_daily_data(self, device, target_date):
        """Generate realistic daily aggregate data."""
        # Daily values are monthly / 30 with some variation
        monthly_agg = MonthlyAggregate.objects.filter(
            device=device,
            month=target_date.replace(day=1)
        ).first()
        
        if monthly_agg:
            base_energy = monthly_agg.total_energy_kwh / 30
            # Add daily variation (±20%)
            daily_energy = base_energy * random.uniform(0.8, 1.2)
            component_breakdown = {
                k: v / 30 * random.uniform(0.8, 1.2)
                for k, v in monthly_agg.component_breakdown.items()
            }
            avg_power = daily_energy / 24  # Rough estimate
        else:
            # Fallback if no monthly data
            daily_energy = random.uniform(1500, 4000)
            component_breakdown = self._generate_component_breakdown(device, daily_energy)
            avg_power = daily_energy / 24
        
        # Production (if applicable)
        units_produced = random.randint(3000, 7000) if device.process_area in ['denim', 'washing'] else None
        efficiency = (daily_energy / units_produced) if units_produced else None
        
        return {
            'total_energy_kwh': daily_energy,
            'avg_power_kw': avg_power,
            'peak_power_kw': avg_power * random.uniform(1.2, 1.5),
            'component_breakdown': component_breakdown,
            'units_produced': units_produced,
            'efficiency_kwh_per_unit': efficiency,
            # Cost in PKR
            'total_cost': (
                SteamConverter.cubic_meters_to_cost_pkr(daily_energy)
                if device.device_type == 'flowmeter'
                else SteamConverter.kwh_to_cost_pkr(daily_energy, is_electricity=True)
            ),
        }

    def _generate_component_breakdown(self, device, total_energy):
        """Generate component breakdown based on device type and department."""
        breakdown = {}
        
        # Different allocations based on process_area
        if device.process_area == 'denim':
            breakdown = {
                'machines': total_energy * 0.54,
                'exhaust_fan': total_energy * 0.30,
                'lights': total_energy * 0.05,
                'hvac': total_energy * 0.04,
                'office': total_energy * 0.07,
            }
        elif device.process_area == 'washing':
            breakdown = {
                'machines': total_energy * 0.77,
                'exhaust_fan': total_energy * 0.12,
                'lights': total_energy * 0.07,
                'laser': total_energy * 0.04,
            }
        elif device.process_area == 'finishing':
            breakdown = {
                'machines': total_energy * 0.06,
                'exhaust_fan': total_energy * 0.20,
                'lights': total_energy * 0.02,
                'hvac': total_energy * 0.02,
                'office': total_energy * 0.70,
            }
        elif device.process_area == 'sewing':
            breakdown = {
                'machines': total_energy * 0.45,
                'exhaust_fan': total_energy * 0.35,
                'lights': total_energy * 0.07,
                'hvac': total_energy * 0.05,
                'office': total_energy * 0.08,
            }
        else:
            # Default/office
            breakdown = {
                'lights': total_energy * 0.30,
                'hvac': total_energy * 0.40,
                'office': total_energy * 0.30,
            }
        
        # For flowmeters, adjust breakdown (steam is primarily for machines)
        # Note: for flowmeters, total_energy is actually volume_m3
        if device.device_type == 'flowmeter':
            # Steam volume breakdown - convert to energy equivalent for component allocation
            energy_equiv = SteamConverter.cubic_meters_to_kwh(total_energy)
            breakdown = {
                'machines': energy_equiv * 0.90,  # Steam primarily for machines (in kWh equivalent)
                'hvac': energy_equiv * 0.10,
            }
        
        return breakdown

