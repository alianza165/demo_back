from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'energy-summaries', views.EnergySummaryViewSet, basename='energy-summary')
router.register(r'shift-energy', views.ShiftEnergyViewSet, basename='shift-energy')
router.register(r'shift-definitions', views.ShiftDefinitionViewSet, basename='shift-definition')

urlpatterns = [
    path('analytics/', include(router.urls)),
    
    # Additional custom endpoints
    path('analytics/energy-summaries/compare_devices/', 
         views.EnergySummaryViewSet.as_view({'get': 'compare_devices'}), 
         name='compare-devices'),
    
    path('analytics/shift-energy/efficiency_report/', 
         views.ShiftEnergyViewSet.as_view({'get': 'efficiency_report'}), 
         name='shift-efficiency-report'),
]
