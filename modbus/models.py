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
    
    APPLICATION_CHOICES = [
        ('machine', 'Machine'),      # Specific equipment/machine
        ('supply', 'Supply'),        # Energy source (solar, utility, generator)
        ('department', 'Department'), # Whole department/building
        ('process', 'Process'),      # Specific manufacturing process
        ('facility', 'Facility'),    # Entire facility
    ]
    
    DEVICE_TYPE_CHOICES = [
        ('electricity', 'Electricity Analyzer'),
        ('flowmeter', 'Flowmeter'),
    ]
    
    # Basic device info
    name = models.CharField(max_length=100)
    device_model = models.ForeignKey(
        DeviceModel, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='devices'
    )
    device_type = models.CharField(
        max_length=20,
        choices=DEVICE_TYPE_CHOICES,
        default='electricity',
        help_text="Type of device: electricity analyzer or flowmeter"
    )
    application_type = models.CharField(
        max_length=20,
        choices=APPLICATION_CHOICES,
        default='machine',
        help_text="Where this device is installed"
    )
    
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
    location = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    
    # Single-line diagram relationships
    parent_device = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='child_devices',
        help_text="Parent device in the single-line diagram hierarchy"
    )
    
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
    
    CATEGORY_CHOICES = [
        ('voltage', 'Voltage'),
        ('current', 'Current'),
        ('power', 'Power'),
        ('energy', 'Energy'),
        ('power_quality', 'Power Quality'),
        ('harmonics', 'Harmonics'),
        ('frequency', 'Frequency'),
        ('temperature', 'Temperature'),
        ('flow', 'Flow'),
        ('pressure', 'Pressure'),
        ('heat', 'Heat'),
        ('density', 'Density'),
        ('status', 'Status'),
        ('other', 'Other'),
    ]
    
    # Links
    device_model = models.ForeignKey(
        DeviceModel, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='register_templates',
        help_text="Link to device model for predefined registers"
    )
    device = models.ForeignKey(
        ModbusDevice, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='registers',
        help_text="Link to specific device instance"
    )
    
    WORD_ORDER_CHOICES = [
        ('high-low', 'High-Low'),
        ('low-high', 'Low-High'),
    ]
    
    # Register configuration
    address = models.IntegerField()
    name = models.CharField(max_length=100)
    data_type = models.CharField(max_length=10, choices=DATA_TYPE_CHOICES, default='uint16')
    scale_factor = models.FloatField(default=1.0)
    unit = models.CharField(max_length=20, blank=True)
    order = models.IntegerField(default=0)
    
    # Multi-word register support
    register_count = models.IntegerField(
        default=0,
        help_text="Number of registers to read (0 = auto-calculate from data_type)"
    )
    word_order = models.CharField(
        max_length=10,
        choices=WORD_ORDER_CHOICES,
        default='high-low',
        help_text="Word order for multi-word registers (high-low or low-high)"
    )
    
    # Categorization
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    visualization_type = models.CharField(
        max_length=20, 
        choices=VISUALIZATION_TYPES,
        default='timeseries'
    )
    
    # Additional fields
    grafana_metric_name = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    influxdb_field_name = models.CharField(max_length=100, blank=True)
    
    # Reference to EnergyMeasurement field (optional)
    energy_measurement_field = models.CharField(
        max_length=50,
        blank=True,
        help_text="Corresponding field name in EnergyMeasurement model"
    )
    
    class Meta:
        ordering = ['order', 'address']
        # Ensure unique addresses per device/model combination
        constraints = [
            models.UniqueConstraint(
                fields=['device_model', 'address'],
                name='unique_address_per_model',
                condition=models.Q(device_model__isnull=False)
            ),
            models.UniqueConstraint(
                fields=['device', 'address'], 
                name='unique_address_per_device',
                condition=models.Q(device__isnull=False)
            ),
            # Ensure register belongs to EITHER device_model OR device, not both or neither
            models.CheckConstraint(
                check=(
                    (models.Q(device_model__isnull=False) & models.Q(device__isnull=True)) |
                    (models.Q(device_model__isnull=True) & models.Q(device__isnull=False))
                ),
                name='register_must_have_one_parent'
            )
        ]
    
    def get_register_count(self):
        """Get the effective register count (explicit or auto-calculated)"""
        if self.register_count > 0:
            return self.register_count
        
        # Auto-calculate based on data type
        type_map = {
            'uint16': 1, 'int16': 1,
            'uint32': 2, 'int32': 2, 'float32': 2
        }
        return type_map.get(self.data_type.lower(), 1)
    
    def get_influxdb_field(self):
        return self.influxdb_field_name or self.name

    def __str__(self):
        return f"{self.name} (0x{self.address:04X})"


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
