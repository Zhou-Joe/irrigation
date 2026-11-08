from django.urls import path
from . import views,bulk

app_name = 'operations'
urlpatterns = [
    path('', views.home, name='home'),
    path('switch/', views.switch, name='switch'),
    path('locations/', views.locations, name='locations'),
    path('locations/new/', views.location_edit, name='location_new'),
    path('locations/batch/',bulk.create,name='location_batch'),
    path('locations/batch-sharing/',bulk.share,name='location_batch_sharing'),
    path('locations/link-irrigation/', views.link_irrigation, name='link_irrigation'),
    path('locations/<uuid:pk>/', views.location_detail, name='location_detail'),
    path('locations/<uuid:pk>/edit/', views.location_edit, name='location_edit'),
    path('locations/<uuid:pk>/sharing/', views.sharing, name='sharing'),
    path('locations.geojson', views.location_geometry, name='location_geometry'),
    path('team/', views.team, name='team'),
    path('catalog/', views.catalog, name='catalog'),
]
