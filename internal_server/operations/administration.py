"""Business administrator authority shared by navigation and management APIs."""
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.models import Q


def scope(user):
    from core.role_utils import get_django_user
    user=get_django_user(user)
    try:
        return user.administrator_scope
    except (AttributeError,):
        return None


def administrator(user):
    from core.role_utils import get_django_user
    user=get_django_user(user)
    if not user or not getattr(user,'is_authenticated',False) or not getattr(user,'is_active',False):
        return False
    from core.models import ManagerProfile
    return user.is_staff or user.is_superuser or ManagerProfile.objects.filter(user=user,active=True).exists()


def is_general(user):
    if not administrator(user):return False
    grant=scope(user)
    return grant.business_id is None if grant else bool(user.is_superuser or user.is_staff)


def can_administer(user,business):
    if not administrator(user):return False
    grant=scope(user)
    return is_general(user) or bool(grant and grant.business.code==business and grant.business.active)


def restricted_business(user):
    grant=scope(user)
    return grant.business.code if grant and grant.business_id else None


def management_team(request):
    """Null keeps legacy irrigation ownership; other businesses use an explicit team."""
    if not settings.MULTI_TEAM_ENABLED:return None
    from .access import active_membership
    member=active_membership(request)
    return member.team if member and member.team.business.code!='irrigation' else None


def can_manage(request):
    if not settings.MULTI_TEAM_ENABLED:return administrator(request.user)
    from .access import active_membership
    member=active_membership(request)
    return bool(member and (can_administer(request.user,member.team.business.code) or member.role=='manager'))


def require_management(request):
    if not can_manage(request):raise PermissionDenied('需要当前业务的管理员权限。')


def owned(model,request):
    return model.objects.filter(business_team=management_team(request))


def registration_business(reg):
    return reg.admin_business if reg.requested_role=='manager' else reg.worker_type if reg.requested_role=='field_worker' else 'irrigation'


def registrations(request):
    from core.models import RegistrationRequest
    if is_general(request.user):return RegistrationRequest.objects.all()
    team=management_team(request);business=team.business.code if team else 'irrigation'
    return RegistrationRequest.objects.filter(Q(requested_role='manager',admin_business=business)|
        Q(requested_role='field_worker',worker_type=business)|Q(requested_role='dept_user',worker_type=business))


def can_approve(user,registration):
    if not settings.MULTI_TEAM_ENABLED:return administrator(user)
    business=registration_business(registration)
    if is_general(user):return True
    if business=='general':return False
    if restricted_business(user) and restricted_business(user)!=business:return False
    if can_administer(user,business):return True
    from .access import memberships
    return memberships(user).filter(role='manager',team__business__code=business).exists()


def audience_users(request):
    from django.contrib.auth import get_user_model
    from .models import Membership
    qs=get_user_model().objects.all()
    team=management_team(request)
    if not settings.MULTI_TEAM_ENABLED:return qs
    if team:
        ids=Membership.objects.filter(team__business=team.business).values('user_id')
        return qs.filter(Q(pk__in=ids)|Q(administrator_scope__business=team.business)|Q(administrator_scope__business__isnull=True,
            administrator_scope__isnull=False)).filter(Q(administrator_scope__business__isnull=True)|Q(administrator_scope__business=team.business))
    ids=Membership.objects.filter(team__business__code='irrigation').values('user_id')
    legacy=qs.filter(team_memberships__isnull=True).filter(Q(worker_profile__worker_type='irrigation')|Q(manager_profile__isnull=False)|
                     Q(dept_profile__isnull=False)|Q(is_staff=True)|Q(is_superuser=True))
    return qs.filter(Q(pk__in=ids)|Q(pk__in=legacy.values('pk'))|Q(administrator_scope__business__code='irrigation')|
        Q(administrator_scope__business__isnull=True,administrator_scope__isnull=False)).filter(
        Q(administrator_scope__business__isnull=True)|Q(administrator_scope__business__code='irrigation'))


def editable_account(request,user):
    from core.role_utils import get_django_user
    actor=get_django_user(request.user)
    if is_general(request.user):return True
    if actor and user.pk==actor.pk:return True
    if administrator(user):return False
    from .access import active_membership
    member=active_membership(request)
    own=user.team_memberships.filter(team__business=member.team.business) if member and restricted_business(request.user) else user.team_memberships.filter(team=member.team) if member else user.team_memberships.none()
    return bool(member and own.exists() and
                not user.team_memberships.exclude(team__business=member.team.business).exists())


def user_rows(request,rows):
    from .models import Membership
    from .access import active_membership
    source=audience_users(request)
    people={user.pk:user for user in source.select_related('administrator_scope__business')}
    current=active_membership(request) if settings.MULTI_TEAM_ENABLED else None
    member_map={}
    if current:
        for member in Membership.objects.filter(team__business=current.team.business).select_related('team__business').order_by('active','pk'):
            member_map[member.user_id]=member
    # A person stays enabled while ANY business membership is active; only an
    # explicit disable (account or every membership) marks them inactive.
    enabled=set(Membership.objects.filter(active=True,team__active=True,team__business__active=True).values_list('user_id',flat=True))
    seen=set();result=[]
    for row in rows:
        identifier=row['user_id']
        if identifier and (identifier not in people or identifier in seen):continue
        if not identifier and management_team(request):continue
        if not identifier and row.get('profile_type')=='worker' and row.get('worker_type','irrigation')!='irrigation':continue
        if identifier:seen.add(identifier)
        user=people.get(identifier)
        if user:
            grant=scope(user)
            row.update(can_edit=editable_account(request,user),is_administrator=administrator(user),
                       admin_business=grant.business.code if grant and grant.business_id else 'general')
            if administrator(user):row['role_display']=grant.business.name+'管理员' if grant and grant.business_id else '通用管理员'
            elif user.pk in member_map:row['active']=row['active'] and (member_map[user.pk].active or user.pk in enabled)
        else:row['can_edit']=is_general(request.user)
        result.append(row)
    for user in people.values():
        if user.pk in seen:continue
        grant=scope(user);admin=administrator(user);member=member_map.get(user.pk)
        if not admin and not member:continue
        label=(grant.business.name+'管理员' if grant and grant.business_id else '通用管理员') if admin else dict(Membership.display_role_choices(member.team.business.code)).get(member.role,'成员')
        result.append(dict(profile_type='account',profile_id=user.pk,user_id=user.pk,username=user.username,
            full_name=user.get_full_name() or user.username,employee_id='',phone='',department='',role='manager' if admin else {'manager':'manager','field':'field_worker','viewer':'dept_user','requester':'dept_user'}[member.role],
            role_display=label,active=user.is_active and (admin or not member or member.active or user.pk in enabled),
            can_edit=editable_account(request,user),is_administrator=admin,admin_business=grant.business.code if grant and grant.business_id else 'general',drawn_zones=0))
    return sorted(result,key=lambda item:item['full_name'])
