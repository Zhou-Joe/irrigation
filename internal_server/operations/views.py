from .administration import is_general
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, IntegrityError
from django.db.models import Q, Count, Prefetch, F
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from django.views.decorators.debug import sensitive_post_parameters
from core.submissions import submission

from .access import (memberships, active_membership, require_member, visible_locations, business_options,
                     can_manage_location, audit, has_irrigation_access, browsable_locations,
                     can_browse_location_catalog)
from .forms import LocationForm
from .models import Team, Membership, Location, LocationGrant, ReferenceCatalog
from .map_data import location_map_data
from .location_filters import filter_values, matching_locations, positioned_ids, with_team_visibility


def number(value):
    try:
        return max(0, int(value or 0))
    except (ValueError, TypeError, OverflowError):
        return 0


def page(request, template, **context):
    member = active_membership(request)
    return render(request, 'operations/' + template + '.html', {
        'membership': member, 'memberships': memberships(request.user).order_by('team__name'),
        'can_manage': bool(member and (member.role == 'manager' or is_general(request.user))),
        'has_irrigation': has_irrigation_access(request.user), **context})


@login_required
@require_GET
def home(request):
    return redirect('core:dashboard')


@login_required
@require_POST
def switch(request):
    if 'business' in request.POST:
        business=request.POST.get('business','')
        if business not in ('irrigation','pest-control','landscaping'):
            return JsonResponse({'error':'业务视图无效。'},status=400)
        if business not in {item['code'] for item in business_options(request.user)}:
            raise PermissionDenied('当前账号无权访问该业务。')
        request.session['operations_business']=business
        request.session.pop('operations_admin_view',None)
        request.session.pop('operations_membership',None)
        request.__dict__.pop('_business_membership',None)
        member=active_membership(request)
        audit(request,member.team,'workspace.switch',member.team_id,business=business)
    elif 'membership' in request.POST:
        # Compatibility for already-open clients; only actual account memberships.
        member=get_object_or_404(memberships(request.user),pk=number(request.POST.get('membership')))
        request.session.pop('operations_admin_view',None)
        request.session.pop('operations_business',None)
        request.session['operations_membership']=member.pk
        audit(request,member.team,'workspace.switch',member.pk)
    else:
        return JsonResponse({'error':'请选择业务视图。'},status=400)
    return switch_response(request)


def switch_response(request):
    if request.headers.get('X-Requested-With')!='XMLHttpRequest':
        return redirect('core:dashboard')
    request.__dict__.pop('_business_membership',None)
    member=active_membership(request)
    return JsonResponse({'success':True,'business':member.team.business.code if member else 'irrigation'})


@login_required
@require_GET
def locations(request):
    member = require_member(request)
    catalog=request.GET.get('scope')=='catalog'
    can_catalog=can_browse_location_catalog(member,request.user)
    if catalog and not can_catalog:raise PermissionDenied('只有管理员或团队经理可以浏览其他团队区域。')
    visible = browsable_locations(member,request.user) if catalog else visible_locations(member.team)
    visible=with_team_visibility(visible,member.team)
    positioned=positioned_ids(visible)
    counts=visible.aggregate(total=Count('pk',distinct=True),
        owned=Count('pk',filter=Q(owner_team=member.team),distinct=True),
        shared=Count('pk',filter=~Q(owner_team=member.team),distinct=True),
        team_visible_count=Count('pk',filter=Q(is_team_visible=True),distinct=True))
    counts['team_visible']=counts.pop('team_visible_count')
    counts['hidden']=counts['total']-counts['team_visible']
    counts['positioned']=len(positioned)
    counts['unpositioned']=counts['total']-counts['positioned']
    qs = matching_locations(visible,member.team,request.GET,positioned=positioned)
    shareable_count=qs.exclude(owner_team=member.team).count() if catalog else qs.filter(owner_team=member.team).count()
    self_visibility_count=qs.exclude(owner_team=member.team).count()
    # A shared child does not imply access to its unshared parent's metadata.
    parents=browsable_locations(member,request.user)
    qs=qs.prefetch_related(Prefetch('parent',queryset=parents.select_related(None)), 'grants__team')
    from django.core.paginator import Paginator
    location_page=Paginator(qs,30).get_page(request.GET.get('page'))
    for location in location_page:
        location.visible_parent_name=location.parent.name if location.parent else ''
        location.has_map_position=location.pk in positioned
    return page(request, 'locations', locations=location_page,
                **filter_values(request.GET),counts=counts,location_kinds=Location.KINDS,shareable_count=shareable_count,
                is_location_catalog=catalog,selected_scope='catalog' if catalog else 'team',
                can_browse_catalog=can_catalog,self_visibility_count=self_visibility_count,
                source_teams=Team.objects.filter(active=True,business__active=True).select_related('business').order_by('name','pk'),
                other_teams=Team.objects.filter(active=True,business__active=True).exclude(pk=member.team_id))


