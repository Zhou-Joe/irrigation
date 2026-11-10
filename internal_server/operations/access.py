from django.core.exceptions import PermissionDenied
from django.conf import settings
from django.db.models import Q

from .models import Membership, Location, AuditEvent, Team


def business_teams():
    return Team.objects.filter(active=True,business__active=True).filter(
        Q(business__code='pest-control') |
        Q(business__code='irrigation',legacy_irrigation_access=True)).select_related('business').order_by('business__code','name')


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


def business_options(user):
    """Business selection never changes the account's role or permissions."""
    if not user or not user.is_authenticated or not user.is_active:
        return []
    teams=business_teams()
    if not user.is_superuser:
        teams=teams.filter(memberships__in=memberships(user))
    available=set(teams.values_list('business__code',flat=True))
    if not user.is_superuser and not has_irrigation_access(user):
        available.discard('irrigation')
    return [{'code':code,'label':label} for code,label in
            (('irrigation','灌溉'),('pest-control','植保')) if code in available]


def active_membership(request):
    if not hasattr(request, '_business_membership'):
        qs=memberships(request.user)
        business=request.session.get('operations_business') if settings.MULTI_TEAM_ENABLED else None
        # Existing sessions retain their selected business, never an impersonated role.
        legacy=request.session.get('operations_admin_view')
        if not business and settings.MULTI_TEAM_ENABLED and request.user.is_superuser and isinstance(legacy,dict):
            team_id=legacy.get('team')
            if type(team_id) is int:
                business=business_teams().filter(pk=team_id).values_list('business__code',flat=True).first()
        if business:
            if request.user.is_superuser:
                team=business_teams().filter(business__code=business).first()
                current=(qs.filter(team=team).first() or Membership(user=request.user,team=team,role='manager')) if team else None
            else:
                current=qs.filter(team__business__code=business).order_by('id').first()
        else:
            selected=request.session.get('operations_membership')
            if selected:
                current=qs.filter(pk=selected).first()
            else:
                current=(qs.filter(team__business__code='irrigation',team__legacy_irrigation_access=True).order_by('id').first()
                         or qs.order_by('team__name','id').first())
                if current is None and request.user.is_superuser:
                    team=business_teams().first()
                    if team:current=Membership(user=request.user,team=team,role='manager')
        # A revoked selection must not silently become authority in a different team.
        request._business_membership=current
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


def can_browse_location_catalog(member,user):
    return bool(member and (member.role=='manager' or user.is_superuser))


def browsable_locations(member,user):
    """Managers inspect location metadata; team grants still govern field use.

    This intentionally does not widen visible_locations(), which is also used by
    map/work-order adapters and must keep requiring the receiving team's grant.
    """
    if can_browse_location_catalog(member,user):
        return Location.objects.filter(owner_team__active=True,owner_team__business__active=True).select_related(
            'owner_team__business','legacy_zone')
    return visible_locations(member.team)


def can_manage_location(member, location, user):
    return location.owner_team_id == member.team_id and (member.role == 'manager' or user.is_superuser)


def audit(request, team, action, target, **detail):
    AuditEvent.objects.create(actor=request.user, team=team, action=action,
                              object_ref=str(target), detail=detail)
