from django.core.exceptions import PermissionDenied
from django.db.models import Q

from .models import Membership, Location, AuditEvent


def memberships(user):
    if not user or not user.is_authenticated or not user.is_active:
        return Membership.objects.none()
    return Membership.objects.filter(user=user, active=True, team__active=True,
                                     team__business__active=True).select_related('team__business')


def has_irrigation_access(user):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    # The legacy application has global roles. Only the explicitly designated
    # legacy workspace and a matching role can use that compatibility boundary.
    from core.role_utils import get_user_role
    mapped = {'manager': 'manager', 'super_admin': 'manager', 'field_worker': 'field', 'dept_user': 'requester'}
    role = mapped.get(get_user_role(user))
    return bool(role and memberships(user).filter(team__business__code='irrigation',
               team__legacy_irrigation_access=True, role=role).exists())


def active_membership(request):
    if not hasattr(request, '_business_membership'):
        selected = request.session.get('operations_membership')
        qs = memberships(request.user)
        if selected:
            current = qs.filter(pk=selected).first()
        else:
            # Adding another team must not change an existing irrigation user's
            # initial workspace because of alphabetical team-name ordering.
            current = (qs.filter(team__business__code='irrigation',team__legacy_irrigation_access=True).order_by('id').first()
                       or qs.order_by('team__name','id').first())
        # A revoked selection must not silently become authority in a different team.
        request._business_membership = current
    return request._business_membership


def require_member(request, *, manager=False):
    member = active_membership(request)
    if not member:
        raise PermissionDenied('请先选择有效的团队成员身份。')
    if manager and member.role != 'manager' and not request.user.is_superuser:
        raise PermissionDenied('此操作需要当前团队的经理权限。')
    return member


def visible_locations(team):
    return Location.objects.filter(Q(owner_team=team) | Q(grants__team=team)).select_related(
        'owner_team__business', 'legacy_zone').distinct()


def can_manage_location(member, location, user):
    return location.owner_team_id == member.team_id and (member.role == 'manager' or user.is_superuser)


def audit(request, team, action, target, **detail):
    AuditEvent.objects.create(actor=request.user, team=team, action=action,
                              object_ref=str(target), detail=detail)
