"""
Reporting app models for dashboards, benchmarks, and production data.
This app is separate from analytics to maintain clear separation of concerns.
"""
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone


class ProductionData(models.Model):
    """
    Production data (e.g., garments produced) for efficiency calculations.
    Links to modbus device to calculate kWh/garment metrics.
    """
    device = models.ForeignKey(
        'modbus.ModbusDevice',
        on_delete=models.CASCADE,
        related_name='production_records',
        help_text="Device/process for which production is recorded"
    )
    date = models.DateField(help_text="Date of production")
    
    # Production metrics
    units_produced = models.IntegerField(
        validators=[MinValueValidator(0)],
        help_text="Number of units produced (e.g., garments)"
    )
    shift_type = models.CharField(
        max_length=20,
        choices=[
            ('LT01', 'LT01'),
            ('LT02', 'LT02'),
            ('MAIN', 'MAIN'),
            ('full_day', 'Full Day'),
        ],
        default='full_day',
        help_text="Shift type for production"
    )
    
    # Additional metadata
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['device', 'date', 'shift_type']
        indexes = [
            models.Index(fields=['device', 'date']),
            models.Index(fields=['date']),
        ]
        ordering = ['-date', 'device']
    
    def __str__(self):
        return f"{self.device.name} - {self.date} - {self.units_produced} units"


class EfficiencyBenchmark(models.Model):
    """
    Historical benchmarks for efficiency metrics (e.g., kWh/garment).
    Calculated from historical data to establish targets.
    """
    BENCHMARK_TYPE_CHOICES = [
        ('best_day', 'Best Day'),
        ('best_week', 'Best Week'),
        ('best_month', 'Best Month'),
        ('average', 'Average'),
        ('median', 'Median'),
        ('custom', 'Custom'),
    ]
    
    device = models.ForeignKey(
        'modbus.ModbusDevice',
        on_delete=models.CASCADE,
        related_name='benchmarks',
        null=True,
        blank=True,
        help_text="Device-specific benchmark (null for overall benchmarks)"
    )
    
    benchmark_type = models.CharField(
        max_length=20,
        choices=BENCHMARK_TYPE_CHOICES,
        help_text="Type of benchmark"
    )
    
    # Efficiency metric
    metric_name = models.CharField(
        max_length=50,
        help_text="Metric name (e.g., 'kwh_per_garment', 'kwh_per_unit')"
    )
    
    benchmark_value = models.FloatField(
        validators=[MinValueValidator(0)],
        help_text="Benchmark value for this metric"
    )
    
    # Period this benchmark represents
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    
    # Calculation metadata
    calculated_from_days = models.IntegerField(
        null=True,
        blank=True,
        help_text="Number of days of data used for calculation"
    )
    
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['device', 'benchmark_type', 'metric_name']
        indexes = [
            models.Index(fields=['device', 'benchmark_type']),
            models.Index(fields=['metric_name', 'is_active']),
        ]
    
    def __str__(self):
        device_name = self.device.name if self.device else "Overall"
        return f"{device_name} - {self.metric_name} - {self.benchmark_type}: {self.benchmark_value:.2f}"


class Target(models.Model):
    """
    Monthly or weekly targets derived from benchmarks.
    Tracks progress towards efficiency goals.
    """
    TARGET_PERIOD_CHOICES = [
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
    ]
    
    device = models.ForeignKey(
        'modbus.ModbusDevice',
        on_delete=models.CASCADE,
        related_name='targets',
        null=True,
        blank=True,
        help_text="Device-specific target (null for overall targets)"
    )
    
    metric_name = models.CharField(
        max_length=50,
        help_text="Metric name (e.g., 'kwh_per_garment')"
    )
    
    target_period = models.CharField(
        max_length=20,
        choices=TARGET_PERIOD_CHOICES,
        help_text="Period for this target"
    )
    
    period_start = models.DateField(help_text="Start of target period")
    period_end = models.DateField(help_text="End of target period")
    
    target_value = models.FloatField(
        validators=[MinValueValidator(0)],
        help_text="Target value to achieve"
    )
    
    # Current progress
    current_value = models.FloatField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Current achieved value"
    )
    
    # Status calculation
    is_on_track = models.BooleanField(
        default=True,
        help_text="Whether we're on track to achieve target"
    )
    
    benchmark_used = models.ForeignKey(
        'EfficiencyBenchmark',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Benchmark this target was derived from"
    )
    
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['device', 'metric_name', 'target_period', 'period_start']
        indexes = [
            models.Index(fields=['period_start', 'period_end']),
            models.Index(fields=['is_on_track']),
        ]
        ordering = ['-period_start']
    
    def __str__(self):
        device_name = self.device.name if self.device else "Overall"
        return f"{device_name} - {self.metric_name} - {self.period_start}"


