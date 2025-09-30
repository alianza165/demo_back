from rest_framework import serializers
from .models import EnergySummary, ShiftEnergyData, ShiftDefinition, DeviceComparison

class EnergySummarySerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)
    
    class Meta:
        model = EnergySummary
        fields = [
            'id', 'device', 'device_name', 'timestamp', 'interval_type',
            'total_energy_kwh', 'avg_power_kw', 'max_power_kw', 'min_power_kw',
            'energy_cost', 'tariff_rate'
        ]

class ShiftEnergyDataSerializer(serializers.ModelSerializer):
    shift_name = serializers.CharField(source='shift.name', read_only=True)
    device_name = serializers.CharField(source='device.name', read_only=True)
    product_type = serializers.CharField(source='shift.product_type', read_only=True)
    
    class Meta:
        model = ShiftEnergyData
        fields = [
            'id', 'shift', 'shift_name', 'device', 'device_name', 'shift_date',
            'total_energy_kwh', 'avg_power_kw', 'peak_power_kw', 'units_produced',
            'energy_per_unit', 'cost_per_unit', 'total_cost', 'tariff_rate',
            'product_type'
        ]

class ShiftDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShiftDefinition
        fields = '__all__'

class DeviceComparisonSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceComparison
        fields = '__all__'
