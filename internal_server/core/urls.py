from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core import views
from core.sync_views import sync_receive, sync_status, agent_status
from core.ai_views import ai_chat, ai_status
from core.api import (
    ZoneViewSet, PlantViewSet, WorkerViewSet,
    WorkOrderViewSet, EventViewSet, WorkLogViewSet,
    MaintenanceRequestViewSet, ProjectSupportRequestViewSet, WaterRequestViewSet,
    EquipmentCatalogViewSet, ZoneEquipmentViewSet,
    PipelineViewSet,
    PatchViewSet, LocationViewSet, RegionViewSet, WorkCategoryViewSet, InfoSourceViewSet,
    FaultCategoryViewSet, FaultSubTypeViewSet, WorkReportViewSet,
    DemandCategoryViewSet, DemandDepartmentViewSet, DemandRecordViewSet,
    worker_login, get_all_requests, get_weather, demand_stats, demand_calendar
)
from core.views import equipment_catalog_autocomplete
from core.workorder_tree_views import (
    workorder_tree_form, project_create_api, planned_maintenance_pending,
    project_management, project_save, project_delete,
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
router.register(r'equipment-catalog', EquipmentCatalogViewSet)
router.register(r'zone-equipment', ZoneEquipmentViewSet)
router.register(r'pipelines', PipelineViewSet)
router.register(r'patches', PatchViewSet)
router.register(r'regions', RegionViewSet)
router.register(r'locations', LocationViewSet, basename='location')
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
    path('settings/zone/export/', views.zone_export_excel, name='zone_export_excel'),
    path('settings/zone/import/', views.zone_import_preview, name='zone_import_preview'),
    path('settings/zone/import/confirm/', views.zone_import_confirm, name='zone_import_confirm'),
    path('settings/zone/<int:zone_id>/', views.zone_edit, name='zone_edit'),
    path('zone/<int:zone_id>/detail/', views.zone_detail_page, name='zone_detail'),
    path('zone/<int:zone_id>/smooth/', views.zone_smooth_update, name='zone_smooth_update'),
    path('zone/<int:zone_id>/remark/add/', views.zone_remark_add, name='zone_remark_add'),
    path('zone/<int:zone_id>/remark/<int:index>/confirm/', views.zone_remark_confirm, name='zone_remark_confirm'),
    path('zone/<int:zone_id>/remark/<int:index>/move/', views.zone_remark_move, name='zone_remark_move'),
    path('settings/zone/<int:zone_id>/delete/', views.zone_delete, name='zone_delete'),
    path('settings/zone/new/', views.zone_new, name='zone_new'),
    path('settings/zone/batch-draw/', views.zone_batch_draw, name='zone_batch_draw'),
    path('settings/zone/quick-draw/', views.zone_quick_draw, name='zone_quick_draw'),
    path('settings/zone/quick-draw/mobile/', views.zone_quick_draw_mobile, name='zone_quick_draw_mobile'),
    path('settings/zone/dxf-import/', views.zone_dxf_import, name='zone_dxf_import'),
    path('settings/map-style/', views.map_style_editor, name='map_style_editor'),
    path('settings/pipeline/new/', views.pipeline_new, name='pipeline_new'),
    path('settings/pipeline/<int:pipeline_id>/', views.pipeline_edit, name='pipeline_edit'),
    path('settings/pipeline/<int:pipeline_id>/delete/', views.pipeline_delete, name='pipeline_delete'),
    path('settings/patch/new/', views.patch_new, name='patch_new'),
    path('settings/patch/<int:patch_id>/', views.patch_edit, name='patch_edit'),
    path('settings/patch/<int:patch_id>/delete/', views.patch_delete, name='patch_delete'),
    path('settings/batch-delete-patch/', views.batch_delete_patch, name='batch_delete_patch'),
    path('settings/batch-delete-zone/', views.batch_delete_zone, name='batch_delete_zone'),
    path('settings/batch-delete-pipeline/', views.batch_delete_pipeline, name='batch_delete_pipeline'),
    path('settings/region/new/', views.region_new, name='region_new'),
    path('settings/region/<int:region_id>/', views.region_edit, name='region_edit'),
    path('settings/region/<int:region_id>/delete/', views.region_delete, name='region_delete'),
    path('settings/batch-delete-region/', views.batch_delete_region, name='batch_delete_region'),
    path('settings/landmark/new/', views.landmark_new, name='landmark_new'),
    path('settings/landmark/<int:landmark_id>/', views.landmark_edit, name='landmark_edit'),
    path('settings/landmark/<int:landmark_id>/delete/', views.landmark_delete, name='landmark_delete'),
    path('settings/batch-delete-landmark/', views.batch_delete_landmark, name='batch_delete_landmark'),
    path('api/landmarks/', views.landmarks_api, name='landmarks_api'),
    path('api/landmarks/recalculate/', views.landmarks_recalculate, name='landmarks_recalculate'),
    path('requests/', views.requests_page, name='requests'),
    path('requests/<str:type_code>/<int:request_id>/', views.request_detail, name='request_detail'),
    path('requests/<str:type_code>/<int:request_id>/update/', views.update_request_status, name='update_request_status'),
    path('work-reports/', views.work_reports_list, name='work_reports'),
    path('work-reports/new/', views.work_report_create, name='work_report_create'),
    path('work-reports/tree/new/', workorder_tree_form, name='workorder_tree_form'),
    path('api/irrigation-project/create/', project_create_api, name='irrigation_project_create'),
    path('api/planned-maintenance/pending/', planned_maintenance_pending, name='planned_maintenance_pending'),
    path('projects/', project_management, name='project_management'),
    path('projects/save/', project_save, name='project_save'),
    path('projects/<int:pk>/delete/', project_delete, name='project_delete'),
    path('work-reports/tree/<int:report_id>/edit/', workorder_tree_form, name='workorder_tree_form_edit'),
    path('work-reports/<int:report_id>/', views.work_report_detail, name='work_report_detail'),
    path('work-reports/<int:report_id>/edit/', views.work_report_edit, name='work_report_edit'),
    path('work-reports/<int:report_id>/upload-photo/', views.work_report_upload_photo, name='work_report_upload_photo'),
    path('work-reports/<int:report_id>/remove-photo/', views.work_report_remove_photo, name='work_report_remove_photo'),
    path('work-reports/<int:report_id>/delete/', views.work_report_delete, name='work_report_delete'),
    path('demands/', views.demands_page, name='demands'),
    path('mobile/workorder/v2/', views.workorder_mobile_v2, name='workorder_mobile_v2'),
    path('mobile/workorder/history/', views.workorder_history, name='workorder_history'),
    path('mobile/water-request/v2/', views.water_request_mobile_v2, name='water_request_mobile_v2'),
    path('api/zone-geo/', views.zone_geo_api, name='zone_geo_api'),
    path('api/zones-in-area/', views.zones_in_area_api, name='zones_in_area_api'),
    path('api/modal/workorder-data/', views.workorder_modal_data, name='workorder_modal_data'),
    path('api/modal/water-request-data/', views.water_request_modal_data, name='water_request_modal_data'),
    path('api/auth/login', worker_login, name='worker_login'),
    path('api/requests', get_all_requests, name='get_all_requests'),
    path('api/weather', get_weather, name='get_weather'),
    path('api/demand-stats', demand_stats, name='demand_stats'),
    path('api/demand-calendar', demand_calendar, name='demand_calendar'),
    path('api/custom-report', views.custom_report_api, name='custom_report_api'),
    path('custom-report/', views.custom_report, name='custom_report'),
    path('api/equipment-catalog/autocomplete', equipment_catalog_autocomplete, name='equipment_catalog_autocomplete'),
    path('api/zones-by-patch/', views.zone_batch_draw_zones_api, name='zones_by_patch'),
    path('api/', include(router.urls)),
    path('api/user/preferences', views.user_preferences_api, name='user_preferences_api'),
    path('api/maxicom-dashboard', views.maxicom_dashboard_api, name='maxicom_dashboard_api'),
    path('api/sync/receive', sync_receive, name='sync_receive'),
    path('api/sync/status', sync_status, name='sync_status'),
    path('api/sync/agent-status', agent_status, name='agent_status'),
    path('api/ai/chat', ai_chat, name='ai_chat'),
    path('api/ai/status', ai_status, name='ai_status'),
]
