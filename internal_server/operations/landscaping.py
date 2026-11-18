"""Business-scoped landscaping pages; supplier import is a subsequent stage."""
import uuid
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from core.submissions import submission
from .access import require_member, visible_locations, audit
from .landscaping_forms import AssetForm, SpeciesForm, WorkOrderForm, DeliveryForm
from .map_data import location_map_data
from .models import LandscapingAsset as Asset, LandscapingSpecies as Species
from .models import LandscapingWorkOrder as WorkOrder, LandscapingDelivery as Delivery


def green_member(request, *, manager=False, write=False):
    member = require_member(request, manager=manager)
    if member.team.business.code != 'landscaping':
        raise PermissionDenied('此页面属于绿化业务。')
    if write and member.role not in ('manager', 'field'):
        raise PermissionDenied('当前身份只能查看绿化记录。')
    return member


def orders_for(request, member):
    qs = WorkOrder.objects.filter(team=member.team)
    if member.role != 'manager':
        qs = qs.filter(Q(assignee=request.user) | Q(created_by=request.user))
    return qs


def green_page(request, template, member, **context):
    return render(request, 'operations/landscaping/' + template + '.html', {
        'can_manage': member.role == 'manager', 'can_write': member.role in ('field', 'manager'),
        'membership': member, **context})


def paged(request, qs):
    params = request.GET.copy()
    params.pop('page', None)
    return {'records': Paginator(qs, 30).get_page(request.GET.get('page')), 'filter_query': params.urlencode()}


def asset_query(request, member):
    qs = Asset.objects.filter(team=member.team).prefetch_related('species')
    q = request.GET.get('q', '').strip()[:150]
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q) | Q(species__name__icontains=q)).distinct()
    if request.GET.get('kind') in dict(Asset.KINDS):
        qs = qs.filter(kind=request.GET['kind'])
    if request.GET.get('risk') in dict(Asset.RISKS):
        qs = qs.filter(risk=request.GET['risk'])
    if request.GET.get('special') == '1':
        qs = qs.filter(species__special=True).distinct()
    if request.GET.get('position') == 'missing':
        qs = qs.filter(Q(latitude=None) | Q(longitude=None))
    location = visible_locations(member.team).filter(pk=request.GET.get('location')).first() if valid_uuid(request.GET.get('location')) else None
    if location:
        qs = qs.filter(location=location)
    return qs


def valid_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


@login_required
@require_GET
def dashboard(request):
    member = green_member(request)
    from core.views import _unacked_announcements_for
    assets = Asset.objects.filter(team=member.team)
    return green_page(request, 'dashboard', member,
        announcements=_unacked_announcements_for(request.user, member.team),
        tree_count=assets.filter(kind='tree').count(), green_count=assets.exclude(kind='tree').count(),
        species_count=Species.objects.filter(team=member.team).count(),
        unpositioned=assets.filter(Q(latitude=None) | Q(longitude=None)).count(),
        high_risk=assets.filter(risk='high').count(),
        pending_count=orders_for(request, member).filter(status__in=['pending', 'in_progress', 'pending_review']).count(),
        upcoming=orders_for(request, member).exclude(status__in=['completed', 'cancelled']).order_by('scheduled_date', 'pk')[:5])


@login_required
@require_GET
def map_data(request):
    member = green_member(request)
    from .map_reference import map_labels
    places = [location_map_data(p) for p in visible_locations(member.team)]
    assets = [{'id': a.pk, 'code': a.code, 'name': a.name, 'kind': a.kind, 'kind_label': a.get_kind_display(),
               'risk': a.risk, 'risk_label': a.get_risk_display(),
               'center': [float(a.latitude), float(a.longitude)] if a.latitude is not None and a.longitude is not None else None,
               'url': reverse('operations:green_asset', args=[a.pk])}
              for a in asset_query(request, member)]
    response = JsonResponse({'business': 'landscaping', 'locations': places, 'assets': assets,
                             **map_labels()})
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@require_GET
def assets(request):
    member = green_member(request)
    result = paged(request, asset_query(request, member))
    names = dict(visible_locations(member.team).values_list('pk', 'name'))
    for obj in result['records']:
        obj.location_label = names.get(obj.location_id, '未关联区域' if not obj.location_id else '区域已不可见')
    return green_page(request, 'assets', member, **result, kinds=Asset.KINDS, risks=Asset.RISKS,
        places=visible_locations(member.team))