class MonthlyAggregate(models.Model):
    """
    Pre-calculated monthly aggregates for dashboard performance.
    Aggregated by Celery tasks to avoid real-time calculations.
    """
    device = models.ForeignKey(
        'modbus.ModbusDevice',
        on_delete=models.CASCADE,
        related_name='monthly_aggregates',
        null=True,
        blank=True,
        help_text="Device-specific aggregate (null for overall)"
    )
    
    month = models.DateField(help_text="First day of the month")
    
    # Energy metrics
    total_energy_kwh = models.FloatField(default=0)
    avg_daily_energy_kwh = models.FloatField(default=0)
    peak_power_kw = models.FloatField(default=0)
    
    # Component breakdown (stored as JSON for flexibility)
    component_breakdown = models.JSONField(
        default=dict,
        help_text="Breakdown by component (lights, machines, HVAC, etc.) in kWh"
    )
    
    # Production metrics (if available)
    total_units_produced = models.IntegerField(null=True, blank=True)
    
    # Efficiency metrics
    efficiency_kwh_per_unit = models.FloatField(
        null=True,
        blank=True,
        help_text="Calculated kWh per unit (e.g., kWh/garment)"
    )
    
    # Cost metrics
    total_cost = models.FloatField(default=0)
    tariff_rate = models.FloatField(default=0.15)
    
    # Data quality
    data_completeness = models.FloatField(
        default=100.0,
        help_text="Percentage of expected data points available"
    )
    
    last_calculated = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['device', 'month']
        indexes = [
            models.Index(fields=['month']),
            models.Index(fields=['device', 'month']),
        ]
        ordering = ['-month']
    
    def __str__(self):
        device_name = self.device.name if self.device else "Overall"
        return f"{device_name} - {self.month.strftime('%Y-%m')}"


class DailyAggregate(models.Model):
    """
    Pre-calculated daily aggregates for trend analysis.
    """
    device = models.ForeignKey(
        'modbus.ModbusDevice',
        on_delete=models.CASCADE,
        related_name='daily_aggregates',
        null=True,
        blank=True,
    )
    
    date = models.DateField()
    
    # Energy metrics
    total_energy_kwh = models.FloatField(default=0)
    avg_power_kw = models.FloatField(default=0)
    peak_power_kw = models.FloatField(default=0)
    
    # Component breakdown
    component_breakdown = models.JSONField(default=dict)
    
    # Production
    units_produced = models.IntegerField(null=True, blank=True)
    efficiency_kwh_per_unit = models.FloatField(null=True, blank=True)
    
    # Cost
    total_cost = models.FloatField(default=0)
    
    # Overtime and meter tracking
    is_overtime = models.BooleanField(
        default=False,
        help_text="Whether this data represents overtime hours"
    )
    meter_reading = models.FloatField(
        null=True,
        blank=True,
        help_text="Raw meter reading value"
    )
    daily_units_kwh = models.FloatField(
        null=True,
        blank=True,
        help_text="Daily units consumed in kWh (from meter difference)"
    )
    
    last_calculated = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['device', 'date', 'is_overtime']
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['device', 'date']),
            models.Index(fields=['is_overtime']),
        ]
        ordering = ['-date']
    
    def __str__(self):
        device_name = self.device.name if self.device else "Overall"
        overtime = " (OT)" if self.is_overtime else ""
        return f"{device_name} - {self.date}{overtime}"


