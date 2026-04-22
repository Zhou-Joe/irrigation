"""
Context processors for making data available to all templates.
"""
from .models import RegistrationRequest, WaterRequest
from .role_utils import get_user_role, is_admin, is_field_worker, is_dept_user


def notifications(request):
    """
    Provide notification data to all templates.
    """
    notifications_list = []

    # Only show notifications for authenticated admins
    if request.user.is_authenticated and is_admin(request.user):
        # Pending registration requests
        for reg in RegistrationRequest.objects.filter(status='pending').order_by('-created_at')[:5]:
            notifications_list.append({
                'type': 'registration',
                'id': reg.id,
                'title': f'新注册申请: {reg.full_name}',
                'description': f'{reg.get_requested_role_display()} - {reg.phone}',
                'url': '/registration-approval/',
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


def user_role(request):
    """Add user role information to template context."""
    if not request.user.is_authenticated:
        return {
            'is_admin': False,
            'is_manager': False,
            'is_field_worker': False,
            'is_dept_user': False,
            'user_role': None,
            'pending_registrations': 0,
        }

    user = request.user
    role = get_user_role(user)
    admin = is_admin(user)

    pending_reg = 0
    if admin:
        pending_reg = RegistrationRequest.objects.filter(status='pending').count()

    return {
        'is_admin': admin,
        'is_manager': role == 'manager',
        'is_field_worker': is_field_worker(user),
        'is_dept_user': is_dept_user(user),
        'user_role': role,
        'pending_registrations': pending_reg,
    }