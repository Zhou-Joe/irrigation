from django.urls import path
from . import views,bulk,management_views,team_visibility

app_name = 'operations'
urlpatterns = [
    path('', views.home, name='home'),
    path('switch/', views.switch, name='switch'),
    path('locations/', views.locations, name='locations'),
    path('locations/new/', views.location_edit, name='location_new'),
    path('locations/batch/',bulk.create,name='location_batch'),
    path('locations/batch-sharing/',bulk.share,name='location_batch_sharing'),
    path('locations/team-visibility/',team_visibility.update,name='location_team_visibility'),
    path('locations/link-irrigation/', views.link_irrigation, name='link_irrigation'),
    path('locations/<uuid:pk>/', views.location_detail, name='location_detail'),
    path('locations/<uuid:pk>/edit/', views.location_edit, name='location_edit'),
    path('locations/<uuid:pk>/sharing/', views.sharing, name='sharing'),
    path('locations.geojson', views.location_geometry, name='location_geometry'),
    path('team/', views.team, name='team'),
    path('catalog/', views.catalog, name='catalog'),
    path('business-data/',management_views.business_data,name='business_data'),
    path('business-data/data/',management_views.catalog_data,name='catalog_data'),
    path('business-data/save/',management_views.catalog_save,name='catalog_save'),
    path('reports/',management_views.statistics,name='reports'),
    path('reports/export/',management_views.report_export,name='report_export'),
    path('reports/<int:pk>/action/',management_views.report_action,name='report_action'),
    path('plans/',management_views.plans,name='plans'),
    path('plans/save/',management_views.plan_save,name='plan_save'),
    path('plans/dispatch/',management_views.dispatch,name='dispatch'),
    path('tasks/<int:pk>/action/',management_views.task_action,name='task_action'),
    path('profile/',management_views.profile,name='profile'),
]
