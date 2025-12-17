"""
Serializers for reporting app.
"""
from rest_framework import serializers
from .models import (
    ProductionData,
    EfficiencyBenchmark,
    Target,
    MonthlyAggregate,
    DailyAggregate,
    EngineeringDashboard,
    CapacityLoad,
)


class ProductionDataSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)
    
    class Meta:
        model = ProductionData
        fields = '__all__'


class EfficiencyBenchmarkSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True, allow_null=True)
    
    class Meta:
        model = EfficiencyBenchmark
        fields = '__all__'


class TargetSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True, allow_null=True)
    progress_percentage = serializers.SerializerMethodField()
    
    class Meta:
        model = Target
        fields = '__all__'
    
    def get_progress_percentage(self, obj):
        """Calculate progress percentage."""
        if obj.target_value == 0:
            return 0
        
        if 'kwh_per_garment' in obj.metric_name or 'kwh_per_unit' in obj.metric_name:
            # For efficiency metrics, lower is better
            # Progress = how much better we are than target
            if obj.current_value == 0:
                return 0
            improvement = ((obj.target_value - obj.current_value) / obj.target_value) * 100
            return max(0, min(100, improvement))
        else:
            # For total metrics, higher is better
            return min(100, (obj.current_value / obj.target_value) * 100)


class MonthlyAggregateSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True, allow_null=True)
    month_str = serializers.CharField(source='month', read_only=True)
    
    class Meta:
        model = MonthlyAggregate
        fields = '__all__'


class DailyAggregateSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True, allow_null=True)
    date_str = serializers.CharField(source='date', read_only=True)
    device_process_area = serializers.CharField(source='device.process_area', read_only=True, allow_null=True)
    device_floor = serializers.CharField(source='device.floor', read_only=True, allow_null=True)
    device_load_type = serializers.CharField(source='device.load_type', read_only=True, allow_null=True)
    
    class Meta:
        model = DailyAggregate
        fields = '__all__'


# Dashboard-specific serializers
class DashboardDataCardSerializer(serializers.Serializer):
    """Data card values for dashboard top section."""
    title = serializers.CharField()
    value = serializers.FloatField()
    unit = serializers.CharField()
    change = serializers.FloatField(allow_null=True)
    change_percentage = serializers.FloatField(allow_null=True)
    trend = serializers.CharField(allow_null=True)  # 'up', 'down', 'stable'


class EnergyMixComponentSerializer(serializers.Serializer):
    """Single component in energy mix."""
    name = serializers.CharField()
    value = serializers.FloatField()
    percentage = serializers.FloatField()
    color = serializers.CharField(allow_null=True)


class EnergyMixSerializer(serializers.Serializer):
    """Energy mix breakdown for a process/device."""
    device_name = serializers.CharField()
    total_kwh = serializers.FloatField()
    load_kw = serializers.FloatField()
    components = EnergyMixComponentSerializer(many=True)


class MonthlyTrendDataSerializer(serializers.Serializer):
    """Monthly trend data point."""
    month = serializers.CharField()
    value = serializers.FloatField()
    zone = serializers.CharField()  # 'green', 'yellow', 'red'
    target = serializers.FloatField(allow_null=True)


class EfficiencyMetricSerializer(serializers.Serializer):
    """Efficiency metric value."""
    date = serializers.CharField()
    achieved = serializers.FloatField()
    target = serializers.FloatField(allow_null=True)
    benchmark = serializers.FloatField(allow_null=True)
    zone = serializers.CharField()  # 'green', 'yellow', 'red'


class EngineeringDashboardSerializer(serializers.ModelSerializer):
    """Serializer for Engineering Dashboard data."""
    
    class Meta:
        model = EngineeringDashboard
        fields = '__all__'


class CapacityLoadSerializer(serializers.ModelSerializer):
    """Serializer for Capacity Load data."""
    
    class Meta:
        model = CapacityLoad
        fields = '__all__'





