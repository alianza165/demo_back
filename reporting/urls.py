"""
URL routing for reporting app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'production-data', views.ProductionDataViewSet, basename='production-data')
router.register(r'benchmarks', views.EfficiencyBenchmarkViewSet, basename='benchmark')
router.register(r'targets', views.TargetViewSet, basename='target')
router.register(r'monthly-aggregates', views.MonthlyAggregateViewSet, basename='monthly-aggregate')
router.register(r'daily-aggregates', views.DailyAggregateViewSet, basename='daily-aggregate')
router.register(r'engineering-dashboard', views.EngineeringDashboardViewSet, basename='engineering-dashboard')
router.register(r'capacity-loads', views.CapacityLoadViewSet, basename='capacity-load')

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('energy-mix/', views.EnergyMixView.as_view(), name='energy-mix'),
]





