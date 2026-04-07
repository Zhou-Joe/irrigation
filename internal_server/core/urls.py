from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core import views
from core.api import (
    ZoneViewSet, PlantViewSet, WorkerViewSet,
    WorkOrderViewSet, EventViewSet, WorkLogViewSet,
    MaintenanceRequestViewSet, ProjectSupportRequestViewSet, WaterRequestViewSet,
    worker_login, get_all_requests, get_weather
)

app_name = 'core'

router = DefaultRouter()
router.register(r'zones', ZoneViewSet)
router.register(r'plants', PlantViewSet)
router.register(r'workers', WorkerViewSet)
router.register(r'work-orders', WorkOrderViewSet)
router.register(r'events', EventViewSet)
router.register(r'work-logs', WorkLogViewSet)
router.register(r'maintenance-requests', MaintenanceRequestViewSet)
router.register(r'project-support-requests', ProjectSupportRequestViewSet)
router.register(r'water-requests', WaterRequestViewSet)

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
    path('register/', views.register, name='register'),
    path('registration-approval/', views.registration_approval, name='registration_approval'),
    path('settings/', views.settings_page, name='settings'),
    path('settings/zone/<int:zone_id>/', views.zone_edit, name='zone_edit'),
    path('settings/zone/<int:zone_id>/delete/', views.zone_delete, name='zone_delete'),
    path('settings/zone/new/', views.zone_new, name='zone_new'),
    path('requests/', views.requests_page, name='requests'),
    path('requests/<str:type_code>/<int:request_id>/', views.request_detail, name='request_detail'),
    path('requests/<str:type_code>/<int:request_id>/update/', views.update_request_status, name='update_request_status'),
    path('api/auth/login', worker_login, name='worker_login'),
    path('api/requests', get_all_requests, name='get_all_requests'),
    path('api/weather', get_weather, name='get_weather'),
    path('api/', include(router.urls)),
]
