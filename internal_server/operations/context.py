from django.conf import settings
from .access import active_membership, memberships, admin_preview_role, preview_teams


def workspace(request):
    if not settings.MULTI_TEAM_ENABLED or not request.user.is_authenticated:
        return {}
    member = active_membership(request)
    preview = admin_preview_role(request)
    platform_admin = request.user.is_superuser
    pest = bool(member and member.team.business.code == 'pest-control')
    data = {'workspace_membership':member, 'workspace_choices':memberships(request.user).order_by('team__name'),
            'active_business_key':f'preview:{member.team_id}:{preview}' if preview else str(member.pk) if member else '',
            'pest_mode':pest, 'is_platform_admin':platform_admin, 'admin_role_preview':bool(preview),'multi_team_enabled':True}
    if platform_admin:
        groups=[]
        for team in preview_teams():
            prefix='灌溉' if team.business.code=='irrigation' else '植保'
            groups.append({'name':team.name,'choices':[
                {'value':f'{team.pk}:manager','label':prefix+'经理'},
                {'value':f'{team.pk}:field','label':prefix+'一线'}]})
        data.update(admin_view_groups=groups,
                    admin_view_selected=f'{member.team_id}:{preview}' if preview else 'admin',
                    account_role_label='平台管理员',user_role='super_admin')
    if preview:
        prefix='灌溉' if member.team.business.code=='irrigation' else '植保'
        data.update(is_admin=preview=='manager',is_manager=preview=='manager',is_field_worker=preview=='field',
                    is_dept_user=False,user_role='manager' if preview=='manager' else 'field_worker',
                    admin_view_label=prefix+('经理' if preview=='manager' else '一线'))
    if pest:
        data.update(is_admin=member.role=='manager' or (platform_admin and not preview),
                    is_manager=member.role=='manager', is_field_worker=member.role=='field',
                    unread_notifications_data=[], pm_tasks_data=[], pending_registrations=0,
                    watermark_text=request.user.get_full_name() or request.user.username,
                    watermark_warning='仅限内部沟通，严禁外传')
    elif not member and not platform_admin:
        data.update(is_admin=False,is_manager=False,is_field_worker=False)
    return data
