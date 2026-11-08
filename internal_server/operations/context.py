from django.conf import settings
from .access import active_membership, memberships


def workspace(request):
    if not settings.MULTI_TEAM_ENABLED or not request.user.is_authenticated:
        return {}
    member = active_membership(request)
    pest = bool(member and member.team.business.code == 'pest-control')
    data = {'workspace_membership':member, 'workspace_choices':memberships(request.user).order_by('team__name'),
            'active_business_key':str(member.pk) if member else '', 'pest_mode':pest}
    if pest:
        data.update(is_admin=member.role=='manager' or request.user.is_superuser,
                    is_manager=member.role=='manager', is_field_worker=member.role=='field',
                    unread_notifications_data=[], pm_tasks_data=[], pending_registrations=0,
                    watermark_text=request.user.get_full_name() or request.user.username,
                    watermark_warning='仅限内部沟通，严禁外传')
    elif not member:
        data.update(is_admin=False,is_manager=False,is_field_worker=False)
    return data
