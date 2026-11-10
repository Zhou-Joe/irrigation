from django.conf import settings
from .access import active_membership, business_options


def workspace(request):
    if not settings.MULTI_TEAM_ENABLED or not request.user.is_authenticated:
        return {}
    member=active_membership(request)
    platform_admin=request.user.is_superuser
    pest=bool(member and member.team.business.code=='pest-control')
    data={'workspace_membership':member,'business_choices':business_options(request.user),
          'active_business_key':f'business:{member.team_id}' if member else '',
          'pest_mode':pest,'is_platform_admin':platform_admin,'multi_team_enabled':True,
          'business_selected':member.team.business.code if member else ''}
    if platform_admin:
        data.update(account_role_label='平台管理员',user_role='super_admin')
    if pest:
        manager=platform_admin or member.role=='manager'
        from .navigation import pest_modules
        from .planning import task_scope
        from django.utils import timezone
        task_count=task_scope(request,member).filter(status='pending',scheduled_date__lte=timezone.localdate()).count()
        data.update(is_admin=manager,is_manager=manager,is_field_worker=not manager and member.role=='field',
                    unread_notifications_data=[],pm_tasks_data=[],pending_registrations=0,
                    watermark_text=request.user.get_full_name() or request.user.username,
                    watermark_warning='仅限内部沟通，严禁外传',pest_navigation=pest_modules(manager),
                    account_role_label='平台管理员' if platform_admin else '植保'+dict(member.ROLES).get(member.role,''),
                    pest_pending_task_count=task_count)
    elif not member and not platform_admin:
        data.update(is_admin=False,is_manager=False,is_field_worker=False)
    elif not pest and getattr(request,'operations_shell',False):
        from .access import has_irrigation_access
        from core.role_utils import is_admin, is_field_worker
        manager=platform_admin or (has_irrigation_access(request.user) and is_admin(request.user))
        data.update(is_admin=manager,is_manager=manager,is_field_worker=is_field_worker(request.user),
            watermark_text=request.user.get_full_name() or request.user.username,
            watermark_warning='仅限内部沟通，严禁外传')
    return data