@login_required
@require_GET
def location_detail(request, pk):
    member = require_member(request)
    places=with_team_visibility(browsable_locations(member,request.user),member.team)
    location = get_object_or_404(places, pk=pk)
    parent = (places.filter(pk=location.parent_id).first() if location.parent_id else None)
    manage = can_manage_location(member, location, request.user)
    grants = location.grants.select_related('team') if manage else []
    others = Team.objects.filter(active=True, business__active=True).exclude(pk=location.owner_team_id) if manage else []
    from .work_parameters import location_definitions, IMPACT_DIRECTION
    direction = next((field for field in location_definitions(location, available_locations=places)
                      if field['key'] == IMPACT_DIRECTION and field['type'] == 'choice'), None) if location.kind == 'building' else None
    return page(request, 'location_detail', location=location, parent=parent, manage=manage, grants=grants, other_teams=others,
        location_directions=direction['options'] if direction else [],
        is_team_visible=location.is_team_visible,
        can_browse_catalog=can_browse_location_catalog(member,request.user),
        selected_scope='catalog' if request.GET.get('scope')=='catalog' and can_browse_location_catalog(member,request.user) else 'team',
        can_curate_team_visibility=can_browse_location_catalog(member,request.user) and location.owner_team_id!=member.team_id)


@login_required
@require_http_methods(['GET', 'POST'])
def location_edit(request, pk=None):
    member = require_member(request, manager=True)
    instance = get_object_or_404(Location, pk=pk, owner_team=member.team) if pk else Location(owner_team=member.team)
    form = LocationForm(request.POST if request.method == 'POST' else None, instance=instance,
                        parents=visible_locations(member.team).exclude(pk=instance.pk))
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                # Explicit metadata edits belong to this team from now on;
                # automatic legacy-zone registry maintenance must not replace them.
                location_field_names={field.name for field in instance._meta.concrete_fields}
                if 'registry_generated' in location_field_names:instance.registry_generated=False
                location = form.save()
                audit(request, member.team, 'location.save', location.pk)
            if request.headers.get('X-Requested-With')=='XMLHttpRequest':
                return JsonResponse({'success':True,'message':'地点已保存。','location':location_map_data(location),
                                     'edit_url':f'/ops/locations/{location.pk}/edit/'})
            messages.success(request, '地点已保存。')
            return redirect('operations:location_detail', pk=location.pk)
        except IntegrityError:
            form.add_error('code', '本团队已有相同编号，请使用其他编号或留空。')
    if request.method=='POST' and request.headers.get('X-Requested-With')=='XMLHttpRequest':
        return JsonResponse({'success':False,'message':'；'.join(str(error) for errors in form.errors.values() for error in errors),
                             'errors':form.errors.get_json_data()},status=400)
    return page(request, 'location_form', form=form, location=instance)


@login_required
@require_POST
def location_delete(request, pk):
    member = require_member(request, manager=True)
    if request.POST.get('team') != str(member.team_id):
        return JsonResponse({'success':False,'message':'当前业务团队已变化，请重新打开区域管理。'},status=409)
    if request.POST.get('location') != str(pk):
        return JsonResponse({'success':False,'message':'地点编号不一致，请重新选择。'},status=400)
    return _delete_location(request, member, pk)


@submission('location-delete')
def _delete_location(request, member, pk):
    try:
        with transaction.atomic():
            places = Location.objects.filter(pk=pk, owner_team=member.team)
            # Reserve the SQLite write before checking references. Row locks
            # serialize the same operation on databases that support them.
            places.update(registry_generated=F('registry_generated'))
            location = get_object_or_404(places.select_for_update())
            if location.legacy_zone_id:
                return JsonResponse({'success':False,'message':'该地点关联灌溉原区域，请在灌溉区域管理中处理原区域。'},status=409)
            references = [('children','下级地点'),('pest_records','工单'),('pest_plans','作业计划'),('pest_tasks','任务')]
            blockers = [label for related, label in references if getattr(location, related).exists()]
            if blockers:
                related_names = '、'.join(blockers)
                return JsonResponse({'success':False,'message':f'该地点仍有关联的{related_names}，请先调整关联后再删除。'},status=409)
            name = location.name
            location.delete()
            audit(request, member.team, 'location.delete', pk, name=name)
    except ProtectedError:
        return JsonResponse({'success':False,'message':'该地点仍有关联记录，请刷新并处理关联后再删除。'},status=409)
    return JsonResponse({'success':True,'id':str(pk),'message':f'已删除地点「{name}」。','redirect_url':'/ops/locations/'})


