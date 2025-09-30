# modbus/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Create a router and register our viewsets with it
router = DefaultRouter()
router.register(r'devices', views.ModusDeviceViewSet, basename='device')
router.register(r'device-models', views.DeviceModelViewSet, basename='devicemodel')
router.register(r'config-logs', views.ConfigurationLogViewSet, basename='config-log')
router.register(r'register-templates', views.RegisterTemplateViewSet, basename='register-template')


urlpatterns = [
    # API routes
    path('modbus/', include(router.urls)),
    
    # Additional custom endpoints
    path('modbus/devices/<int:pk>/apply_configuration/', 
         views.ModusDeviceViewSet.as_view({'post': 'apply_configuration'}), 
         name='device-apply-configuration'),
    
    path('modbus/devices/<int:pk>/config_logs/', 
         views.ModusDeviceViewSet.as_view({'get': 'config_logs'}), 
         name='device-config-logs'),
    
    path('modbus/devices/apply_all_configurations/', 
         views.ModusDeviceViewSet.as_view({'post': 'apply_all_configurations'}), 
         name='apply-all-configurations'),

    path('modbus/register-templates/by_category/', 
         views.RegisterTemplateViewSet.as_view({'get': 'by_category'}), 
         name='register-templates-by-category'),
    
    # Health check endpoints
    path('health/', views.health_check, name='health-check'),
    path('health/influxdb/', views.influxdb_health_check, name='influxdb-health-check'),
    path('health/modbus/', views.modbus_health_check, name='modbus-health-check'),
    path('health/config/', views.config_status, name='config-status'),

    # Add Grafana-specific endpoints
    path('modbus/devices/<int:pk>/grafana_dashboard/', 
         views.ModusDeviceViewSet.as_view({'get': 'grafana_dashboard'}), 
         name='device-grafana-dashboard'),

]