@login_required
@require_GET
def asset_detail(request, pk):
    member = green_member(request)
    asset = get_object_or_404(Asset.objects.prefetch_related('species'), team=member.team, pk=pk)
    place = visible_locations(member.team).filter(pk=asset.location_id).first()
    return green_page(request, 'asset', member, asset=asset, place=place,
                      workorders=orders_for(request, member).filter(assets=asset)[:10])


@login_required
@require_http_methods(['GET', 'POST'])
@submission('green.asset')
def asset_edit(request, pk=None):
    member = green_member(request, manager=True)
    obj = get_object_or_404(Asset, team=member.team, pk=pk) if pk else Asset(team=member.team)
    form = AssetForm(request.POST if request.method == 'POST' else None, instance=obj, team=member.team)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                form.save()
                audit(request, member.team, 'green.asset.save', obj.pk, code=obj.code)
            messages.success(request, '档案已保存。')
            return redirect('operations:green_asset', pk=obj.pk)
        except IntegrityError:
            form.add_error('code', '该档案编号已存在，请使用唯一编号。')
    return edit_page(request, member, form, '编辑档案' if pk else '新建树木 / 绿地档案', 'green_assets')


@login_required
@require_GET
def species(request):
    member = green_member(request)
    qs = Species.objects.filter(team=member.team)
    q = request.GET.get('q', '').strip()[:150]
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(scientific_name__icontains=q))
    if request.GET.get('special') == '1':
        qs = qs.filter(special=True)
    if request.GET.get('identification') in dict(Species.IDENTIFICATIONS):
        qs = qs.filter(identification=request.GET['identification'])
    return green_page(request, 'species', member, **paged(request, qs))


@login_required
@require_http_methods(['GET', 'POST'])
@submission('green.species')
def species_edit(request, pk=None):
    member = green_member(request, manager=True)
    obj = get_object_or_404(Species, team=member.team, pk=pk) if pk else Species(team=member.team)
    form = SpeciesForm(request.POST if request.method == 'POST' else None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                form.save()
                audit(request, member.team, 'green.species.save', obj.pk, code=obj.code)
            messages.success(request, '植物资料已保存。')
            return redirect('operations:green_species')
        except IntegrityError:
            form.add_error('code', '该植物编号已存在，请使用唯一编号。')
    return edit_page(request, member, form, '编辑植物资料' if pk else '新建植物资料', 'green_species')


@login_required
@require_GET
def workorders(request):
    member = green_member(request)
    qs = orders_for(request, member).select_related('assignee')
    period = request.GET.get('period', '30')
    if period != 'all':
        days = 365 if period == 'year' else 30
        qs = qs.filter(created_at__date__gte=timezone.localdate() - timedelta(days=days - 1))
    if request.GET.get('status') in dict(WorkOrder.STATUSES):
        qs = qs.filter(status=request.GET['status'])
    q = request.GET.get('q', '').strip()[:150]
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(instructions__icontains=q))
    return green_page(request, 'workorders', member, **paged(request, qs), statuses=WorkOrder.STATUSES, period=period)


@login_required
@require_http_methods(['GET', 'POST'])
@submission('green.workorder')
def workorder_new(request):
    member = green_member(request, write=True)
    obj = WorkOrder(team=member.team, created_by=request.user, scheduled_date=timezone.localdate())
    initial = {}
    if request.method == 'GET' and request.GET.get('asset', '').isdigit():
        asset = Asset.objects.filter(team=member.team, pk=request.GET['asset']).first()
        if asset:
            initial['assets'] = [asset.pk]
            if visible_locations(member.team).filter(pk=asset.location_id).exists():
                initial['location'] = asset.location_id
    form = WorkOrderForm(request.POST if request.method == 'POST' else None, instance=obj, member=member, initial=initial)
    if request.method == 'POST' and form.is_valid():
        from core.workorder_tree_views import weather_snapshot_at
        with transaction.atomic():
            obj = form.save(commit=False)
            if member.role != 'manager':
                obj.assignee = request.user
            obj.weather = weather_snapshot_at()
            obj.save()
            form.save_m2m()
            audit(request, member.team, 'green.workorder.create', obj.pk)
        messages.success(request, '养护工单已创建。')
        return redirect('operations:green_workorder', pk=obj.pk)
    return edit_page(request, member, form, '新建养护工单', 'green_workorders')