@login_required
@require_POST
def sharing(request, pk):
    member = require_member(request, manager=True)
    location = get_object_or_404(Location, pk=pk, owner_team=member.team)
    target = get_object_or_404(Team, pk=number(request.POST.get('team')), active=True, business__active=True)
    if target.pk == member.team_id:
        raise PermissionDenied('所属团队无需额外共享。')
    action = request.POST.get('action')
    if action not in ('grant', 'revoke'):
        return JsonResponse({'error': '共享操作无效'}, status=400)
    with transaction.atomic():
        if action == 'grant':
            LocationGrant.objects.get_or_create(location=location, team=target, defaults={'created_by': request.user})
        else:
            LocationGrant.objects.filter(location=location, team=target).delete()
        audit(request, member.team, 'location.' + action, location.pk, target_team=target.pk)
    if request.headers.get('X-Requested-With')=='XMLHttpRequest':
        return JsonResponse({'success':True,'message':'共享设置已更新。'})
    return redirect('operations:location_detail', pk=pk)


@login_required
@require_GET
def location_geometry(request):
    member = require_member(request)
    result = []
    catalog=request.GET.get('scope')=='catalog'
    if catalog and not can_browse_location_catalog(member,request.user):
        raise PermissionDenied('只有管理员或团队经理可以浏览其他团队区域。')
    single=request.GET.get('location','')
    places=browsable_locations(member,request.user) if catalog or single else visible_locations(member.team)
    places=with_team_visibility(places,member.team)
    if single:
        import uuid
        try:places=places.filter(pk=uuid.UUID(single))
        except (ValueError,TypeError):return JsonResponse({'error':'地点编号无效。'},status=400)
        if not places.exists():return JsonResponse({'error':'地点不存在或当前账号无权查看。'},status=404)
    shared=request.GET.get('shared')=='1'
    if shared:places=places.exclude(owner_team=member.team)
    places=matching_locations(places,member.team,request.GET)
    for location in places:
        # Never include legacy remarks, work counts, worker details or histories.
        result.append({**location_map_data(location),'owner_team':location.owner_team.name,
            'owner_team_id':location.owner_team_id,'team_visible':location.is_team_visible,
            'can_select':bool(catalog and can_browse_location_catalog(member,request.user) and location.owner_team_id!=member.team_id),
            'can_edit':can_manage_location(member,location,request.user)})
    response = JsonResponse({'locations': result})
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@require_http_methods(['GET', 'POST'])
@sensitive_post_parameters('new_password')
def team(request):
    member = require_member(request, manager=True)
    team_id = request.POST.get('team') if request.method == 'POST' else request.GET.get('team')
    target_team = get_object_or_404(Team, pk=number(team_id)) if team_id else member.team
    if target_team.pk != member.team_id and not is_general(request.user):
        raise PermissionDenied('只能管理自己的团队。')
    if target_team.business_id!=member.team.business_id:
        raise PermissionDenied('请先切换至对应业务视图。')
    error = ''
    if request.method == 'POST':
        if request.POST.get('context_team',str(member.team_id))!=str(member.team_id):
            return JsonResponse({'success':False,'message':'业务视图已变化，请重新打开用户管理。'},status=409)
        role = request.POST.get('role', '')
        username = request.POST.get('username', '').strip()
        action = request.POST.get('action', 'save')
        if role not in dict(Membership.ROLES) or action not in ('save', 'disable'):
            error = '请选择有效的角色和操作。'
        elif role == 'manager' and not is_general(request.user):
            error = '管理员角色由超级管理员授予。'
        else:
            try:
                with transaction.atomic():
                    # Serialize manager removal checks within the team.
                    Team.objects.select_for_update().get(pk=target_team.pk)
                    user = get_user_model().objects.filter(username=username, is_active=True).first()
                    if user is None:
                        password = request.POST.get('new_password', '')
                        if get_user_model().objects.filter(username=username).exists():
                            raise ValidationError('此账号已停用，请由平台管理员处理。')
                        if action != 'save' or not password:
                            raise ValidationError('新增账号请设置初始密码；添加已有账号时无需填写密码。')
                        if target_team.business.code!='pest-control' and not is_general(request.user):
                            raise ValidationError('当前业务的新账号仍由平台管理员创建。')
                        if len(username)<3:raise ValidationError('用户名至少需要 3 个字符。')
                        user = get_user_model()(username=username,first_name=request.POST.get('full_name','').strip(),
                            email=request.POST.get('email','').strip())
                        user.full_clean(exclude=['password'])
                        from django.utils import translation
                        with translation.override('zh-hans'):
                            try:validate_password(password, user)
                            except ValidationError as invalid:raise ValidationError([str(message) for message in invalid.messages])
                        user.set_password(password)
                        user.save()
                    existing = Membership.objects.filter(user=user, team=target_team).first()
                    if existing and existing.role == 'manager' and not is_general(request.user):
                        raise ValidationError('管理员身份的变更由超级管理员处理。')
                    if user.pk == request.user.pk and action == 'disable':
                        raise ValidationError('不能在这里停用自己的团队身份。')
                    if existing and existing.active and existing.role=='manager' and (action=='disable' or role!='manager'):
                        if not Membership.objects.filter(team=target_team,role='manager',active=True,user__is_active=True).exclude(pk=existing.pk).exists():
                            raise ValidationError('请先安排另一位管理员，再调整当前管理员身份。')
                    obj, _ = Membership.objects.update_or_create(user=user, team=target_team,
                                                                defaults={'role': role, 'active': action == 'save'})
                    audit(request, target_team, 'membership.' + action, obj.pk, role=role)
                if request.headers.get('X-Requested-With')=='XMLHttpRequest':
                    return JsonResponse({'success':True,'message':'团队成员已更新，其他团队的身份保持不变。','refresh':True})
                messages.success(request, '团队成员身份已更新。')
                return redirect(request.path + '?team=' + str(target_team.pk))
            except (ValidationError, IntegrityError) as exc:
                error = '；'.join(exc.messages) if isinstance(exc, ValidationError) else '账号或成员身份已存在，请刷新后重试。'
        if request.headers.get('X-Requested-With')=='XMLHttpRequest':
            return JsonResponse({'success':False,'message':error},status=400)
    from django.core.paginator import Paginator
    from django.db.models import Count
    from .models import AuditEvent
    from .management_views import render_page
    qs=Membership.objects.filter(team=target_team).select_related('user','team__business').order_by('-active','user__username')
    counts=qs.aggregate(total=Count('pk'),enabled_count=Count('pk',filter=Q(active=True,user__is_active=True)),
        managers=Count('pk',filter=Q(role='manager',active=True)),field=Count('pk',filter=Q(role='field',active=True)))
    counts['active']=counts.pop('enabled_count')
    query=request.GET.get('q','').strip()[:150]
    if query:qs=qs.filter(Q(user__username__icontains=query)|Q(user__first_name__icontains=query)|Q(user__email__icontains=query))
    role_filter=request.GET.get('role','')
    if role_filter in dict(Membership.ROLES):qs=qs.filter(role=role_filter)
    context={'membership':member,'can_manage':True,'managed_team':target_team,'error':error,
        'team_members':Paginator(qs,30).get_page(request.GET.get('page')),'counts':counts,'query':query,
        'selected_role':role_filter,'roles':Membership.display_role_choices(target_team.business.code),
        'role_labels':dict(Membership.display_role_choices(target_team.business.code)),
        'all_teams':Team.objects.filter(active=True,business=member.team.business) if is_general(request.user) else [],
        'audit_events':AuditEvent.objects.filter(team=target_team).select_related('actor').order_by('-pk')[:50]}
    return render_page(request,'operations/team.html',context,'operations/_team_results.html')


@login_required
@require_GET
def catalog(request):
    member = require_member(request)
    if member.team.business.code=='pest-control':
        from .management_views import business_data
        return business_data(request)
    current = ReferenceCatalog.objects.filter(business=member.team.business).order_by('-imported_at', '-id').first()
    roots = []
    if current:
        nodes = list(current.nodes.all())
        by_id = {node.pk: {'node': node, 'children': []} for node in nodes}
        for node in nodes:
            item = by_id[node.pk]
            if node.parent_id:
                by_id[node.parent_id]['children'].append(item)
            else:
                roots.append(item)
    return page(request, 'catalog', catalog=current, roots=roots)
