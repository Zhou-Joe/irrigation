from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core import views
from core.api import (
    ZoneViewSet, PlantViewSet, WorkerViewSet,
    WorkOrderViewSet, EventViewSet, WorkLogViewSet
)

app_name = 'core'

router = DefaultRouter()
router.register(r'zones', ZoneViewSet)
router.register(r'plants', PlantViewSet)
router.register(r'workers', WorkerViewSet)
router.register(r'work-orders', WorkOrderViewSet)
router.register(r'events', EventViewSet)
router.register(r'work-logs', WorkLogViewSet)

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('api/', include(router.urls)),
]
