from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.conf import settings

class EnergySummary(models.Model):
    """Hourly/daily energy summaries for analytics"""
    device = models.ForeignKey(
        'modbus.ModbusDevice',  # Use string reference
        on_delete=models.CASCADE
    )
    timestamp = models.DateTimeField()
    interval_type = models.CharField(
        max_length=10,
        choices=[('hourly', 'Hourly'), ('daily', 'Daily'), ('monthly', 'Monthly')]
    )
    
    # Energy metrics
    total_energy_kwh = models.FloatField()  # Total energy consumed
    avg_power_kw = models.FloatField()      # Average power
    max_power_kw = models.FloatField()      # Peak power
    min_power_kw = models.FloatField()      # Minimum power
    
    # Cost calculations
    energy_cost = models.FloatField(null=True, blank=True)  # Calculated cost
    tariff_rate = models.FloatField(default=0.15)  # $/kWh
    
    class Meta:
        indexes = [
            models.Index(fields=['device', 'timestamp']),
            models.Index(fields=['timestamp', 'interval_type']),
        ]
        unique_together = ['device', 'timestamp', 'interval_type']

class ShiftDefinition(models.Model):
    """User-defined shift patterns"""
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    # Shift times (24-hour format)
    shift_start = models.TimeField()
    shift_end = models.TimeField()
    days_of_week = ArrayField(
        models.IntegerField(),  # 0=Monday, 6=Sunday
        size=7,
        default=list
    )
    
    # Production data
    product_type = models.CharField(max_length=100, blank=True)
    units_produced = models.IntegerField(null=True, blank=True)
    tariff_rate = models.FloatField(default=0.15)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.name} ({self.shift_start} - {self.shift_end})"

class ShiftEnergyData(models.Model):
    """Energy consumption per shift"""
    shift = models.ForeignKey('ShiftDefinition', on_delete=models.CASCADE)
    device = models.ForeignKey(
        'modbus.ModbusDevice',  # Use string reference
        on_delete=models.CASCADE
    )
    shift_date = models.DateField()
    
    # Energy metrics
    total_energy_kwh = models.FloatField()
    avg_power_kw = models.FloatField()
    peak_power_kw = models.FloatField()
    
    # Production metrics
    units_produced = models.IntegerField(null=True, blank=True)
    energy_per_unit = models.FloatField(null=True, blank=True)  # kWh per unit
    cost_per_unit = models.FloatField(null=True, blank=True)   # Cost per unit
    
    # Cost calculations
    total_cost = models.FloatField()
    tariff_rate = models.FloatField(default=0.15)
    
    class Meta:
        unique_together = ['shift', 'device', 'shift_date']

class DeviceComparison(models.Model):
    """Pre-calculated device comparisons"""
    timestamp = models.DateTimeField()
    interval_type = models.CharField(max_length=10)
    
    # Comparison metrics - Use django.db.models.JSONField
    comparison_data = models.JSONField()  # Stores device comparisons
    # Format: {device1_id: {energy: 100, cost: 15}, device2_id: {...}}
    
    created_at = models.DateTimeField(auto_now_add=True)

class AnomalyDetection(models.Model):
    """Detected anomalies in energy consumption"""
    device = models.ForeignKey(
        'modbus.ModbusDevice',  # Use string reference
        on_delete=models.CASCADE
    )
    timestamp = models.DateTimeField()
    metric_type = models.CharField(max_length=50)  # 'power', 'energy', 'current'
    actual_value = models.FloatField()
    expected_value = models.FloatField()
    deviation = models.FloatField()  # Percentage deviation
    severity = models.CharField(max_length=20, choices=[
        ('low', 'Low'), ('medium', 'Medium'), ('high', 'High')
    ])
    
    class Meta:
        indexes = [
            models.Index(fields=['device', 'timestamp']),
        ]
