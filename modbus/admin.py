# modbus/admin.py
from django.contrib import admin
from .models import DeviceModel, ModbusDevice, ModbusRegister, ConfigurationLog

class ModbusRegisterInline(admin.TabularInline):
    model = ModbusRegister
    extra = 1
    fields = ['address', 'name', 'data_type', 'scale_factor', 'unit', 'category', 'order', 'is_active']

@admin.register(DeviceModel)
class DeviceModelAdmin(admin.ModelAdmin):
    list_display = ['name', 'manufacturer', 'model_number', 'is_active']
    list_filter = ['manufacturer', 'is_active']
    search_fields = ['name', 'manufacturer', 'model_number']
    inlines = [ModbusRegisterInline]

@admin.register(ModbusDevice)
class ModbusDeviceAdmin(admin.ModelAdmin):
    list_display = ['name', 'device_model', 'address', 'port', 'is_active', 'location']
    list_filter = ['device_model', 'is_active', 'created_at']
    search_fields = ['name', 'location', 'description']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [ModbusRegisterInline]

@admin.register(ModbusRegister)
class ModbusRegisterAdmin(admin.ModelAdmin):
    list_display = ['name', 'address', 'device', 'device_model', 'category', 'data_type', 'is_active']
    list_filter = ['category', 'data_type', 'is_active']
    search_fields = ['name', 'address']

@admin.register(ConfigurationLog)
class ConfigurationLogAdmin(admin.ModelAdmin):
    list_display = ['device', 'status', 'created_at', 'applied_at']
    list_filter = ['status', 'created_at']
    readonly_fields = ['created_at']
