# models.py
from django.db import models
import json

class DeviceModel(models.Model):
    """Predefined device profiles/models for reusability"""
    name = models.CharField(max_length=100, unique=True)  # e.g., "ABB Power Meter", "Siemens Energy Analyzer"
    description = models.TextField(blank=True)
    manufacturer = models.CharField(max_length=100, blank=True)
    model_number = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.manufacturer} {self.name}"

class ModbusDevice(models.Model):
    PARITY_CHOICES = [
        ('N', 'None'),
        ('E', 'Even'),
        ('O', 'Odd'),
    ]
    
    # Basic device info
    name = models.CharField(max_length=100)  # Instance name e.g., "Main Panel Meter"
    device_model = models.ForeignKey(DeviceModel, on_delete=models.SET_NULL, 
                                   null=True, blank=True, related_name='devices')
    
    # Modbus connection settings
    port = models.CharField(max_length=100, default='/dev/ttyUSB0')
    address = models.IntegerField(default=1)
    baud_rate = models.IntegerField(default=9600)
    parity = models.CharField(max_length=1, choices=PARITY_CHOICES, default='N')
    stop_bits = models.IntegerField(default=1)
    byte_size = models.IntegerField(default=8)
    timeout = models.IntegerField(default=3)
    
    # Device status
    is_active = models.BooleanField(default=True)
    location = models.CharField(max_length=200, blank=True)  # e.g., "Main Electrical Room"
    description = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    grafana_dashboard_uid = models.CharField(max_length=100, blank=True)
    grafana_dashboard_url = models.URLField(blank=True)
    last_grafana_sync = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.device_model.name if self.device_model else 'Custom'})"