def order_actions(request, member, obj):
    manager = member.role == 'manager'
    actor = manager or (member.role == 'field' and (obj.assignee_id == request.user.pk or
                     (obj.assignee_id is None and obj.created_by_id == request.user.pk)))
    actions = []
    if actor and obj.status == 'pending':
        actions.append(('start', '开始处理'))
    if actor and obj.status == 'in_progress':
        actions.append(('submit', '提交复核'))
    if manager and obj.status == 'pending_review':
        actions.extend([('complete', '复核完成'), ('return', '退回处理')])
    if manager and obj.status in ('pending', 'in_progress', 'pending_review'):
        actions.append(('cancel', '取消工单'))
    return actions


@login_required
@require_GET
def workorder_detail(request, pk):
    member = green_member(request)
    obj = get_object_or_404(orders_for(request, member).select_related('assignee', 'created_by', 'reviewed_by').prefetch_related('assets'), pk=pk)
    weather = obj.weather.split(',', 1)
    return green_page(request, 'workorder', member, order=obj, actions=order_actions(request, member, obj),
        order_version=obj.updated_at.isoformat(),
        place=visible_locations(member.team).filter(pk=obj.location_id).first(),
        weather_desc=weather[0], weather_temp=weather[1].strip() if len(weather) > 1 else '',
        events=member.team.auditevent_set.filter(object_ref=str(obj.pk), action__startswith='green.workorder.').select_related('actor').order_by('created_at', 'pk'))


@login_required
@require_POST
def workorder_action(request, pk):
    member = green_member(request, write=True)
    with transaction.atomic():
        obj = get_object_or_404(orders_for(request, member).select_for_update(), pk=pk)
        action = request.POST.get('action')
        allowed = dict(order_actions(request, member, obj))
        if action not in allowed:
            raise PermissionDenied('当前身份或工单状态不能执行此操作。')
        if request.POST.get('version') != obj.updated_at.isoformat():
            messages.error(request, '工单已更新，请查看最新状态后再操作。')
            return redirect('operations:green_workorder', pk=pk)
        notes = request.POST.get('notes', '').strip()
        if len(notes) > 5000 or (action in ('submit', 'return', 'cancel') and not notes):
            messages.error(request, '请填写处理结果或退回 / 取消原因（最多 5000 字）。')
            return redirect('operations:green_workorder', pk=pk)
        before = obj.status
        obj.status = {'start': 'in_progress', 'submit': 'pending_review', 'complete': 'completed',
                      'return': 'in_progress', 'cancel': 'cancelled'}[action]
        if action == 'submit':
            obj.completion_notes = notes
        if action == 'complete':
            obj.reviewed_by = request.user
            obj.completed_at = timezone.now()
        obj.save()
        audit(request, member.team, 'green.workorder.' + action, obj.pk, before=before, after=obj.status, notes=notes)
    messages.success(request, '工单状态已更新。')
    return redirect('operations:green_workorder', pk=pk)


@login_required
@require_GET
def deliveries(request):
    member = green_member(request, manager=True)
    qs = Delivery.objects.filter(team=member.team)
    return green_page(request, 'deliveries', member, **paged(request, qs))


@login_required
@require_http_methods(['GET', 'POST'])
@submission('green.delivery')
def delivery_edit(request, pk=None):
    member = green_member(request, manager=True)
    obj = get_object_or_404(Delivery, team=member.team, pk=pk) if pk else Delivery(team=member.team, created_by=request.user)
    before = obj.status
    form = DeliveryForm(request.POST if request.method == 'POST' else None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            form.save()
            audit(request, member.team, 'green.delivery.save', obj.pk, before=before, after=obj.status, notes=obj.notes)
        messages.success(request, '交付台账已保存。登记不会自动导入植物数据。')
        return redirect('operations:green_deliveries')
    return edit_page(request, member, form, '编辑交付批次' if pk else '登记交付批次', 'green_deliveries')


def edit_page(request, member, form, title, back):
    return green_page(request, 'form', member, form=form, page_title=title, back_url=reverse('operations:' + back),
                      submission_key=request.POST.get('submission_key') or str(uuid.uuid4()))
