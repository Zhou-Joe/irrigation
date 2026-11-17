from django.conf import settings
from .access import active_membership, business_options
from .models import Location, Membership


def workspace(request):
    if not settings.MULTI_TEAM_ENABLED or not request.user.is_authenticated:
        return {}
    member=active_membership(request)
    from .administration import is_general, restricted_business
    platform_admin=is_general(request.user)
    pest=bool(member and member.team.business.code=='pest-control')
    landscaping=bool(member and member.team.business.code=='landscaping')
    data={'workspace_membership':member,'business_choices':business_options(request.user),
          'active_business_key':f'business:{member.team_id}' if member else '',
          'location_kind_choices':Location.KINDS,
          'pest_mode':pest,'landscaping_mode':landscaping,'is_platform_admin':platform_admin,'multi_team_enabled':True,
          'business_selected':member.team.business.code if member else ''}
    if platform_admin:
        data.update(account_role_label='超级管理员',user_role='super_admin')
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
                    account_role_label='超级管理员' if platform_admin else dict(Membership.display_role_choices('pest-control')).get(member.role,''),
                    pest_pending_task_count=task_count)
        if manager:
            from .administration import registrations
            data['pending_registrations']=registrations(request).filter(status='pending').count()
    elif landscaping:
        manager=platform_admin or member.role=='manager'
        data.update(is_admin=manager,is_manager=manager,is_field_worker=not manager and member.role=='field',
                    unread_notifications_data=[],pm_tasks_data=[],pending_registrations=0,
                    account_role_label='超级管理员' if platform_admin else dict(Membership.display_role_choices('landscaping')).get(member.role,''),
                    watermark_text=request.user.get_full_name() or request.user.username,
                    watermark_warning='仅限内部沟通，严禁外传')
    elif not member and not platform_admin:
        data.update(is_admin=False,is_manager=False,is_field_worker=False)
    elif not pest and getattr(request,'operations_shell',False):
        from .access import has_irrigation_access
        from core.role_utils import is_admin, is_field_worker
        manager=platform_admin or (has_irrigation_access(request.user) and is_admin(request.user))
        data.update(is_admin=manager,is_manager=manager,is_field_worker=is_field_worker(request.user),
            watermark_text=request.user.get_full_name() or request.user.username,
            watermark_warning='仅限内部沟通，严禁外传')
    limited=restricted_business(request.user)
    if limited:
        data.update(account_role_label=request.user.administrator_scope.business.name+'管理员',user_role='manager')
    elif platform_admin:
        data['account_role_label']='通用管理员'
    return data
