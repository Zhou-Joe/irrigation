"""
Context processors for making data available to all templates.
"""
from .models import RegistrationRequest, WaterRequest


def notifications(request):
    """
    Provide notification data to all templates.
    """
    notifications_list = []

    # Only show notifications for authenticated users
    if request.user.is_authenticated:
        # Check if user is admin (superuser, staff, or Worker with ADM employee_id)
        is_admin = request.user.is_superuser or request.user.is_staff

        if not is_admin:
            if hasattr(request.user, 'worker_profile'):
                is_admin = request.user.worker_profile.employee_id.startswith('ADM')

        if is_admin:
            # Pending registration requests
            for reg in RegistrationRequest.objects.filter(status='pending').order_by('-created_at')[:5]:
                notifications_list.append({
                    'type': 'registration',
                    'id': reg.id,
                    'title': f'新注册申请: {reg.full_name}',
                    'description': f'{reg.department if reg.department != "其他" else reg.department_other} - {reg.phone}',
                    'url': '/admin/core/registrationrequest/',
                    'created_at': reg.created_at,
                })

            # Pending water requests
            for req in WaterRequest.objects.filter(status='submitted').order_by('-created_at')[:5]:
                notifications_list.append({
                    'type': 'water',
                    'id': req.id,
                    'title': f'浇水协调需求: {req.zone.name}',
                    'description': f'{req.get_request_type_display()} - {req.user_type}',
                    'url': f'/requests/water/{req.id}/',
                    'created_at': req.created_at,
                })

    return {
        'notifications_list': notifications_list,
        'notification_count': len(notifications_list),
    }