class EngineeringDashboard(models.Model):
    """
    Engineering dashboard data for utilities, gen-sets, and resource status.
    Based on the Dashboard sheet from Master DND- Dashboard.xlsx
    """
    date = models.DateField(help_text="Date of the dashboard entry")
    
    # Utilities Production Rate
    kwh_generated = models.FloatField(
        null=True,
        blank=True,
        help_text="KWH Generated"
    )
    kw_avg = models.FloatField(
        null=True,
        blank=True,
        help_text="KW Average"
    )
    kw_peak = models.FloatField(
        null=True,
        blank=True,
        help_text="KW Peak"
    )
    
    # Resource Group Status
    avg_flow_tons_per_hr = models.FloatField(
        null=True,
        blank=True,
        help_text="Average Flow (Tons/Hrs)"
    )
    husk_kgs = models.FloatField(
        null=True,
        blank=True,
        help_text="Husk (Kgs)"
    )
    steam_tons = models.FloatField(
        null=True,
        blank=True,
        help_text="Steam (Tons)"
    )
    wastage_kg = models.FloatField(
        null=True,
        blank=True,
        help_text="Wastage (Kg)"
    )
    gas_availability = models.BooleanField(
        null=True,
        blank=True,
        help_text="Gas Availability"
    )
    
    # Gen-Sets / Others
    gen_set_from = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Gen-Set From time"
    )
    gen_set_to = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Gen-Set To time"
    )
    gen_set_hours = models.FloatField(
        null=True,
        blank=True,
        help_text="Gen-Set Hours"
    )
    dg_engine = models.CharField(
        max_length=100,
        blank=True,
        help_text="DG Engine identifier"
    )
    downtime = models.FloatField(
        null=True,
        blank=True,
        help_text="Downtime in hours"
    )
    
    # Additional metadata
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['date']
        indexes = [
            models.Index(fields=['date']),
        ]
        ordering = ['-date']
    
    def __str__(self):
        return f"Engineering Dashboard - {self.date}"


class CapacityLoad(models.Model):
    """
    Capacity and load data for production lines and exhaust fans.
    Based on the Capacity load sheet from DND Nov Master Format Final.xlsx
    """
    LOCATION_CHOICES = [
        ('GF', 'Ground Floor'),
        ('FF', 'First Floor'),
        ('SF', 'Second Floor'),
        ('WF', 'Washing Floor'),
    ]
    
    EQUIPMENT_TYPE_CHOICES = [
        ('production_line', 'Production Line'),
        ('exhaust_fan', 'Exhaust Fan'),
        ('highbay', 'Highbay'),
        ('other', 'Other'),
    ]
    
    PROCESS_AREA_CHOICES = [
        ('denim', 'Denim'),
        ('finishing', 'Finishing'),
        ('washing', 'Washing'),
        ('sewing', 'Sewing'),
        ('packing', 'Packing'),
        ('cutting', 'Cutting'),
        ('general', 'General'),
    ]
    
    # Identification
    name = models.CharField(
        max_length=200,
        help_text="Equipment name (e.g., 'Finishing Lines', 'Exhaust Fans GF')"
    )
    equipment_type = models.CharField(
        max_length=20,
        choices=EQUIPMENT_TYPE_CHOICES,
        help_text="Type of equipment"
    )
    process_area = models.CharField(
        max_length=20,
        choices=PROCESS_AREA_CHOICES,
        default='general',
        help_text="Process area this equipment belongs to"
    )
    location = models.CharField(
        max_length=10,
        choices=LOCATION_CHOICES,
        help_text="Floor location"
    )
    
    # Capacity specifications
    quantity = models.IntegerField(
        default=1,
        validators=[MinValueValidator(0)],
        help_text="Number of units (QTY)"
    )
    power_per_unit_kw = models.FloatField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Power per unit in kW"
    )
    total_load_kw = models.FloatField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Total load (kW × QTY)"
    )
    
    # Shift data (8-hour shift)
    shift_hours = models.FloatField(
        default=8.0,
        help_text="Shift duration in hours"
    )
    daily_kwh = models.FloatField(
        null=True,
        blank=True,
        help_text="Daily consumption in kWh"
    )
    monthly_kwh = models.FloatField(
        null=True,
        blank=True,
        help_text="Monthly consumption in kWh"
    )
    
    # Additional metadata
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['equipment_type', 'process_area']),
            models.Index(fields=['location']),
            models.Index(fields=['is_active']),
        ]
        ordering = ['process_area', 'location', 'name']
    
    def __str__(self):
        return f"{self.name} - {self.get_location_display()} ({self.total_load_kw} kW)"
