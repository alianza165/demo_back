from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'energy-summaries', views.EnergySummaryViewSet, basename='energy-summary')
router.register(r'shift-energy', views.ShiftEnergyViewSet, basename='shift-energy')
router.register(r'shift-definitions', views.ShiftDefinitionViewSet, basename='shift-definition')

urlpatterns = [
    # Router URLs (these will be at /api/analytics/energy-summaries/, etc.)
    path('analytics/', include(router.urls)),
    
    # Additional custom endpoints
    path('analytics/energy-summaries/compare_devices/', 
         views.EnergySummaryViewSet.as_view({'get': 'compare_devices'}), 
         name='compare-devices'),
    
    path('analytics/shift-energy/efficiency_report/', 
         views.ShiftEnergyViewSet.as_view({'get': 'efficiency_report'}), 
         name='shift-efficiency-report'),

    # New analytics insights endpoints
    path(
        'analytics/energy-insights/summary/',
        views.EnergyAnalyticsSummaryView.as_view(),
        name='energy-analytics-summary',
    ),
    path(
        'analytics/energy-insights/report/',
        views.EnergyAnalyticsReportView.as_view(),
        name='energy-analytics-report',
    ),
    
    # Energy analytics endpoints (custom actions on ViewSet)
    # Note: These use hyphens in URL but underscore in method names
    # The @action decorators register them automatically, but we add explicit paths
    # with hyphens for consistency with frontend expectations
    path(
        'analytics/energy-summaries/dashboard-stats/',
        views.EnergySummaryViewSet.as_view({'get': 'dashboard_stats'}),
        name='dashboard-stats',
    ),
    path(
        'analytics/energy-summaries/trends/',
        views.EnergySummaryViewSet.as_view({'get': 'trends'}),
        name='energy-trends',
    ),
    path(
        'analytics/energy-summaries/by-process-area/',
        views.EnergySummaryViewSet.as_view({'get': 'by_process_area'}),
        name='by-process-area',
    ),
    path(
        'analytics/energy-summaries/by-floor/',
        views.EnergySummaryViewSet.as_view({'get': 'by_floor'}),
        name='by-floor',
    ),
    path(
        'analytics/energy-summaries/by-device/',
        views.EnergySummaryViewSet.as_view({'get': 'by_device'}),
        name='by-device',
    ),
    path(
        'analytics/energy-summaries/heatmap-data/',
        views.EnergySummaryViewSet.as_view({'get': 'heatmap_data'}),
        name='heatmap-data',
    ),
    path(
        'analytics/energy-summaries/main-feeders/',
        views.EnergySummaryViewSet.as_view({'get': 'main_feeders'}),
        name='main-feeders',
    ),
    path(
        'analytics/energy-summaries/by-sub-department/',
        views.EnergySummaryViewSet.as_view({'get': 'by_sub_department'}),
        name='by-sub-department',
    ),
]
