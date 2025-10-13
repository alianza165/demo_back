# modbus/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Create a router and register our viewsets with it
router = DefaultRouter()
router.register(r'devices', views.ModbusDeviceViewSet, basename='device')
router.register(r'device-models', views.DeviceModelViewSet, basename='device-model')  # Now this works!
router.register(r'config-logs', views.ConfigurationLogViewSet, basename='config-log')

urlpatterns = [
    # API routes
    path('modbus/', include(router.urls)),
    
    # Additional custom endpoints (these are now included in the router automatically)
    path('modbus/devices/<int:pk>/apply_configuration/', 
         views.ModbusDeviceViewSet.as_view({'post': 'apply_configuration'}), 
         name='device-apply-configuration'),
    
    path('modbus/devices/apply_all_configurations/', 
         views.ModbusDeviceViewSet.as_view({'post': 'apply_all_configurations'}), 
         name='apply-all-configurations'),
    
    # Health check endpoints
    path('health/', views.health_check, name='health-check'),
    path('health/influxdb/', views.influxdb_health_check, name='influxdb-health-check'),
    path('health/modbus/', views.modbus_health_check, name='modbus-health-check'),
    path('health/config/', views.config_status, name='config-status'),
]
