from django.contrib import admin
from .models import (
    ProductionData,
    EfficiencyBenchmark,
    Target,
    MonthlyAggregate,
    DailyAggregate,
)


@admin.register(ProductionData)
class ProductionDataAdmin(admin.ModelAdmin):
    list_display = ['device', 'date', 'shift_type', 'units_produced', 'created_at']
    list_filter = ['device', 'date', 'shift_type']
    search_fields = ['device__name', 'notes']
    date_hierarchy = 'date'


@admin.register(EfficiencyBenchmark)
class EfficiencyBenchmarkAdmin(admin.ModelAdmin):
    list_display = ['device', 'metric_name', 'benchmark_type', 'benchmark_value', 'is_active', 'created_at']
    list_filter = ['benchmark_type', 'metric_name', 'is_active', 'device']
    search_fields = ['metric_name', 'notes']
    readonly_fields = ['calculated_from_days', 'created_at', 'updated_at']


@admin.register(Target)
class TargetAdmin(admin.ModelAdmin):
    list_display = ['device', 'metric_name', 'target_period', 'period_start', 'target_value', 'current_value', 'is_on_track']
    list_filter = ['target_period', 'is_on_track', 'device']
    search_fields = ['metric_name', 'notes']
    date_hierarchy = 'period_start'
    readonly_fields = ['current_value', 'is_on_track', 'created_at', 'updated_at']


@admin.register(MonthlyAggregate)
class MonthlyAggregateAdmin(admin.ModelAdmin):
    list_display = ['device', 'month', 'total_energy_kwh', 'efficiency_kwh_per_unit', 'total_cost', 'last_calculated']
    list_filter = ['month', 'device']
    search_fields = ['device__name']
    date_hierarchy = 'month'
    readonly_fields = ['last_calculated']


@admin.register(DailyAggregate)
class DailyAggregateAdmin(admin.ModelAdmin):
    list_display = ['device', 'date', 'total_energy_kwh', 'efficiency_kwh_per_unit', 'total_cost', 'last_calculated']
    list_filter = ['date', 'device']
    search_fields = ['device__name']
    date_hierarchy = 'date'
    readonly_fields = ['last_calculated']
