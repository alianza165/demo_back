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


class EnergyAnalyticsQuerySerializer(serializers.Serializer):
    """
    Validate query parameters for the energy analytics endpoints.
    """

    start = serializers.DateTimeField(required=False)
    end = serializers.DateTimeField(required=False)
    days = serializers.IntegerField(required=False, min_value=1, default=8)
    device_id = serializers.CharField(required=False)
    devices = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=False
    )
    target_kwh = serializers.FloatField(required=False, min_value=0)
    include_hourly = serializers.BooleanField(required=False, default=True)
    include_trend = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        start = attrs.get("start")
        end = attrs.get("end")
        if start and end and start >= end:
            raise serializers.ValidationError("start must be earlier than end.")
        return attrs

    def get_devices(self) -> list[str]:
        data = self.validated_data
        devices: list[str] = []

        if "devices" in data:
            devices = list(data["devices"])
        elif "device_id" in data and data["device_id"]:
            devices = [data["device_id"]]

        return devices
