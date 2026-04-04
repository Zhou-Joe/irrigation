import json
from django.shortcuts import render
from django.db.models import Count, Q
from core.models import Zone


def dashboard(request):
    """
    Main dashboard view with interactive map showing irrigation zones.
    """
    # Get all zones with annotations
    zones = Zone.objects.all().annotate(
        plant_count=Count('plants', distinct=True),
        pending_work_orders=Count(
            'work_orders',
            filter=Q(work_orders__status='pending'),
            distinct=True
        )
    )

    # Prepare zones data for template
    zones_data = []
    for zone in zones:
        zones_data.append({
            'id': zone.id,
            'code': zone.code,
            'name': zone.name,
            'description': zone.description,
            'boundary_points': zone.boundary_points,
            'status': zone.status,
            'statusDisplay': zone.get_status_display(),
            'plant_count': zone.plant_count or 0,
            'pending_work_orders': zone.pending_work_orders or 0,
        })

    context = {
        'zones': zones,
        'zones_json': json.dumps(zones_data),
    }

    return render(request, 'core/dashboard.html', context)
