from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core import views
from core.sync_views import sync_receive, sync_status, agent_status
from core.api import (
    ZoneViewSet, PlantViewSet, WorkerViewSet,
    WorkOrderViewSet, EventViewSet, WorkLogViewSet,
    MaintenanceRequestViewSet, ProjectSupportRequestViewSet, WaterRequestViewSet,
    EquipmentCatalogViewSet, ZoneEquipmentViewSet,
    PipelineViewSet,
    PatchViewSet, LocationViewSet, WorkCategoryViewSet, InfoSourceViewSet,
    FaultCategoryViewSet, FaultSubTypeViewSet, WorkReportViewSet,
    DemandCategoryViewSet, DemandDepartmentViewSet, DemandRecordViewSet,
    worker_login, get_all_requests, get_weather, demand_stats, demand_calendar
)
from core.views import equipment_catalog_autocomplete

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
router.register(r'equipment-catalog', EquipmentCatalogViewSet)
router.register(r'zone-equipment', ZoneEquipmentViewSet)
router.register(r'pipelines', PipelineViewSet)
router.register(r'patches', PatchViewSet)
router.register(r'locations', LocationViewSet)
router.register(r'work-categories', WorkCategoryViewSet)
router.register(r'info-sources', InfoSourceViewSet)
router.register(r'fault-categories', FaultCategoryViewSet)
router.register(r'fault-subtypes', FaultSubTypeViewSet)
router.register(r'work-reports', WorkReportViewSet, basename='workreport')
router.register(r'demand-categories', DemandCategoryViewSet)
router.register(r'demand-departments', DemandDepartmentViewSet)
router.register(r'demand-records', DemandRecordViewSet, basename='demandrecord')

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('stats/', views.stats_dashboard, name='stats_dashboard'),
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
    path('profile/', views.profile_page, name='profile'),
    path('register/', views.register, name='register'),
    path('registration-approval/', views.registration_approval, name='registration_approval'),
    path('user-management/', views.user_management, name='user_management'),
    path('user-management/<str:profile_type>/<int:profile_id>/edit/', views.user_edit, name='user_edit'),
    path('settings/', views.settings_page, name='settings'),
    path('settings/zone/<int:zone_id>/', views.zone_edit, name='zone_edit'),
    path('zone/<int:zone_id>/detail/', views.zone_detail_page, name='zone_detail'),
    path('settings/zone/<int:zone_id>/delete/', views.zone_delete, name='zone_delete'),
    path('settings/zone/new/', views.zone_new, name='zone_new'),
    path('settings/pipeline/new/', views.pipeline_new, name='pipeline_new'),
    path('settings/pipeline/<int:pipeline_id>/', views.pipeline_edit, name='pipeline_edit'),
    path('settings/pipeline/<int:pipeline_id>/delete/', views.pipeline_delete, name='pipeline_delete'),
    path('settings/patch/new/', views.patch_new, name='patch_new'),
    path('settings/patch/<int:patch_id>/', views.patch_edit, name='patch_edit'),
    path('settings/patch/<int:patch_id>/delete/', views.patch_delete, name='patch_delete'),
    path('requests/', views.requests_page, name='requests'),
    path('requests/<str:type_code>/<int:request_id>/', views.request_detail, name='request_detail'),
    path('requests/<str:type_code>/<int:request_id>/update/', views.update_request_status, name='update_request_status'),
    path('work-reports/', views.work_reports_list, name='work_reports'),
    path('work-reports/new/', views.work_report_create, name='work_report_create'),
    path('work-reports/<int:report_id>/', views.work_report_detail, name='work_report_detail'),
    path('work-reports/<int:report_id>/edit/', views.work_report_edit, name='work_report_edit'),
    path('work-reports/<int:report_id>/upload-photo/', views.work_report_upload_photo, name='work_report_upload_photo'),
    path('work-reports/<int:report_id>/remove-photo/', views.work_report_remove_photo, name='work_report_remove_photo'),
    path('work-reports/<int:report_id>/delete/', views.work_report_delete, name='work_report_delete'),
    path('demands/', views.demands_page, name='demands'),
    path('api/auth/login', worker_login, name='worker_login'),
    path('api/requests', get_all_requests, name='get_all_requests'),
    path('api/weather', get_weather, name='get_weather'),
    path('api/demand-stats', demand_stats, name='demand_stats'),
    path('api/demand-calendar', demand_calendar, name='demand_calendar'),
    path('api/custom-report', views.custom_report_api, name='custom_report_api'),
    path('custom-report/', views.custom_report, name='custom_report'),
    path('api/equipment-catalog/autocomplete', equipment_catalog_autocomplete, name='equipment_catalog_autocomplete'),
    path('api/', include(router.urls)),
    path('api/maxicom-dashboard', views.maxicom_dashboard_api, name='maxicom_dashboard_api'),
    path('api/sync/receive', sync_receive, name='sync_receive'),
    path('api/sync/status', sync_status, name='sync_status'),
    path('api/sync/agent-status', agent_status, name='agent_status'),
]