class RegisterTemplate(models.Model):
    """Predefined register templates for common energy metrics"""
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    address = models.IntegerField()
    data_type = models.CharField(
        max_length=20,
        choices=[
            ('uint16', 'Unsigned 16-bit'),
            ('int16', 'Signed 16-bit'), 
            ('uint32', 'Unsigned 32-bit'),
            ('int32', 'Signed 32-bit'),
            ('float32', 'Float 32-bit'),
        ],
        default='uint16'
    )
    scale_factor = models.FloatField(default=1.0)
    unit = models.CharField(max_length=20, blank=True)
    category = models.CharField(
        max_length=50,
        choices=[
            ('voltage', 'Voltage'),
            ('current', 'Current'),
            ('power', 'Power'),
            ('energy', 'Energy'),
            ('frequency', 'Frequency'),
            ('power_factor', 'Power Factor'),
            ('thd', 'THD'),
        ]
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['category', 'address']

    def __str__(self):
        return f"{self.name} (0x{self.address:04X})"


class ModbusRegister(models.Model):
    DATA_TYPE_CHOICES = [
        ('uint16', 'Unsigned 16-bit'),
        ('int16', 'Signed 16-bit'),
        ('uint32', 'Unsigned 32-bit'),
        ('int32', 'Signed 32-bit'),
        ('float32', 'Float 32-bit'),
    ]
    VISUALIZATION_TYPES = [
        ('timeseries', 'Time Series'),
        ('gauge', 'Gauge'),
        ('stat', 'Stat'),
    ]
    visualization_type = models.CharField(
        max_length=20, 
        choices=VISUALIZATION_TYPES,
        default='timeseries'
    )
    grafana_metric_name = models.CharField(max_length=100, blank=True)
    # Link to both device model (for templates) and specific device (for instances)
    device_model = models.ForeignKey(DeviceModel, on_delete=models.CASCADE, 
                                   null=True, blank=True, related_name='register_templates')
    device = models.ForeignKey(ModbusDevice, on_delete=models.CASCADE, 
                             null=True, blank=True, related_name='registers')
    
    # Register configuration
    address = models.IntegerField()
    name = models.CharField(max_length=100)
    data_type = models.CharField(max_length=10, choices=DATA_TYPE_CHOICES, default='uint16')
    scale_factor = models.FloatField(default=1.0)
    unit = models.CharField(max_length=20, blank=True)
    order = models.IntegerField(default=0)
    
    # Categorization for easier management
    CATEGORY_CHOICES = [
        ('voltage', 'Voltage'),
        ('current', 'Current'),
        ('power', 'Power'),
        ('energy', 'Energy'),
        ('power_quality', 'Power Quality'),
        ('harmonics', 'Harmonics'),
        ('frequency', 'Frequency'),
        ('other', 'Other'),
    ]
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    
    is_active = models.BooleanField(default=True)
    influxdb_field_name = models.CharField(max_length=100, blank=True)
    
    class Meta:
        ordering = ['order', 'address']
    
    def get_influxdb_field(self):
        """Get the actual field name in InfluxDB"""
        return self.influxdb_field_name or self.name

    def __str__(self):
        return f"{self.name} (0x{self.address:04X})"

class EnergyMeasurement(models.Model):
    """Stores electricity metrics for each device"""
    device = models.ForeignKey(ModbusDevice, on_delete=models.CASCADE, related_name='measurements')
    timestamp = models.DateTimeField(db_index=True)
    
    # Voltage measurements
    voltage_l1_n = models.FloatField(null=True, blank=True, help_text="Voltage Phase 1-Neutral (V)")
    voltage_l2_n = models.FloatField(null=True, blank=True, help_text="Voltage Phase 2-Neutral (V)")
    voltage_l3_n = models.FloatField(null=True, blank=True, help_text="Voltage Phase 3-Neutral (V)")
    voltage_l1_l2 = models.FloatField(null=True, blank=True, help_text="Voltage Phase 1-2 (V)")
    voltage_l2_l3 = models.FloatField(null=True, blank=True, help_text="Voltage Phase 2-3 (V)")
    voltage_l3_l1 = models.FloatField(null=True, blank=True, help_text="Voltage Phase 3-1 (V)")
    avg_voltage = models.FloatField(null=True, blank=True, help_text="Average Voltage (V)")
    
    # Current measurements
    current_l1 = models.FloatField(null=True, blank=True, help_text="Current Phase 1 (A)")
    current_l2 = models.FloatField(null=True, blank=True, help_text="Current Phase 2 (A)")
    current_l3 = models.FloatField(null=True, blank=True, help_text="Current Phase 3 (A)")
    current_neutral = models.FloatField(null=True, blank=True, help_text="Neutral Current (A)")
    avg_current = models.FloatField(null=True, blank=True, help_text="Average Current (A)")
    
    # Power measurements
    active_power_total = models.FloatField(null=True, blank=True, help_text="Total Active Power (kW)")
    active_power_l1 = models.FloatField(null=True, blank=True, help_text="Active Power Phase 1 (kW)")
    active_power_l2 = models.FloatField(null=True, blank=True, help_text="Active Power Phase 2 (kW)")
    active_power_l3 = models.FloatField(null=True, blank=True, help_text="Active Power Phase 3 (kW)")
    
    apparent_power_total = models.FloatField(null=True, blank=True, help_text="Total Apparent Power (kVA)")
    reactive_power_total = models.FloatField(null=True, blank=True, help_text="Total Reactive Power (kVAR)")
    
    # Energy measurements
    energy_active = models.FloatField(null=True, blank=True, help_text="Active Energy (kWh)")
    energy_reactive = models.FloatField(null=True, blank=True, help_text="Reactive Energy (kVARh)")
    
    # Power quality
    frequency = models.FloatField(null=True, blank=True, help_text="Frequency (Hz)")
    power_factor_total = models.FloatField(null=True, blank=True, help_text="Total Power Factor")
    power_factor_l1 = models.FloatField(null=True, blank=True, help_text="Power Factor Phase 1")
    power_factor_l2 = models.FloatField(null=True, blank=True, help_text="Power Factor Phase 2")
    power_factor_l3 = models.FloatField(null=True, blank=True, help_text="Power Factor Phase 3")
    
    # Harmonics
    thd_voltage_l1 = models.FloatField(null=True, blank=True, help_text="THD Voltage L1 (%)")
    thd_voltage_l2 = models.FloatField(null=True, blank=True, help_text="THD Voltage L2 (%)")
    thd_voltage_l3 = models.FloatField(null=True, blank=True, help_text="THD Voltage L3 (%)")
    thd_current_l1 = models.FloatField(null=True, blank=True, help_text="THD Current L1 (%)")
    thd_current_l2 = models.FloatField(null=True, blank=True, help_text="THD Current L2 (%)")
    thd_current_l3 = models.FloatField(null=True, blank=True, help_text="THD Current L3 (%)")
    
    # Additional metrics
    demand = models.FloatField(null=True, blank=True, help_text="Current Demand (kW)")
    max_demand = models.FloatField(null=True, blank=True, help_text="Maximum Demand (kW)")
    
    class Meta:
        indexes = [
            models.Index(fields=['device', 'timestamp']),
            models.Index(fields=['timestamp']),
        ]
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.device.name} - {self.timestamp}"

class DailyAggregate(models.Model):
    """Daily aggregated data for analytics"""
    device = models.ForeignKey(ModbusDevice, on_delete=models.CASCADE, related_name='daily_aggregates')
    date = models.DateField(db_index=True)
    
    # Voltage aggregates
    avg_voltage = models.FloatField()
    min_voltage = models.FloatField()
    max_voltage = models.FloatField()
    
    # Current aggregates
    avg_current = models.FloatField()
    max_current = models.FloatField()
    
    # Power aggregates
    total_energy = models.FloatField(help_text="Total energy consumed (kWh)")
    avg_power = models.FloatField()
    max_power = models.FloatField()
    min_power = models.FloatField()
    
    # Power quality aggregates
    avg_frequency = models.FloatField()
    avg_power_factor = models.FloatField()
    
    class Meta:
        unique_together = ['device', 'date']
        ordering = ['-date']
    
    def __str__(self):
        return f"{self.device.name} - {self.date}"

class ConfigurationLog(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('applied', 'Applied'),
        ('failed', 'Failed'),
    ]
    
    device = models.ForeignKey(ModbusDevice, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    applied_at = models.DateTimeField(null=True, blank=True)
    log_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.device.name} - {self.status} - {self.created_at}"
