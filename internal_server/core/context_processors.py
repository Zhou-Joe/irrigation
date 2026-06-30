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
                'url': '/user-management/?tab=approval',
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
            'watermark_text': '',
            'watermark_warning': '',
        }

    user = request.user
    role = get_user_role(user)
    admin = is_admin(user)

    pending_reg = 0
    if admin:
        pending_reg = RegistrationRequest.objects.filter(status='pending').count()

    # Watermark text for anti-leak: 姓名 + 手机号 + 部门 + 警示文字.
    # Per 甲方要求 the warning "仅限内部沟通，严禁外传" is appended so a leaked
    # screenshot carries both the culprit's identity and an explicit non-disclosure
    # notice. The canonical name/phone/department live on a linked profile (one of
    # worker / manager / dept), not on the auth User itself, so pick whichever
    # profile this user has. Falls back to display name / username when fields are
    # unset. Note: ManagerProfile has no department field (it IS management), so
    # only Worker / DepartmentUserProfile contribute a department segment.
    wm_name = user.get_full_name() or user.username
    wm_parts = [wm_name]
    profile = (getattr(user, 'worker_profile', None)
               or getattr(user, 'manager_profile', None)
               or getattr(user, 'dept_profile', None))
    if profile:
        if profile.full_name:
            wm_parts[0] = profile.full_name
        if profile.phone:
            wm_parts.append(profile.phone)
        # Department — only Worker/DepartmentUserProfile carry this; both expose
        # get_department_display_name(). ManagerProfile has no such attribute.
        dept_fn = getattr(profile, 'get_department_display_name', None)
        if callable(dept_fn):
            dept = dept_fn()
            if dept:
                wm_parts.append(dept)
    watermark_text = ' · '.join(p for p in wm_parts if p)
    # Warning notice (甲方要求) — rendered as a second line under the identity
    # text so a leaked screenshot carries both the culprit's identity and an
    # explicit non-disclosure notice. Kept as a separate variable so the SVG
    # tile can place it on its own line for readability.
    watermark_warning = '仅限内部沟通，严禁外传' if watermark_text else ''

    return {
        'is_admin': admin,
        'is_manager': role == 'manager',
        'is_field_worker': is_field_worker(user),
        'is_dept_user': is_dept_user(user),
        'user_role': role,
        'pending_registrations': pending_reg,
        'watermark_text': watermark_text,
        'watermark_warning': watermark_warning,
    }