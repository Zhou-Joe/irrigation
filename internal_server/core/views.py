import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Avg, Sum
from django.db.models.functions import Coalesce
from django.views.decorators.http import require_POST
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from core.models import Zone


def auto_close_boundary_points(boundary_data):
    """
    Auto-close incomplete polygons in boundary data.

    If a user defines points but doesn't click "完成当前区域" before saving,
    this function will automatically close the polygon by adding the first point
    at the end if it has at least 3 points but isn't explicitly closed.

    Args:
        boundary_data: List of polygons, each polygon is a list of {lat, lng} points.
                       Format: [[{lat, lng}, ...], [{lat, lng}, ...]]

    Returns:
        List of properly closed polygons with at least 3 points each.
    """
    if not boundary_data or not isinstance(boundary_data, list):
        return []

    result = []
    for polygon in boundary_data:
        if not polygon or not isinstance(polygon, list):
            continue

        # Convert to list of dicts if points are in [lat, lng] array format
        points = []
        for p in polygon:
            if isinstance(p, dict) and 'lat' in p and 'lng' in p:
                points.append({'lat': float(p['lat']), 'lng': float(p['lng'])})
            elif isinstance(p, (list, tuple)) and len(p) >= 2:
                points.append({'lat': float(p[0]), 'lng': float(p[1])})

        # Skip if less than 3 points - cannot form a polygon
        if len(points) < 3:
            continue

        # Check if polygon is already closed (first point == last point)
        first_point = points[0]
        last_point = points[-1]

        is_closed = (
            abs(first_point['lat'] - last_point['lat']) < 0.000001 and
            abs(first_point['lng'] - last_point['lng']) < 0.000001
        )

        if not is_closed:
            # Auto-close by appending the first point
            points.append({'lat': first_point['lat'], 'lng': first_point['lng']})

        result.append(points)

    return result


def _wants_json(request):
    """Return JSON for async form saves while preserving normal HTML fallback."""
    return (
        request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('accept', '')
    )


def _parse_float(val):
    if not val:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _get_zone_dropdown_options():
    """Get distinct values from DB for zone dropdown fields."""
    from .models import Zone
    opts = {}
    for field in ['plant_type', 'sprinkler_type', 'soil_moisture', 'terrain_feature']:
        vals = Zone.objects.exclude(**{field: ''}).exclude(**{field: None}) \
                   .values_list(field, flat=True).distinct().order_by(field)
        opts[field] = list(vals)
    # Foreman candidates: distinct names already used + manager/dept user names
    from .models import ManagerProfile, DepartmentUserProfile
    from django.contrib.auth.models import User
    foreman_names = set()
    for field in ['irrigation_foreman', 'greenery_foreman', 'pest_control_foreman']:
        foreman_names.update(
            Zone.objects.exclude(**{field: ''}).exclude(**{field: None})
            .values_list(field, flat=True)
        )
    foreman_names.update(
        ManagerProfile.objects.filter(active=True).values_list('full_name', flat=True)
    )
    foreman_names.update(
        DepartmentUserProfile.objects.filter(active=True).values_list('full_name', flat=True)
    )
    # Also add user first_names (non-superuser, non-staff)
    for u in User.objects.filter(is_superuser=False):
        name = u.first_name or u.username
        if name:
            foreman_names.add(name)
    opts['foreman_names'] = sorted(foreman_names)
    return opts


def _zone_save_response(request, zone, message, created=False):
    if _wants_json(request):
        resp = {
            'success': True,
            'message': message,
            'created': created,
            'zone_id': zone.id,
            'zone_name': zone.name,
            'edit_url': reverse('core:zone_edit', args=[zone.id]),
        }
        # Return parsed notes for editor reload
        for field in ('equipment_maintenance_notes', 'irrigation_management_notes'):
            raw = getattr(zone, field, '') or ''
            try:
                parsed = json.loads(raw) if raw else []
                resp[field] = parsed
                resp[field + '_count'] = len(parsed)
            except (json.JSONDecodeError, TypeError):
                resp[field] = []
                resp[field + '_count'] = 0
        resp['boundary_count'] = len(zone.boundary_points) if zone.boundary_points else 0
        resp['area_display'] = zone.area_display
        resp['plant_count'] = zone.plants.count()
        resp['equipment_count'] = zone.equipments.count()
        return JsonResponse(resp)

    messages.success(request, message)
    return redirect('core:zone_edit', zone_id=zone.id)


def _build_grouped_zones(zones_qs=None, group_by='patch'):
    """Build grouped structure for template rendering.

    group_by='patch': Groups zones by their Patch FK.
    group_by='priority': Groups zones by priority level.
    Returns a list of dicts: {id, name, code, type, zone_count, zones: [{...}]}
    """
    from core.models import Patch

    if zones_qs is None:
        zones_qs = Zone.objects.all().order_by('code')

    zones_data = []
    for z in zones_qs:
        zones_data.append({
            'id': z.id,
            'name': z.name,
            'code': z.code,
            'description': z.description or '',
            'patch_id': z.patch_id,
            'patch_name': z.patch.name if z.patch else None,
            'patch_code': z.patch.code if z.patch else None,
            'boundary_points': z.active_boundary_points,
            'boundary_color': z.boundary_color,
            'priority': z.priority,
            'priority_display': z.get_priority_display(),
            'current_status': z.current_status,
            'sprinkler_type': z.sprinkler_type,
            'irrigation_intensity': z.irrigation_intensity,
            'solenoid_valve_size': z.solenoid_valve_size,
            'landscape_coefficient': z.landscape_coefficient,
            'plant_type': z.plant_type,
            'irrigation_foreman': z.irrigation_foreman,
            'greenery_zone': z.greenery_zone,
            'greenery_foreman': z.greenery_foreman,
            'pest_control_zone': z.pest_control_zone,
            'pest_control_foreman': z.pest_control_foreman,
            'terrain_feature': z.terrain_feature,
            'plant_feature': z.plant_feature,
            'soil_moisture': z.soil_moisture,
            'equipment_maintenance_notes': z.equipment_maintenance_notes,
            'irrigation_management_notes': z.irrigation_management_notes,
            'has_remarks': bool(z.remarks and json.loads(z.remarks)) if z.remarks else False,
            'has_confirmed_remarks': bool(z.confirmed_remarks and json.loads(z.confirmed_remarks)) if z.confirmed_remarks else False,
            'plant_names': list(z.plants.values_list('name', flat=True)),
        })

    if group_by == 'priority':
        priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'abolished': 4}
        groups = {}
        for z in zones_data:
            p = z['priority']
            groups.setdefault(p, []).append(z)
        grouped = []
        for pkey in sorted(groups.keys(), key=lambda k: priority_order.get(k, 99)):
            grouped.append({
                'type': 'priority',
                'id': pkey,
                'name': groups[pkey][0]['priority_display'],
                'code': pkey,
                'type_display': '优先级',
                'zones': groups[pkey],
                'zone_count': len(groups[pkey]),
            })
        return grouped

    # Default: group by patch_id
    groups = {}
    orphans = []
    for z in zones_data:
        if z['patch_id'] is not None:
            groups.setdefault(z['patch_id'], []).append(z)
        else:
            orphans.append(z)

    grouped = []
    for patch_id, zones in sorted(groups.items()):
        grouped.append({
            'id': patch_id,
            'name': zones[0]['patch_name'],
            'code': zones[0]['patch_code'],
            'zones': zones,
            'zone_count': len(zones),
        })

    if orphans:
        grouped.append({
            'name': '未分配片区',
            'zones': orphans,
            'zone_count': len(orphans),
        })

    return grouped


def _get_reference_map_data(exclude_zone_id=None, exclude_pipeline_id=None):
    """Build JSON data for rendering existing zones and pipelines as reference layers on edit maps."""
    from core.models import Pipeline

    ref_zones = []
    for z in Zone.objects.all():
        if exclude_zone_id and z.id == exclude_zone_id:
            continue
        if z.active_boundary_points:
            ref_zones.append({
                'id': z.id, 'name': z.name, 'code': z.code,
                'boundary_points': z.active_boundary_points,
                'boundary_color': z.boundary_color or '#52B788',
                'smooth_override': z.smooth_override,
                'ring_display_modes': z.ring_display_modes or {},
            })

    ref_pipelines = []
    for p in Pipeline.objects.all():
        if exclude_pipeline_id and p.id == exclude_pipeline_id:
            continue
        if p.line_points and len(p.line_points) >= 2:
            ref_pipelines.append({
                'id': p.id, 'name': p.name, 'code': p.code,
                'pipeline_type': p.pipeline_type,
                'line_points': p.line_points,
                'line_color': p.line_color,
                'line_weight': p.line_weight,
            })

    return json.dumps(ref_zones), json.dumps(ref_pipelines)


def _auto_pipeline_name_code(zone_ids, pipeline_type):
    """Generate unique pipeline name and code from zone IDs and type."""
    from .models import Pipeline

    type_label = '灌溉水管' if pipeline_type == 'irrigation' else '冲洗水管'
    type_prefix = 'IRR' if pipeline_type == 'irrigation' else 'FLU'

    zones = Zone.objects.filter(id__in=zone_ids).order_by('code')
    zone_names = list(zones.values_list('name', flat=True))
    zone_codes = list(zones.values_list('code', flat=True))

    if not zone_names:
        return '', ''

    base_name = '、'.join(zone_names) + ' - ' + type_label
    base_code = type_prefix + '-' + '-'.join(zone_codes)

    # Ensure uniqueness
    name, code = base_name, base_code
    suffix = 2
    while Pipeline.objects.filter(code=code).exists():
        name = f"{base_name} ({suffix})"
        code = f"{base_code}-{suffix}"
        suffix += 1

    return name, code


from django.views.decorators.csrf import ensure_csrf_cookie


@ensure_csrf_cookie
def user_login(request):
    """Login page for frontend with role-based redirect."""
    from .models import DepartmentUserProfile

    if request.user.is_authenticated:
        return redirect('core:dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)

            # Determine redirect based on role
            redirect_url = 'core:dashboard'

            # Check if dept user - redirect to requests page (water requests focus)
            try:
                DepartmentUserProfile.objects.get(user=user, active=True)
                redirect_url = 'core:requests'
            except DepartmentUserProfile.DoesNotExist:
                pass

            next_url = request.GET.get('next', redirect_url)
            return redirect(next_url)
        else:
            messages.error(request, '用户名或密码错误')

    return render(request, 'core/login.html')


def user_logout(request):
    """Logout view."""
    logout(request)
    return redirect('core:login')




@login_required(login_url='core:login')
def profile_page(request):
    """User profile page - view and edit personal information."""
    from core.models import Worker, ManagerProfile, DepartmentUserProfile

    user = request.user
    profile_data = {}
    profile_type = None

    # Priority: ManagerProfile > DepartmentUserProfile > Worker > System User
    # This ensures admin users show as managers even if they also have Worker records
    try:
        manager = ManagerProfile.objects.get(user=user, active=True)
        profile_type = 'manager'
        profile_data = {
            'type': '管理员',
            'employee_id': manager.employee_id,
            'full_name': manager.full_name,
            'phone': manager.phone,
            'api_token': str(manager.api_token),
            'is_super_admin': manager.is_super_admin,
            'can_approve_registrations': manager.can_approve_registrations,
            'can_approve_work_orders': manager.can_approve_work_orders,
        }
    except ManagerProfile.DoesNotExist:
        pass

    if not profile_type:
        try:
            dept_user = DepartmentUserProfile.objects.get(user=user, active=True)
            profile_type = 'dept_user'
            profile_data = {
                'type': '部门用户',
                'employee_id': dept_user.employee_id,
                'full_name': dept_user.full_name,
                'phone': dept_user.phone,
                'api_token': str(dept_user.api_token),
                'department': dept_user.get_department_display_name(),
            }
        except DepartmentUserProfile.DoesNotExist:
            pass

    if not profile_type:
        try:
            worker = Worker.objects.get(user=user, active=True)
            profile_type = 'worker'
            profile_data = {
                'type': '灌溉一线',
                'employee_id': worker.employee_id,
                'full_name': worker.full_name,
                'phone': worker.phone,
                'department': worker.get_department_display_name(),
                'api_token': str(worker.api_token),
            }
        except Worker.DoesNotExist:
            pass

    if not profile_type:
        profile_data = {
            'type': '系统用户',
            'username': user.username,
            'email': user.email,
        }

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'regenerate_token' and profile_type in ['worker', 'manager', 'dept_user']:
            try:
                if profile_type == 'worker':
                    profile = Worker.objects.get(user=user, active=True)
                elif profile_type == 'manager':
                    profile = ManagerProfile.objects.get(user=user, active=True)
                else:
                    profile = DepartmentUserProfile.objects.get(user=user, active=True)
                profile.regenerate_token()
                messages.success(request, 'API令牌已重新生成')
                return redirect('core:profile')
            except Exception:
                messages.error(request, '未找到用户档案')
        elif action == 'update_profile':
            phone = request.POST.get('phone', '').strip()
            full_name = request.POST.get('full_name', '').strip()
            employee_id = request.POST.get('employee_id', '').strip()
            email = request.POST.get('email', '').strip()

            # Update profile if exists
            if profile_type in ['worker', 'manager', 'dept_user']:
                try:
                    if profile_type == 'worker':
                        profile = Worker.objects.get(user=user, active=True)
                    elif profile_type == 'manager':
                        profile = ManagerProfile.objects.get(user=user, active=True)
                    else:
                        profile = DepartmentUserProfile.objects.get(user=user, active=True)

                    if full_name:
                        profile.full_name = full_name
                    if phone:
                        profile.phone = phone
                    if employee_id:
                        # Check uniqueness for employee_id
                        model_class = Worker if profile_type == 'worker' else (ManagerProfile if profile_type == 'manager' else DepartmentUserProfile)
                        if model_class.objects.filter(employee_id=employee_id).exclude(pk=profile.pk).exists():
                            messages.error(request, f'工号 {employee_id} 已被使用')
                        else:
                            profile.employee_id = employee_id
                    profile.save()
                except Exception as e:
                    messages.error(request, f'Profile更新失败: {str(e)}')

            # Update user email
            if email:
                user.email = email
                user.save()

            messages.success(request, '个人信息已更新')
            return redirect('core:profile')

    return render(request, 'core/profile.html', {
        'profile_data': profile_data,
        'profile_type': profile_type,
        'user': user,
    })


def get_zone_center(boundary_points):
    """Calculate the center point of a zone from its boundary points. Supports multi-polygon format."""
    if not boundary_points or len(boundary_points) == 0:
        return None

    lats = []
    lngs = []

    def _extract_coords(points):
        for point in points:
            if isinstance(point, list) and len(point) >= 2:
                lats.append(point[0])
                lngs.append(point[1])
            elif isinstance(point, dict) and 'lat' in point and 'lng' in point:
                lats.append(point['lat'])
                lngs.append(point['lng'])

    # Detect multi-polygon format: [[{lat,lng},...], [{lat,lng},...]]
    first = boundary_points[0]
    is_multi = isinstance(first, list) and len(first) > 0 and (
        isinstance(first[0], list) or (isinstance(first[0], dict) and 'lat' in first[0])
    )

    # Detect nested multi-group: [[[{lat,lng},...], ...], ...]
    is_nested = False
    if is_multi and isinstance(first, list) and len(first) > 0:
        inner = first[0]
        if isinstance(inner, list) and len(inner) > 0:
            innermost = inner[0]
            if isinstance(innermost, (list, dict)):
                is_nested = True

    if is_nested:
        # Flatten: [[ring1, ring2], [ring3]] → [ring1, ring2, ring3]
        for group in boundary_points:
            if isinstance(group, list):
                for ring in group:
                    _extract_coords(ring)
    elif is_multi:
        for ring in boundary_points:
            _extract_coords(ring)
    else:
        _extract_coords(boundary_points)

    if lats and lngs:
        return {
            'lat': round(sum(lats) / len(lats), 6),
            'lng': round(sum(lngs) / len(lngs), 6)
        }
    return None


def _safe_remark_items(raw):
    """Parse a zone remarks JSON string into a compact list for the dashboard.

    Returns a list of {date, content, author} (confirmed entries also keep their
    confirm_* fields). Empty/malformed → []. The dashboard hover tooltip renders
    these so users can read pending remarks without navigating to the zone page.
    """
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append({
            'date': it.get('date', ''),
            'content': it.get('content', '') or it.get('confirm_reply', ''),
            'author': it.get('author', '') or it.get('confirm_author', ''),
        })
    return out


def _cached(key, ttl, builder):
    """TTL cache wrapper with a safe fallback.

    Uses the framework cache when a real backend is configured; if the backend
    is DummyCache (or unset) the builder just runs every call — still correct,
    only slower. ``builder`` may return None legitimately; we cache a sentinel.
    """
    from django.core.cache import caches
    try:
        backend = caches['default']
        from django.core.cache.backends.dummy import DummyCache
        if isinstance(backend, DummyCache):
            return builder()
    except Exception:
        return builder()
    from django.core.cache import cache
    sentinel = object()
    val = cache.get(key, sentinel)
    if val is sentinel:
        val = builder()
        try:
            cache.set(key, val, ttl)
        except Exception:
            pass
    return val


@login_required(login_url='core:login')
def dashboard(request):
    """
    Main dashboard view with interactive map showing irrigation zones.
    """
    from datetime import date, timedelta
    from django.db.models.functions import TruncDate
    from core.models import (
        MaintenanceRequest, ProjectSupportRequest, WaterRequest,
        ManagerProfile, DepartmentUserProfile, RegistrationRequest, WorkOrder, Worker,
        Pipeline, Plant, MapStyleSettings, ZoneEquipment, WorkReport,
    )

    user = request.user
    today = date.today()
    week_ago = today - timedelta(days=7)

    # Determine user role
    is_admin = user.is_superuser or user.is_staff
    is_manager = False
    is_dept_user = False
    is_field_worker = False

    if not is_admin:
        try:
            ManagerProfile.objects.get(user=user, active=True)
            is_manager = True
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        try:
            DepartmentUserProfile.objects.get(user=user, active=True)
            is_dept_user = True
        except DepartmentUserProfile.DoesNotExist:
            pass

    if not is_admin and not is_dept_user:
        try:
            Worker.objects.get(user=user, active=True)
            is_field_worker = True
        except Worker.DoesNotExist:
            pass

    # Get all zones with annotations and related objects in minimal queries
    from django.db.models import Sum

    thirty_days_ago = today - timedelta(days=30)

    # Base zone queryset: select_related for patch/region, .only() the fields we
    # actually serialize to the client. Counts are computed via separate group-by
    # queries below to avoid the expensive Count(distinct=True) cross-product that
    # a single mega-annotated query produced on 2500+ zones.
    zones = (Zone.objects.select_related('patch', 'patch__region', 'land')
             .only('id', 'code', 'name', 'description', 'boundary_points',
                   'dxf_boundary_points', 'boundary_source', 'boundary_color',
                   'current_status', 'priority', 'remarks', 'confirmed_remarks',
                   'sprinkler_type', 'irrigation_intensity', 'solenoid_valve_size',
                   'landscape_coefficient', 'plant_type', 'irrigation_foreman',
                   'greenery_zone', 'greenery_foreman', 'pest_control_zone',
                   'pest_control_foreman', 'terrain_feature', 'plant_feature',
                   'soil_moisture', 'equipment_maintenance_notes',
                   'irrigation_management_notes', 'label_lat', 'label_lng',
                   'label_scale', 'label_angle', 'smooth_override',
                   'ring_display_modes', 'area_sqm',
                   'patch__id', 'patch__name', 'patch__code',
                   'patch__region__id', 'patch__region__name',
                   'land__id', 'land__name'))

    zone_ids = list(zones.values_list('id', flat=True))

    # Group-by counts (one query each, no distinct=True cross-product).
    def _count_map(model, label, **filters):
        out = {}
        qs = model.objects.filter(zone_id__in=zone_ids, **filters).values('zone_id')
        for row in qs.annotate(c=Count('id')):
            out[row['zone_id']] = row['c']
        return out

    plant_count_map = _count_map(Plant, 'plants')
    equipment_count_map = _count_map(ZoneEquipment, 'equipments')
    pending_work_map = _count_map(WorkOrder, 'work_orders', status='pending')
    maintenance_count_map = _count_map(MaintenanceRequest, 'maintenancerequest')
    water_count_map = _count_map(WaterRequest, 'waterrequest')
    project_count_map = _count_map(ProjectSupportRequest, 'projectsupportrequest')
    # recent_fault_count: sum of fault-entry counts over the last 30 days, per zone.
    fault_count_map = {}
    for row in (WorkReport.objects.filter(date__gte=thirty_days_ago, zones__in=zone_ids)
                .values('zones').annotate(s=Coalesce(Sum('fault_entries__count'), 0))):
        fault_count_map[row['zones']] = row['s']

    # ── Bulk: pending water requests for today ──
    pending_water_map = {}  # zone_id -> list of {id, type, type_display}
    for req in WaterRequest.objects.filter(
        zone_id__in=zone_ids,
        status='submitted',
        start_datetime__date__lte=today,
        end_datetime__date__gte=today
    ).values_list('zone_id', 'id'):
        pending_water_map.setdefault(req[0], []).append({
            'id': req[1], 'type': 'water', 'type_display': '浇水协调',
        })

    # ── Bulk: recent maintenance (last 7 days, top 3 per zone) ──
    from collections import defaultdict
    recent_maint_map = defaultdict(list)
    for m in MaintenanceRequest.objects.filter(
        zone_id__in=zone_ids, date__gte=week_ago
    ).order_by('zone_id', '-date'):
        lst = recent_maint_map[m.zone_id]
        if len(lst) < 3:
            lst.append({
                'id': m.id,
                'date': m.date.strftime('%Y-%m-%d'),
                'status': m.status,
                'status_display': m.get_status_display(),
                'work_content': m.work_content[:50] + '...' if len(m.work_content) > 50 else m.work_content,
            })

    # ── Bulk: recent water requests (top 3 per zone) ──
    recent_water_map = defaultdict(list)
    for w in WaterRequest.objects.filter(
        zone_id__in=zone_ids
    ).order_by('zone_id', '-created_at'):
        lst = recent_water_map[w.zone_id]
        if len(lst) < 3:
            lst.append({
                'id': w.id,
                'type': w.get_request_type_display(),
                'status': w.status,
                'status_display': w.get_status_display(),
                'start': w.start_datetime.strftime('%m-%d %H:%M'),
                'end': w.end_datetime.strftime('%m-%d %H:%M'),
            })

    # ── Bulk: recent project support (top 3 per zone) ──
    recent_proj_map = defaultdict(list)
    for p in ProjectSupportRequest.objects.filter(
        zone_id__in=zone_ids
    ).order_by('zone_id', '-created_at'):
        lst = recent_proj_map[p.zone_id]
        if len(lst) < 3:
            lst.append({
                'id': p.id,
                'date': p.date.strftime('%Y-%m-%d'),
                'status': p.status,
                'status_display': p.get_status_display(),
                'work_content': p.work_content[:50] + '...' if len(p.work_content) > 50 else p.work_content,
            })

    # ── Bulk: plant names per zone ──
    plant_names_map = defaultdict(list)
    for zone_id, name in Plant.objects.filter(
        zone_id__in=zone_ids
    ).values_list('zone_id', 'name'):
        plant_names_map[zone_id].append(name)

    # ── Build zones_list (no per-zone DB queries) ──
    zones_list = []
    for zone in zones:
        center = get_zone_center(zone.active_boundary_points)
        # Parse remarks TextFields once each (was 4× per zone: bool(json.loads) + _safe_remark_items).
        zone_remarks = _safe_remark_items(zone.remarks)
        zone_confirmed = _safe_remark_items(zone.confirmed_remarks)
        zones_list.append({
            'id': zone.id,
            'code': zone.code,
            'name': zone.name,
            'description': zone.description,
            'boundary_points': zone.active_boundary_points,
            'boundary_color': zone.boundary_color,
            'status': zone.get_today_status(),
            'statusDisplay': zone.get_status_display(),
            'plant_count': plant_count_map.get(zone.id, 0),
            'plant_names': plant_names_map.get(zone.id, []),
            'equipment_count': equipment_count_map.get(zone.id, 0),
            'pending_work_orders': pending_work_map.get(zone.id, 0),
            'recent_fault_count': fault_count_map.get(zone.id, 0),
            'center': center,
            'pending_requests': pending_water_map.get(zone.id, []),
            # Patch info
            'patch_id': zone.patch.id if zone.patch else None,
            'patch_name': zone.patch.name if zone.patch else None,
            'patch_code': zone.patch.code if zone.patch else None,
            # Region info
            'region_id': zone.patch.region_id if zone.patch and zone.patch.region else None,
            'region_name': zone.patch.region.name if zone.patch and zone.patch.region else None,
            # Land info (top-level grouping for sidebar)
            'land_id': zone.land.id if zone.land else None,
            'land_name': zone.land.name if zone.land else None,
            # Priority
            'priority': zone.priority,
            'priority_display': zone.get_priority_display(),
            # Zone attributes from Excel
            'current_status': zone.current_status,
            'sprinkler_type': zone.sprinkler_type,
            'irrigation_intensity': zone.irrigation_intensity,
            'solenoid_valve_size': zone.solenoid_valve_size,
            'landscape_coefficient': zone.landscape_coefficient,
            'plant_type': zone.plant_type,
            'irrigation_foreman': zone.irrigation_foreman,
            'greenery_zone': zone.greenery_zone,
            'greenery_foreman': zone.greenery_foreman,
            'pest_control_zone': zone.pest_control_zone,
            'pest_control_foreman': zone.pest_control_foreman,
            'terrain_feature': zone.terrain_feature,
            'plant_feature': zone.plant_feature,
            'soil_moisture': zone.soil_moisture,
            'equipment_maintenance_notes': zone.equipment_maintenance_notes,
            'irrigation_management_notes': zone.irrigation_management_notes,
            'has_remarks': bool(zone_remarks),
            'has_confirmed_remarks': bool(zone_confirmed),
            'remarks': zone_remarks,
            'confirmed_remarks': zone_confirmed,
            # Label settings
            'label_lat': zone.label_lat,
            'label_lng': zone.label_lng,
            'label_scale': zone.label_scale,
            'label_angle': zone.label_angle,
            'smooth_override': zone.smooth_override,
            'ring_display_modes': zone.ring_display_modes or {},
            'area_sqm': zone.area_sqm,
            'area_display': zone.area_display,
            # Counts (from group-by maps, not annotations)
            'maintenance_count': maintenance_count_map.get(zone.id, 0),
            'water_count': water_count_map.get(zone.id, 0),
            'project_count': project_count_map.get(zone.id, 0),
            # Recent items (from bulk queries)
            'recent_maintenance': recent_maint_map.get(zone.id, []),
            'recent_water': recent_water_map.get(zone.id, []),
            'recent_project': recent_proj_map.get(zone.id, []),
        })

    # Group zones by Land → common-name (zone.name) for sidebar display
    from .models import Land
    lands = Land.objects.filter(active=True).order_by('order', 'name')

    # Bucket zones by land_id
    land_buckets = {}
    orphan_zones = []
    for z in zones_list:
        lid = z.get('land_id')
        if lid is not None:
            land_buckets.setdefault(lid, []).append(z)
        else:
            orphan_zones.append(z)

    def _build_name_groups(zones):
        """Group zones by their common name (zone.name), preserving first-seen order."""
        order = []
        grouped = {}
        for z in zones:
            nm = z.get('name') or '(未命名)'
            if nm not in grouped:
                grouped[nm] = []
                order.append(nm)
            grouped[nm].append(z)
        result = []
        for nm in order:
            result.append({
                'name': nm,
                'zones': grouped[nm],
                'zone_count': len(grouped[nm]),
            })
        return result

    grouped_zones = []
    for land in lands:
        lz = land_buckets.pop(land.id, None)
        if lz:
            name_groups = _build_name_groups(lz)
            grouped_zones.append({
                'type': 'land',
                'id': land.id,
                'name': land.name,
                'name_groups': name_groups,
                'zone_count': len(lz),
            })

    # Zones whose Land is inactive / missing (land_id set but no active Land row)
    extra_orphan_zones = []
    for lid, lz in land_buckets.items():
        extra_orphan_zones.extend(lz)
    all_orphan = extra_orphan_zones + orphan_zones
    if all_orphan:
        grouped_zones.append({
            'type': 'orphan',
            'name': '未分配Land',
            'name_groups': _build_name_groups(all_orphan),
            'zone_count': len(all_orphan),
        })

    # Only admins see pending counts
    pending_counts = None
    if is_admin:
        pending_counts = {
            'registrations': RegistrationRequest.objects.filter(status='pending').count(),
            'work_orders': WorkOrder.objects.filter(status='pending').count(),
            'maintenance': MaintenanceRequest.objects.filter(status='submitted').count(),
            'project_support': ProjectSupportRequest.objects.filter(status='submitted').count(),
            'water': WaterRequest.objects.filter(status='submitted').count(),
        }

    # Dashboard statistics
    status_distribution = {
        'unarranged': sum(1 for z in zones_list if z['status'] == 'unarranged'),
        'in_progress': sum(1 for z in zones_list if z['status'] == 'in_progress'),
        'completed': sum(1 for z in zones_list if z['status'] == 'completed'),
        'canceled': sum(1 for z in zones_list if z['status'] == 'canceled'),
        'delayed': sum(1 for z in zones_list if z['status'] == 'delayed'),
    }

    # Recent activity (last 7 days)
    recent_activity = []
    for req in MaintenanceRequest.objects.select_related('zone').filter(created_at__date__gte=week_ago).order_by('-created_at')[:5]:
        recent_activity.append({
            'type': 'maintenance',
            'type_display': '维护维修',
            'zone': req.zone.name,
            'date': req.created_at.strftime('%m-%d %H:%M'),
            'status': req.get_status_display(),
        })
    for req in WaterRequest.objects.select_related('zone').filter(created_at__date__gte=week_ago).order_by('-created_at')[:5]:
        recent_activity.append({
            'type': 'water',
            'type_display': '浇水协调',
            'zone': req.zone.name,
            'date': req.created_at.strftime('%m-%d %H:%M'),
            'status': req.get_status_display(),
        })

    # Sort by date
    recent_activity.sort(key=lambda x: x['date'], reverse=True)
    recent_activity = recent_activity[:10]

    # Prepare pipelines data for map (prefetch zones to avoid N+1 per pipeline).
    # Pipelines rarely change — cache the built list for 5 min.
    pipelines_list = _cached('dashboard:pipelines', 300, lambda: [
        {
            'id': p.id, 'code': p.code, 'name': p.name,
            'pipeline_type': p.pipeline_type,
            'pipeline_type_display': p.get_pipeline_type_display(),
            'line_points': p.line_points, 'line_color': p.line_color,
            'line_weight': p.line_weight,
            'zone_names': [z.name for z in p.zones.all()],
        } for p in Pipeline.objects.prefetch_related('zones')
    ])

    all_plant_names = _cached('dashboard:plant_names', 300,
                              lambda: list(Plant.objects.values_list('name', flat=True).distinct().order_by('name')))

    # Landmark data for dashboard map and filter (rarely changes → cached 5 min).
    from .models import Landmark, ZoneLandmarkAssignment

    def _build_landmarks():
        lms = [{
            'id': lm.id, 'name': lm.name, 'boundary_points': lm.boundary_points,
            'boundary_color': lm.boundary_color, 'center': lm.center,
        } for lm in Landmark.objects.order_by('order', 'name')]
        zlm = {}
        for assignment in ZoneLandmarkAssignment.objects.select_related('landmark').all():
            zlm.setdefault(assignment.zone_id, []).append({
                'id': assignment.landmark_id, 'name': assignment.landmark.name,
            })
        return {'landmarks': lms, 'zone_landmark_map': zlm}

    _lm = _cached('dashboard:landmarks', 300, _build_landmarks)
    landmarks_data = _lm['landmarks']
    zone_landmark_map = _lm['zone_landmark_map']

    # Patch list for map filter plugin
    from .models import Patch
    patches_list = []
    for p in Patch.objects.order_by('code'):
        patches_list.append({
            'id': p.id,
            'name': p.name,
            'code': p.code,
        })

    # Land list for map filter plugin
    lands_list = []
    for l in Land.objects.filter(active=True).order_by('order', 'name'):
        lands_list.append({
            'id': l.id,
            'name': l.name,
        })

    context = {
        'zones_json': json.dumps(zones_list),
        'grouped_zones': grouped_zones,  # For hierarchical sidebar display
        'pipelines_json': json.dumps(pipelines_list),
        'all_plant_names': all_plant_names,
        'landmarks_json': json.dumps(landmarks_data),
        'landmark_names': [lm['name'] for lm in landmarks_data],
        'zone_landmark_map_json': json.dumps(zone_landmark_map),
        'patches_json': json.dumps(patches_list),
        'lands_json': json.dumps(lands_list),
        'is_admin': is_admin,
        'is_manager': is_manager,
        'is_dept_user': is_dept_user,
        'is_field_worker': is_field_worker,
        'pending_counts': pending_counts,
        'status_distribution': status_distribution,
        'recent_activity': recent_activity,
        'total_zones': len(zones_list),
        'total_plants': sum(z['plant_count'] for z in zones_list),
        'map_style_json': json.dumps(_cached('dashboard:map_style', 300, lambda: MapStyleSettings.get_style())),
    }

    return render(request, 'core/dashboard.html', context)


# ─── Zone Import / Export ───────────────────────────────────────────

# Excel headers matching Zone list V0.xlsx column order
_ZONE_EXPORT_HEADERS = [
    '编号', '位置重要程度', '所属Land', '通用名称', '灌溉管理用的位置',
    '当前状态', '灌水器类型', '灌溉强度 mm/h', '区域面积',
    '灌溉分区', 'CCU编号', '电磁阀尺寸', '景观系数',
    '植物类型', '灌溉领班', '绿化分区', '绿化领班',
    '植保分区', '植保领班', '地形特点', '植物特点',
    '土壤湿度', '灌溉设备维护记录', '灌溉管理以往记录',
]

# Priority display text → model value (for import)
_PRIORITY_IMPORT_MAP = {
    '超级重点位置': Zone.PRIORITY_CRITICAL,
    '重点位置': Zone.PRIORITY_HIGH,
    '一般位置': Zone.PRIORITY_MEDIUM,
    '次要位置': Zone.PRIORITY_LOW,
    '废除': Zone.PRIORITY_ABOLISHED,
}

# Model value → display text (for export)
_PRIORITY_EXPORT_MAP = {v: k for k, v in _PRIORITY_IMPORT_MAP.items()}

# Fields that map directly to zone model attributes (col index 0-based → field name)
# Excluding: col 7 (area), col 8 (irrigation zone name), col 9 (CCU number) which are computed
_ZONE_FIELD_COLUMNS = {
    0: 'code',
    2: 'name',
    3: 'description',
    4: 'current_status',
    5: 'sprinkler_type',
    6: 'irrigation_intensity',
    10: 'solenoid_valve_size',
    11: 'landscape_coefficient',
    12: 'plant_type',
    13: 'irrigation_foreman',
    14: 'greenery_zone',
    15: 'greenery_foreman',
    16: 'pest_control_zone',
    17: 'pest_control_foreman',
    18: 'terrain_feature',
    19: 'plant_feature',
    20: 'soil_moisture',
    21: 'equipment_maintenance_notes',
    22: 'irrigation_management_notes',
}


def _check_zone_admin(request):
    """Return True if user has zone admin permission."""
    if request.user.is_superuser or request.user.is_staff:
        return True
    from .models import ManagerProfile
    try:
        ManagerProfile.objects.get(user=request.user, active=True)
        return True
    except ManagerProfile.DoesNotExist:
        return False


def _get_user_display_name(request):
    """Get the current user's display name from their profile."""
    from .models import ManagerProfile, Worker
    for Model in (ManagerProfile, Worker):
        try:
            profile = Model.objects.get(user=request.user, active=True)
            return profile.full_name or request.user.username
        except Model.DoesNotExist:
            continue
    return request.user.username


@login_required(login_url='core:login')
def zone_export_excel(request):
    """Export all zones to an Excel file matching Zone list V0.xlsx format."""
    import io
    try:
        import openpyxl
        from openpyxl.styles import Alignment
    except ImportError:
        return JsonResponse({'error': 'openpyxl not installed'}, status=500)

    if not _check_zone_admin(request):
        return JsonResponse({'error': '无权限'}, status=403)

    zones = Zone.objects.select_related('patch').order_by('code')
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Zone info 仅色块'

    # Write headers with same styling as V0
    center_wrap = Alignment(horizontal='center', vertical='center', wrap_text=True)
    for col_idx, header in enumerate(_ZONE_EXPORT_HEADERS, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.alignment = center_wrap

    # Set column widths matching V0
    col_widths = [16, 13, 14, 13, 18, 13, 16, 13, 14, 13, 12, 8, 9, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13]
    for i, w in enumerate(col_widths):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = w

    # Write data rows
    for zone in zones:
        row_num = ws.max_row + 1
        # CCU number from patch code (e.g. "CCU1" → "1")
        ccu_num = zone.patch.code.replace('CCU', '') if zone.patch else ''

        values = [
            zone.code,                                          # A: 编号
            _PRIORITY_EXPORT_MAP.get(zone.priority, ''),         # B: 位置重要程度
            zone.land.name if zone.land else None,              # C: 所属Land
            zone.name,                                          # D: 通用名称
            zone.description,                                   # E: 灌溉管理用的位置
            zone.current_status or None,                        # F: 当前状态
            zone.sprinkler_type or None,                        # G: 灌水器类型
            zone.irrigation_intensity,                          # H: 灌溉强度
            zone.area_display if zone.area_sqm else None,       # I: 区域面积
            zone.patch.name if zone.patch else None,            # J: 灌溉分区
            int(ccu_num) if ccu_num.isdigit() else ccu_num,     # K: CCU编号
            zone.solenoid_valve_size,                           # L: 电磁阀尺寸
            zone.landscape_coefficient,                         # M: 景观系数
            zone.plant_type or None,                            # N: 植物类型
            zone.irrigation_foreman or None,                    # O: 灌溉领班
            zone.greenery_zone or None,                         # P: 绿化分区
            zone.greenery_foreman or None,                      # Q: 绿化领班
            zone.pest_control_zone or None,                     # R: 植保分区
            zone.pest_control_foreman or None,                  # S: 植保领班
            zone.terrain_feature or None,                       # T: 地形特点
            zone.plant_feature or None,                         # U: 植物特点
            zone.soil_moisture or None,                         # V: 土壤湿度
            zone.equipment_maintenance_notes or None,           # W: 灌溉设备维护记录
            zone.irrigation_management_notes or None,           # X: 灌溉管理以往记录
        ]
        for col_idx, val in enumerate(values, 1):
            ws.cell(row=row_num, column=col_idx, value=val)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    from django.utils import timezone
    filename = f"zones_{timezone.now().strftime('%Y%m%d_%H%M')}.xlsx"
    resp = HttpResponse(buf.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


def _parse_zone_row(row):
    """Parse an Excel row (23 columns, values_only) into a dict of zone fields."""
    code = str(row[0] or '').strip() if row[0] else ''
    if not code:
        return None

    priority_raw = str(row[1] or '').strip()
    priority = _PRIORITY_IMPORT_MAP.get(priority_raw, Zone.PRIORITY_MEDIUM)

    def _float(val):
        if val is None or val == '':
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _str(val):
        return str(val or '').strip()

    return {
        'code': code,
        'land': _str(row[2]),                # 所属Land (resolved to Land in confirm)
        'name': _str(row[3]) or code,
        'description': _str(row[4]),
        'priority': priority,
        'current_status': _str(row[5]),
        'sprinkler_type': _str(row[6]),
        'irrigation_intensity': _float(row[7]),
        # row[8] = 区域面积 (computed) and row[9]/[10] = 灌溉分区/CCU (from patch) — skipped
        'solenoid_valve_size': _float(row[11]),
        'landscape_coefficient': _float(row[12]),
        'plant_type': _str(row[13]),
        'irrigation_foreman': _str(row[14]),
        'greenery_zone': _str(row[15]),
        'greenery_foreman': _str(row[16]),
        'pest_control_zone': _str(row[17]),
        'pest_control_foreman': _str(row[18]),
        'terrain_feature': _str(row[19]),
        'plant_feature': _str(row[20]),
        'soil_moisture': _str(row[21]),
        'equipment_maintenance_notes': _str(row[22]),
        # row[23] = 灌溉管理以往记录 (protected) — skipped on import
    }


# Field display names for the preview table
_FIELD_LABELS = {
    'code': '编号', 'land': '所属Land', 'name': '通用名称', 'description': '灌溉管理用的位置',
    'priority': '位置重要程度', 'current_status': '当前状态',
    'sprinkler_type': '灌水器类型', 'irrigation_intensity': '灌溉强度',
    'solenoid_valve_size': '电磁阀尺寸', 'landscape_coefficient': '景观系数',
    'plant_type': '植物类型', 'irrigation_foreman': '灌溉领班',
    'greenery_zone': '绿化分区', 'greenery_foreman': '绿化领班',
    'pest_control_zone': '植保分区', 'pest_control_foreman': '植保领班',
    'terrain_feature': '地形特点', 'plant_feature': '植物特点',
    'soil_moisture': '土壤湿度', 'equipment_maintenance_notes': '设备维护记录',
    'irrigation_management_notes': '灌溉管理记录',
}

# Fields that are DB-primary / auto-calculated — never overwritten on import
# (面积 is computed from the boundary; 灌溉管理以往记录 is accumulated history).
_ZONE_IMPORT_PROTECTED = {'area_sqm', 'irrigation_management_notes'}


@login_required(login_url='core:login')
def zone_import_preview(request):
    """Upload an xlsx file, compare with DB, return change list as JSON."""
    try:
        import openpyxl
    except ImportError:
        return JsonResponse({'error': 'openpyxl not installed'}, status=500)

    if not _check_zone_admin(request):
        return JsonResponse({'error': '无权限'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    uploaded = request.FILES.get('file')
    if not uploaded:
        return JsonResponse({'error': '未选择文件'}, status=400)

    try:
        wb = openpyxl.load_workbook(uploaded, read_only=True, data_only=True)
        ws = wb.active
    except Exception as e:
        return JsonResponse({'error': f'文件解析失败: {e}'}, status=400)

    # Preload all zones by code
    existing_zones = {z.code: z for z in Zone.objects.select_related('patch').all()}

    # Fields to compare (exclude code + DB-primary/auto-calculated fields)
    compare_fields = [k for k in _FIELD_LABELS if k != 'code' and k not in _ZONE_IMPORT_PROTECTED]

    changes = []
    counts = {'new': 0, 'modified': 0, 'unchanged': 0}

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, max_col=24, values_only=True), start=2):
        parsed = _parse_zone_row(row)
        if not parsed:
            continue

        code = parsed['code']
        zone = existing_zones.get(code)

        if zone is None:
            changes.append({
                'row': row_idx, 'code': code, 'action': 'new',
                'name': parsed['name'],
                'fields': [{'field': k, 'label': _FIELD_LABELS.get(k, k), 'old': '', 'new': str(v)}
                           for k, v in parsed.items() if k != 'code' and v],
            })
            counts['new'] += 1
        else:
            field_changes = []
            for field in compare_fields:
                new_val = parsed.get(field)
                old_val = getattr(zone, field, None)
                # Normalize for comparison
                old_norm = str(old_val or '').strip()
                new_norm = str(new_val or '').strip()
                if old_norm != new_norm:
                    field_changes.append({
                        'field': field,
                        'label': _FIELD_LABELS.get(field, field),
                        'old': old_norm or '(空)',
                        'new': new_norm or '(空)',
                    })
            if field_changes:
                changes.append({
                    'row': row_idx, 'code': code, 'action': 'modified',
                    'name': zone.name,
                    'fields': field_changes,
                })
                counts['modified'] += 1
            else:
                counts['unchanged'] += 1

    wb.close()
    return JsonResponse({'success': True, 'summary': counts, 'changes': changes})


@login_required(login_url='core:login')
def zone_import_confirm(request):
    """Apply confirmed import changes. Expects multipart with file + rows JSON."""
    try:
        import openpyxl
    except ImportError:
        return JsonResponse({'error': 'openpyxl not installed'}, status=500)

    if not _check_zone_admin(request):
        return JsonResponse({'error': '无权限'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    uploaded = request.FILES.get('file')
    rows_json = request.POST.get('rows', '[]')
    try:
        import json as _json
        confirmed_rows = set(_json.loads(rows_json))
    except (_json.JSONDecodeError, TypeError):
        return JsonResponse({'error': '无效的行号数据'}, status=400)

    if not uploaded:
        return JsonResponse({'error': '未选择文件'}, status=400)

    try:
        wb = openpyxl.load_workbook(uploaded, read_only=True, data_only=True)
        ws = wb.active
    except Exception as e:
        return JsonResponse({'error': f'文件解析失败: {e}'}, status=400)

    from .models import Patch, Land

    # Preload patches by CCU number
    patch_map = {}
    for p in Patch.objects.filter(code__startswith='CCU'):
        patch_map[p.code.replace('CCU', '')] = p
    # Preload lands by name
    land_map = {l.name: l for l in Land.objects.all()}

    created = 0
    updated = 0

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, max_col=24, values_only=True), start=2):
        if row_idx not in confirmed_rows:
            continue

        parsed = _parse_zone_row(row)
        if not parsed:
            continue

        code = parsed['code']
        # Resolve patch from code prefix
        parts = code.split('-')
        ccu_prefix = parts[0] if parts else ''
        patch = patch_map.get(ccu_prefix)
        # Resolve Land (create on demand); protected fields are already excluded by _parse_zone_row
        land_name = (parsed.get('land') or '').strip()
        land = None
        if land_name:
            land = land_map.get(land_name)
            if not land:
                land = Land.objects.create(name=land_name)
                land_map[land_name] = land

        zone = Zone.objects.filter(code=code).first()
        if zone:
            for k, v in parsed.items():
                if k in ('code', 'land'):
                    continue
                setattr(zone, k, v)
            zone.land = land
            if patch:
                zone.patch = patch
            zone.save()
            updated += 1
        else:
            zone = Zone(code=code, patch=patch, land=land)
            for k, v in parsed.items():
                if k in ('code', 'land'):
                    continue
                setattr(zone, k, v)
            zone.save()
            created += 1

    wb.close()
    return JsonResponse({'success': True, 'created': created, 'updated': updated})


@login_required(login_url='core:login')
def settings_page(request):
    """
    Settings page to manage zones and system configuration - admin only.
    """
    from .models import ManagerProfile, Pipeline, Patch, Plant, Region

    # Check admin permission
    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        messages.error(request, '无权限访问设置页面')
        return redirect('core:dashboard')

    zones = Zone.objects.all().order_by('code')
    pipelines = Pipeline.objects.all().order_by('code')
    regions = Region.objects.filter(active=True).order_by('order', 'name')
    site_patches = Patch.objects.order_by('code')

    # Precompute zone counts per patch (FK + derived from code prefix)
    grouped_zones_data = _build_grouped_zones(zones)
    priority_zones_data = _build_grouped_zones(zones, group_by='priority')
    patch_zone_counts = {}
    for group in grouped_zones_data:
        pid = group.get('id')
        if pid:
            patch_zone_counts[pid] = group['zone_count']

    # Precompute linked patch counts (children via parent FK)
    child_counts = {}
    for p in site_patches:
        child_counts[p.id] = p.children.count()

    # Precompute patch counts per region
    region_patch_counts = {}
    for r in regions:
        region_patch_counts[r.id] = r.patches.count()

    all_plant_names = list(Plant.objects.values_list('name', flat=True).distinct().order_by('name'))

    from .models import Landmark
    landmarks = Landmark.objects.annotate(zone_count=Count('zone_assignments')).order_by('order', 'name')

    context = {
        'zones': zones,
        'grouped_zones': grouped_zones_data,
        'priority_zones': priority_zones_data,
        'priority_choices': Zone.PRIORITY_CHOICES,
        'all_plant_names': all_plant_names,
        'status_choices': Zone.STATUS_CHOICES,
        'pipelines': pipelines,
        'site_patches': site_patches,
        'patch_zone_counts': patch_zone_counts,
        'child_counts': child_counts,
        'regions': regions,
        'region_patch_counts': region_patch_counts,
        'landmarks': landmarks,
    }

    return render(request, 'core/settings.html', context)


def _get_patches_by_region():
    """Return patches grouped by region for the settings page."""
    from .models import Region, Patch
    result = []
    for region in Region.objects.filter(active=True).order_by('order', 'name'):
        patches = Patch.objects.filter(region=region).order_by('code')
        if patches.exists():
            result.append({
                'region': region,
                'patches': patches,
            })
    # Include unassigned patches
    unassigned = Patch.objects.filter(region__isnull=True).order_by('code')
    if unassigned.exists():
        result.append({
            'region': None,
            'patches': unassigned,
        })
    return result


@login_required(login_url='core:login')
def zone_edit(request, zone_id):
    """
    Edit a specific zone - admin only.
    """
    from .models import ManagerProfile, Plant, ZoneEquipment, Patch

    # Check admin permission
    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        if _wants_json(request):
            return JsonResponse({'success': False, 'message': '无权限修改区域'}, status=403)
        messages.error(request, '无权限修改区域')
        return redirect('core:dashboard')

    zone = get_object_or_404(Zone, pk=zone_id)

    if request.method == 'POST':
        zone.name = request.POST.get('name', zone.name)
        zone.code = request.POST.get('code', zone.code)
        zone.description = request.POST.get('description', zone.description)
        zone.boundary_color = request.POST.get('boundary_color', zone.boundary_color)
        zone.priority = request.POST.get('priority', zone.priority)

        # Irrigation attributes
        zone.current_status = request.POST.get('current_status', '')
        zone.sprinkler_type = request.POST.get('sprinkler_type', '')
        zone.irrigation_intensity = _parse_float(request.POST.get('irrigation_intensity'))
        zone.solenoid_valve_size = _parse_float(request.POST.get('solenoid_valve_size'))
        zone.landscape_coefficient = _parse_float(request.POST.get('landscape_coefficient'))
        zone.plant_type = request.POST.get('plant_type', '')
        zone.soil_moisture = request.POST.get('soil_moisture', '')
        zone.terrain_feature = request.POST.get('terrain_feature', '')
        zone.plant_feature = request.POST.get('plant_feature', '')
        zone.irrigation_foreman = request.POST.get('irrigation_foreman', '')
        zone.greenery_zone = request.POST.get('greenery_zone', '')
        zone.greenery_foreman = request.POST.get('greenery_foreman', '')
        zone.pest_control_zone = request.POST.get('pest_control_zone', '')
        zone.pest_control_foreman = request.POST.get('pest_control_foreman', '')
        zone.equipment_maintenance_notes = request.POST.get('equipment_maintenance_notes', '')
        zone.irrigation_management_notes = request.POST.get('irrigation_management_notes', '')

        # Label settings
        label_lat = request.POST.get('label_lat', '')
        label_lng = request.POST.get('label_lng', '')
        zone.label_lat = float(label_lat) if label_lat else None
        zone.label_lng = float(label_lng) if label_lng else None
        zone.label_scale = float(request.POST.get('label_scale', 1.0) or 1.0)
        zone.label_angle = int(request.POST.get('label_angle', 0) or 0)

        # Smooth override
        smooth_val = request.POST.get('smooth_override', '')
        zone.smooth_override = int(smooth_val) if smooth_val != '' else None

        # Handle patch selection
        patch_id = request.POST.get('patch')
        new_patch_name = request.POST.get('new_patch_name', '').strip()

        if new_patch_name and not patch_id:
            # Create new patch
            patch_code = new_patch_name[:10].replace(' ', '-')
            patch, created = Patch.objects.get_or_create(
                name=new_patch_name,
                defaults={'code': patch_code}
            )
            zone.patch = patch
        elif patch_id:
            zone.patch_id = patch_id
        else:
            zone.patch = None

        # Parse boundary points from JSON
        boundary_json = request.POST.get('boundary_points', '[]')
        try:
            boundary_points = json.loads(boundary_json)
            # Auto-close any incomplete polygons (points defined but not explicitly "completed")
            zone.boundary_points = auto_close_boundary_points(boundary_points)
        except json.JSONDecodeError:
            if _wants_json(request):
                return JsonResponse({'success': False, 'message': '边界点数据格式有误，请重新绘制区域边界后重试'}, status=400)
            messages.error(request, '边界点数据格式有误，请重新绘制区域边界后重试')
            return redirect('core:zone_edit', zone_id=zone.id)

        zone.drawn_by = request.user
        zone.save()

        # Handle plants - JSON array in hidden field
        plants_data = request.POST.get('plants_data', '')
        if plants_data:
            try:
                plants_list = json.loads(plants_data)
                zone.plants.all().delete()
                for item in plants_list:
                    Plant.objects.create(
                        zone=zone,
                        name=item.get('name', ''),
                        quantity=item.get('quantity', 1),
                        planting_date=item.get('planting_date') or None,
                        end_date=item.get('end_date') or None,
                        notes=item.get('notes', ''),
                    )
            except json.JSONDecodeError:
                pass

        # Handle equipment - JSON array in hidden field
        equipment_data = request.POST.get('equipment_data', '')
        if equipment_data:
            try:
                equipment_list = json.loads(equipment_data)
                zone.equipments.all().delete()
                for item in equipment_list:
                    equipment_id = item.get('equipment_id')
                    if equipment_id:
                        ZoneEquipment.objects.create(
                            zone=zone,
                            equipment_id=equipment_id,
                            quantity=item.get('quantity', 1),
                            installation_date=item.get('installation_date') or None,
                            status=item.get('status', 'working'),
                            location_in_zone=item.get('location_in_zone', ''),
                            notes=item.get('notes', '')
                        )
            except json.JSONDecodeError:
                pass

        return _zone_save_response(request, zone, f'区域「{zone.name}」已保存成功')

    # Get available plants (distinct names from all plants)
    available_plants = list(Plant.objects.values_list('name', flat=True).distinct().order_by('name'))

    # Get zone equipment
    zone_equipments = zone.equipments.select_related('equipment').all()

    # Get all patches for selection
    patches = Patch.objects.all()

    ref_zones_json, ref_pipelines_json = _get_reference_map_data(exclude_zone_id=zone.id)

    # Sibling zones: other zones in the same patch (for sidebar navigation)
    sibling_zones = []
    if zone.patch_id:
        sibling_zones = list(
            Zone.objects.filter(patch_id=zone.patch_id)
            .exclude(pk=zone.pk)
            .values('id', 'name', 'code', 'priority', 'current_status')
            .order_by('code')
        )

    context = {
        'zone': zone,
        'boundary_json': json.dumps(zone.boundary_points),
        'available_plants': available_plants,
        'zone_equipments': zone_equipments,
        'patches': patches,
        'ref_zones_json': ref_zones_json,
        'ref_pipelines_json': ref_pipelines_json,
        'sibling_zones': sibling_zones,
        'equip_notes_json': json.dumps(json.loads(zone.equipment_maintenance_notes)) if zone.equipment_maintenance_notes else '[]',
        'irrig_notes_json': json.dumps(json.loads(zone.irrigation_management_notes)) if zone.irrigation_management_notes else '[]',
        'boundary_count': len(zone.boundary_points) if zone.boundary_points else 0,
        'equip_notes_count': len(json.loads(zone.equipment_maintenance_notes)) if zone.equipment_maintenance_notes else 0,
        'irrig_notes_count': len(json.loads(zone.irrigation_management_notes)) if zone.irrigation_management_notes else 0,
        'plant_count': zone.plants.count(),
        'equipment_count': zone.equipments.count(),
        **_get_zone_dropdown_options(),
    }

    return render(request, 'core/zone_form.html', context)


@login_required(login_url='core:login')
def zone_new(request):
    """
    Create a new zone - admin only.
    """
    from .models import ManagerProfile, Plant, ZoneEquipment, Patch

    # Check admin permission
    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        if _wants_json(request):
            return JsonResponse({'success': False, 'message': '无权限创建区域'}, status=403)
        messages.error(request, '无权限创建区域')
        return redirect('core:dashboard')

    if request.method == 'POST':
        zone = Zone(
            name=request.POST.get('name'),
            code=request.POST.get('code'),
            description=request.POST.get('description', ''),
            boundary_color=request.POST.get('boundary_color', '#52B788'),
            priority=request.POST.get('priority', Zone.PRIORITY_MEDIUM),
            current_status=request.POST.get('current_status', ''),
            sprinkler_type=request.POST.get('sprinkler_type', ''),
            irrigation_intensity=_parse_float(request.POST.get('irrigation_intensity')),
            solenoid_valve_size=_parse_float(request.POST.get('solenoid_valve_size')),
            landscape_coefficient=_parse_float(request.POST.get('landscape_coefficient')),
            plant_type=request.POST.get('plant_type', ''),
            soil_moisture=request.POST.get('soil_moisture', ''),
            terrain_feature=request.POST.get('terrain_feature', ''),
            plant_feature=request.POST.get('plant_feature', ''),
            irrigation_foreman=request.POST.get('irrigation_foreman', ''),
            greenery_zone=request.POST.get('greenery_zone', ''),
            greenery_foreman=request.POST.get('greenery_foreman', ''),
            pest_control_zone=request.POST.get('pest_control_zone', ''),
            pest_control_foreman=request.POST.get('pest_control_foreman', ''),
            equipment_maintenance_notes=request.POST.get('equipment_maintenance_notes', ''),
            irrigation_management_notes=request.POST.get('irrigation_management_notes', ''),
        )

        # Label settings
        label_lat = request.POST.get('label_lat', '')
        label_lng = request.POST.get('label_lng', '')
        zone.label_lat = float(label_lat) if label_lat else None
        zone.label_lng = float(label_lng) if label_lng else None
        zone.label_scale = float(request.POST.get('label_scale', 1.0) or 1.0)
        zone.label_angle = int(request.POST.get('label_angle', 0) or 0)

        # Smooth override
        smooth_val = request.POST.get('smooth_override', '')
        zone.smooth_override = int(smooth_val) if smooth_val != '' else None

        # Handle patch selection
        patch_id = request.POST.get('patch')
        new_patch_name = request.POST.get('new_patch_name', '').strip()

        if new_patch_name and not patch_id:
            # Create new patch
            patch_code = new_patch_name[:10].replace(' ', '-')
            patch, created = Patch.objects.get_or_create(
                name=new_patch_name,
                defaults={'code': patch_code}
            )
            zone.patch = patch
        elif patch_id:
            zone.patch_id = patch_id

        # Parse boundary points from JSON
        boundary_json = request.POST.get('boundary_points', '[]')
        try:
            boundary_points = json.loads(boundary_json)
            # Auto-close any incomplete polygons (points defined but not explicitly "completed")
            zone.boundary_points = auto_close_boundary_points(boundary_points)
        except json.JSONDecodeError:
            if _wants_json(request):
                return JsonResponse({'success': False, 'message': '边界点数据格式有误，请重新绘制区域边界后重试'}, status=400)
            messages.error(request, '边界点数据格式有误，请重新绘制区域边界后重试')
            return render(request, 'core/zone_form.html', {
                'zone': zone,
                'boundary_json': boundary_json,
            })

        zone.drawn_by = request.user
        zone.save()

        # Handle plants - JSON array with full details
        plants_data = request.POST.get('plants_data', '')
        if plants_data:
            try:
                plants_list = json.loads(plants_data)
                for item in plants_list:
                    Plant.objects.create(
                        zone=zone,
                        name=item.get('name', ''),
                        quantity=item.get('quantity', 1),
                        planting_date=item.get('planting_date') or None,
                        end_date=item.get('end_date') or None,
                        notes=item.get('notes', ''),
                    )
            except json.JSONDecodeError:
                # Fallback to comma-separated names
                plant_names = [p.strip() for p in plants_data.split(',') if p.strip()]
                for name in plant_names:
                    Plant.objects.create(zone=zone, name=name)

        # Handle equipment - JSON array in hidden field
        equipment_data = request.POST.get('equipment_data', '')
        if equipment_data:
            try:
                equipment_list = json.loads(equipment_data)
                for item in equipment_list:
                    equipment_id = item.get('equipment_id')
                    if equipment_id:
                        ZoneEquipment.objects.create(
                            zone=zone,
                            equipment_id=equipment_id,
                            quantity=item.get('quantity', 1),
                            installation_date=item.get('installation_date') or None,
                            status=item.get('status', 'working'),
                            location_in_zone=item.get('location_in_zone', ''),
                            notes=item.get('notes', '')
                        )
            except json.JSONDecodeError:
                pass

        return _zone_save_response(request, zone, f'区域「{zone.name}」已创建成功', created=True)

    # Get available plants
    available_plants = list(Plant.objects.values_list('name', flat=True).distinct().order_by('name'))

    # Get all patches for selection
    patches = Patch.objects.all()

    ref_zones_json, ref_pipelines_json = _get_reference_map_data()

    context = {
        'zone': None,
        'boundary_json': '[]',
        'available_plants': available_plants,
        'patches': patches,
        'ref_zones_json': ref_zones_json,
        'ref_pipelines_json': ref_pipelines_json,
        'equip_notes_json': '[]',
        'irrig_notes_json': '[]',
        **_get_zone_dropdown_options(),
    }

    return render(request, 'core/zone_form.html', context)


@require_POST
@login_required(login_url='core:login')
def zone_delete(request, zone_id):
    """
    Delete a zone - admin only.
    """
    from .models import ManagerProfile

    # Check admin permission
    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        messages.error(request, '无权限删除区域')
        return redirect('core:dashboard')

    zone = get_object_or_404(Zone, pk=zone_id)
    zone_name = zone.name
    zone.delete()
    messages.success(request, f'Zone "{zone_name}" deleted successfully.')
    return redirect('core:settings')


@login_required(login_url='core:login')
def zone_batch_draw(request):
    """Batch zone boundary drawing page."""
    from .models import ManagerProfile, Patch

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        messages.error(request, '无权限访问此页面')
        return redirect('core:dashboard')

    if request.method == 'POST':
        new_zone = request.POST.get('new_zone') == 'true'
        if new_zone:
            patch_id = request.POST.get('patch_id')
            code = request.POST.get('code', '').strip()
            name = request.POST.get('name', '').strip()
            if not patch_id:
                return JsonResponse({'success': False, 'message': '缺少片区ID'}, status=400)
            if not code:
                return JsonResponse({'success': False, 'message': '请输入区域编号'}, status=400)
            if Zone.objects.filter(code=code).exists():
                return JsonResponse({'success': False, 'message': f'区域编号 {code} 已存在'}, status=400)
            patch = get_object_or_404(Patch, pk=int(patch_id))
            zone = Zone.objects.create(
                patch=patch, code=code, name=name or code,
                priority='medium', boundary_points=[], boundary_color='#52B788'
            )
        else:
            zone_id = request.POST.get('zone_id')
            if not zone_id:
                return JsonResponse({'success': False, 'message': '缺少区域ID'}, status=400)
            zone = get_object_or_404(Zone, pk=int(zone_id))

        boundary_raw = request.POST.get('boundary_points', '[]')
        try:
            boundary_data = json.loads(boundary_raw)
        except (json.JSONDecodeError, TypeError):
            boundary_data = []

        boundary_data = auto_close_boundary_points(boundary_data)
        zone.boundary_points = boundary_data

        label_lat = request.POST.get('label_lat', '')
        label_lng = request.POST.get('label_lng', '')
        zone.label_lat = float(label_lat) if label_lat else None
        zone.label_lng = float(label_lng) if label_lng else None
        zone.label_scale = float(request.POST.get('label_scale', '1.0') or '1.0')
        zone.label_angle = int(request.POST.get('label_angle', '0') or '0')
        smooth_val = request.POST.get('smooth_override', '')
        zone.smooth_override = int(smooth_val) if smooth_val != '' else None

        zone.drawn_by = request.user
        zone.save()

        return JsonResponse({
            'success': True,
            'message': f'区域 {zone.code} 边界已保存',
            'zone_id': zone.id,
            'zone_name': zone.name,
            'zone_code': zone.code,
            'area_display': zone.area_display,
            'boundary_count': len(zone.boundary_points),
            'boundary_points': zone.boundary_points,
            'boundary_color': zone.boundary_color,
            'label_lat': zone.label_lat,
            'label_lng': zone.label_lng,
            'label_scale': zone.label_scale,
            'label_angle': zone.label_angle,
            'smooth_override': zone.smooth_override,
            'patch_id': zone.patch_id,
            'is_new': new_zone if request.method == 'POST' else False,
        })

    patches = Patch.objects.all().order_by('code')

    # All zones with boundaries for reference layer on map
    all_drawn_zones = []
    for z in Zone.objects.select_related('patch').only(
        'id', 'code', 'name', 'boundary_points', 'boundary_color',
        'label_lat', 'label_lng', 'label_scale', 'label_angle', 'smooth_override', 'patch_id'
    ):
        all_drawn_zones.append({
            'id': z.id,
            'code': z.code,
            'name': z.name,
            'boundary_points': z.active_boundary_points,
            'boundary_color': z.boundary_color,
            'label_lat': z.label_lat,
            'label_lng': z.label_lng,
            'label_scale': z.label_scale,
            'label_angle': z.label_angle,
            'smooth_override': z.smooth_override,
            'patch_id': z.patch_id,
        })

    context = {
        'patches': patches,
        'all_drawn_zones_json': json.dumps(all_drawn_zones),
        'nav_settings': True,
    }
    return render(request, 'core/zone_batch_draw.html', context)


@login_required(login_url='core:login')
def zone_batch_draw_zones_api(request):
    """API: return zones for a given patch_id."""
    from .models import ManagerProfile

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        return JsonResponse({'error': '无权限'}, status=403)

    patch_id = request.GET.get('patch_id')
    if not patch_id:
        return JsonResponse({'error': '缺少patch_id参数'}, status=400)

    zones = Zone.objects.filter(patch_id=patch_id).order_by('code')
    result = []
    for z in zones:
        has_boundary = bool(z.active_boundary_points)
        result.append({
            'id': z.id,
            'code': z.code,
            'name': z.name,
            'has_boundary': has_boundary,
            'boundary_points': z.active_boundary_points if has_boundary else [],
            'boundary_color': z.boundary_color,
            'label_lat': z.label_lat,
            'label_lng': z.label_lng,
            'label_scale': z.label_scale,
            'label_angle': z.label_angle,
            'smooth_override': z.smooth_override,
            'area_display': z.area_display if has_boundary else '',
        })
    return JsonResponse({'zones': result})


@login_required(login_url='core:login')
@ensure_csrf_cookie
def zone_quick_draw(request):
    """Quick zone boundary drawing page — draw first, assign zone code after."""
    from .models import ManagerProfile, Worker, MapStyleSettings

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        try:
            Worker.objects.get(user=request.user, active=True)
        except Worker.DoesNotExist:
            messages.error(request, '无权限访问此页面')
            return redirect('core:dashboard')

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'delete_boundary':
            zone_code = request.POST.get('zone_code', '').strip()
            if not zone_code:
                return JsonResponse({'success': False, 'message': '缺少区域编号'}, status=400)
            try:
                zone = Zone.objects.get(code=zone_code)
                zone.boundary_points = []
                zone.label_lat = None
                zone.label_lng = None
                zone.drawn_by = None
                zone.save()
                return JsonResponse({'success': True, 'message': f'区域 {zone.code} 边界已删除'})
            except Zone.DoesNotExist:
                return JsonResponse({'success': False, 'message': f'区域 {zone_code} 不存在'}, status=404)

        if action == 'update_color':
            zone_code = request.POST.get('zone_code', '').strip()
            boundary_color = request.POST.get('boundary_color', '').strip()
            if not zone_code:
                return JsonResponse({'success': False, 'message': '缺少区域编号'}, status=400)
            if not boundary_color:
                return JsonResponse({'success': False, 'message': '缺少颜色值'}, status=400)
            try:
                zone = Zone.objects.get(code=zone_code)
                zone.boundary_color = boundary_color
                zone.drawn_by = request.user
                zone.save()
                return JsonResponse({'success': True, 'message': f'区域 {zone.code} 颜色已更新', 'boundary_color': zone.boundary_color})
            except Zone.DoesNotExist:
                return JsonResponse({'success': False, 'message': f'区域 {zone_code} 不存在'}, status=404)

        if action == 'update_ring_display_mode':
            zone_code = request.POST.get('zone_code', '').strip()
            ring_index = request.POST.get('ring_index', '')
            mode = request.POST.get('mode', 'line')
            if not zone_code:
                return JsonResponse({'success': False, 'message': '缺少区域编号'}, status=400)
            if mode not in ('line', 'sublabel'):
                return JsonResponse({'success': False, 'message': '无效的显示模式'}, status=400)
            try:
                zone = Zone.objects.get(code=zone_code)
                modes = dict(zone.ring_display_modes or {})
                if mode == 'line':
                    modes.pop(str(ring_index), None)
                else:
                    modes[str(ring_index)] = mode
                # Prune stale indices beyond ring count
                bp = zone.boundary_points or []
                ring_count = len(bp) if bp and isinstance(bp[0], (list,)) else 0
                if ring_count > 0:
                    modes = {k: v for k, v in modes.items() if int(k) < ring_count}
                zone.ring_display_modes = modes
                zone.save()
                mode_label = '引导线' if mode == 'line' else '子标签'
                return JsonResponse({'success': True, 'message': f'已切换为{mode_label}', 'ring_display_modes': modes})
            except Zone.DoesNotExist:
                return JsonResponse({'success': False, 'message': f'区域 {zone_code} 不存在'}, status=404)

        if action == 'update_all_ring_display_modes':
            zone_code = request.POST.get('zone_code', '').strip()
            mode = request.POST.get('mode', 'line')
            if not zone_code:
                return JsonResponse({'success': False, 'message': '缺少区域编号'}, status=400)
            if mode not in ('line', 'sublabel'):
                return JsonResponse({'success': False, 'message': '无效的显示模式'}, status=400)
            try:
                zone = Zone.objects.get(code=zone_code)
                bp = zone.boundary_points or []
                ring_count = len(bp) if bp and isinstance(bp[0], (list,)) else 0
                if mode == 'line':
                    modes = {}
                else:
                    modes = {str(i): mode for i in range(ring_count)}
                zone.ring_display_modes = modes
                zone.save()
                mode_label = '引导线' if mode == 'line' else '子标签'
                return JsonResponse({'success': True, 'message': f'已全部切换为{mode_label}', 'ring_display_modes': modes})
            except Zone.DoesNotExist:
                return JsonResponse({'success': False, 'message': f'区域 {zone_code} 不存在'}, status=404)

        # Save boundary action
        zone_code = request.POST.get('zone_code', '').strip()
        if not zone_code:
            return JsonResponse({'success': False, 'message': '缺少区域编号'}, status=400)

        try:
            zone = Zone.objects.get(code=zone_code)
        except Zone.DoesNotExist:
            return JsonResponse({'success': False, 'message': f'区域编号 {zone_code} 不存在，请检查输入'}, status=404)

        boundary_raw = request.POST.get('boundary_points', '[]')
        try:
            boundary_data = json.loads(boundary_raw)
        except (json.JSONDecodeError, TypeError):
            boundary_data = []

        boundary_data = auto_close_boundary_points(boundary_data)
        zone.boundary_points = boundary_data

        label_lat = request.POST.get('label_lat', '')
        label_lng = request.POST.get('label_lng', '')
        zone.label_lat = float(label_lat) if label_lat else None
        zone.label_lng = float(label_lng) if label_lng else None
        zone.label_scale = float(request.POST.get('label_scale', '1.0') or '1.0')
        zone.label_angle = int(request.POST.get('label_angle', '0') or '0')
        smooth_val = request.POST.get('smooth_override', '')
        zone.smooth_override = int(smooth_val) if smooth_val != '' else None
        boundary_color = request.POST.get('boundary_color')
        if boundary_color:
            zone.boundary_color = boundary_color
        zone.drawn_by = request.user

        zone.save()

        patch_name = zone.patch.name if zone.patch else ''
        return JsonResponse({
            'success': True,
            'message': f'区域 {zone.code} 边界已保存',
            'zone_id': zone.id,
            'zone_name': zone.name,
            'zone_code': zone.code,
            'area_display': zone.area_display,
            'boundary_count': len(zone.boundary_points),
            'boundary_points': zone.boundary_points,
            'boundary_color': zone.boundary_color,
            'label_lat': zone.label_lat,
            'label_lng': zone.label_lng,
            'label_scale': zone.label_scale,
            'label_angle': zone.label_angle,
            'smooth_override': zone.smooth_override,
            'ring_display_modes': zone.ring_display_modes or {},
            'patch_id': zone.patch_id,
            'patch_name': patch_name,
        })

    # GET — render page with all zones data
    all_zones = []
    for z in Zone.objects.select_related('patch').order_by('code').only(
        'id', 'code', 'name', 'patch_id', 'patch__name'
    ):
        all_zones.append({
            'id': z.id,
            'code': z.code,
            'name': z.name,
            'patch_name': z.patch.name if z.patch else '',
        })

    # All zones with boundaries for reference layer on map
    all_drawn_zones = []
    for z in Zone.objects.select_related('patch').only(
        'id', 'code', 'name', 'boundary_points', 'boundary_source', 'dxf_boundary_points', 'boundary_color',
        'label_lat', 'label_lng', 'label_scale', 'label_angle', 'smooth_override',
        'ring_display_modes', 'patch_id', 'patch__name', 'area_sqm'
    ):
        all_drawn_zones.append({
            'id': z.id,
            'code': z.code,
            'name': z.name,
            'boundary_points': z.active_boundary_points,
            'boundary_color': z.boundary_color,
            'label_lat': z.label_lat,
            'label_lng': z.label_lng,
            'label_scale': z.label_scale,
            'label_angle': z.label_angle,
            'smooth_override': z.smooth_override,
            'ring_display_modes': z.ring_display_modes or {},
            'patch_id': z.patch_id,
            'patch_name': z.patch.name if z.patch else '',
            'area_display': z.area_display,
        })

    # Drawing stats per patch
    from .models import Patch
    patch_stats = []
    for p in Patch.objects.order_by('name'):
        total = Zone.objects.filter(patch=p).count()
        drawn = Zone.objects.filter(patch=p).exclude(boundary_points__isnull=True).exclude(boundary_points=[]).count() + Zone.objects.filter(patch=p, boundary_source='dxf').exclude(dxf_boundary_points__isnull=True).exclude(dxf_boundary_points=[]).count()
        patch_stats.append({'name': p.name, 'total': total, 'drawn': drawn})
    total_all = Zone.objects.count()
    drawn_all = Zone.objects.exclude(boundary_points__isnull=True).exclude(boundary_points=[]).count() + Zone.objects.filter(boundary_source='dxf').exclude(dxf_boundary_points__isnull=True).exclude(dxf_boundary_points=[]).count()

    context = {
        'all_zones_json': json.dumps(all_zones),
        'all_drawn_zones_json': json.dumps(all_drawn_zones),
        'map_style_json': json.dumps(MapStyleSettings.get_style()),
        'patch_stats_json': json.dumps(patch_stats),
        'drawn_total': drawn_all,
        'zone_total': total_all,
        'nav_settings': True,
    }
    return render(request, 'core/zone_quick_draw.html', context)


@login_required(login_url='core:login')
@ensure_csrf_cookie
def zone_quick_draw_mobile(request):
    """Mobile-optimized quick zone boundary drawing page."""
    from .models import ManagerProfile, Worker, MapStyleSettings

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        try:
            Worker.objects.get(user=request.user, active=True)
        except Worker.DoesNotExist:
            messages.error(request, '无权限访问此页面')
            return redirect('core:dashboard')

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'delete_boundary':
            zone_code = request.POST.get('zone_code', '').strip()
            if not zone_code:
                return JsonResponse({'success': False, 'message': '缺少区域编号'}, status=400)
            try:
                zone = Zone.objects.get(code=zone_code)
                zone.boundary_points = []
                zone.label_lat = None
                zone.label_lng = None
                zone.drawn_by = None
                zone.save()
                return JsonResponse({'success': True, 'message': f'区域 {zone.code} 边界已删除'})
            except Zone.DoesNotExist:
                return JsonResponse({'success': False, 'message': f'区域 {zone_code} 不存在'}, status=404)

        if action == 'update_color':
            zone_code = request.POST.get('zone_code', '').strip()
            boundary_color = request.POST.get('boundary_color', '').strip()
            if not zone_code:
                return JsonResponse({'success': False, 'message': '缺少区域编号'}, status=400)
            if not boundary_color:
                return JsonResponse({'success': False, 'message': '缺少颜色值'}, status=400)
            try:
                zone = Zone.objects.get(code=zone_code)
                zone.boundary_color = boundary_color
                zone.drawn_by = request.user
                zone.save()
                return JsonResponse({'success': True, 'message': f'区域 {zone.code} 颜色已更新', 'boundary_color': zone.boundary_color})
            except Zone.DoesNotExist:
                return JsonResponse({'success': False, 'message': f'区域 {zone_code} 不存在'}, status=404)

        if action == 'update_ring_display_mode':
            zone_code = request.POST.get('zone_code', '').strip()
            ring_index = request.POST.get('ring_index', '')
            mode = request.POST.get('mode', 'line')
            if not zone_code:
                return JsonResponse({'success': False, 'message': '缺少区域编号'}, status=400)
            if mode not in ('line', 'sublabel'):
                return JsonResponse({'success': False, 'message': '无效的显示模式'}, status=400)
            try:
                zone = Zone.objects.get(code=zone_code)
                modes = dict(zone.ring_display_modes or {})
                if mode == 'line':
                    modes.pop(str(ring_index), None)
                else:
                    modes[str(ring_index)] = mode
                bp = zone.boundary_points or []
                ring_count = len(bp) if bp and isinstance(bp[0], (list,)) else 0
                if ring_count > 0:
                    modes = {k: v for k, v in modes.items() if int(k) < ring_count}
                zone.ring_display_modes = modes
                zone.save()
                mode_label = '引导线' if mode == 'line' else '子标签'
                return JsonResponse({'success': True, 'message': f'已切换为{mode_label}', 'ring_display_modes': modes})
            except Zone.DoesNotExist:
                return JsonResponse({'success': False, 'message': f'区域 {zone_code} 不存在'}, status=404)

        if action == 'update_all_ring_display_modes':
            zone_code = request.POST.get('zone_code', '').strip()
            mode = request.POST.get('mode', 'line')
            if not zone_code:
                return JsonResponse({'success': False, 'message': '缺少区域编号'}, status=400)
            if mode not in ('line', 'sublabel'):
                return JsonResponse({'success': False, 'message': '无效的显示模式'}, status=400)
            try:
                zone = Zone.objects.get(code=zone_code)
                bp = zone.boundary_points or []
                ring_count = len(bp) if bp and isinstance(bp[0], (list,)) else 0
                if mode == 'line':
                    modes = {}
                else:
                    modes = {str(i): mode for i in range(ring_count)}
                zone.ring_display_modes = modes
                zone.save()
                mode_label = '引导线' if mode == 'line' else '子标签'
                return JsonResponse({'success': True, 'message': f'已全部切换为{mode_label}', 'ring_display_modes': modes})
            except Zone.DoesNotExist:
                return JsonResponse({'success': False, 'message': f'区域 {zone_code} 不存在'}, status=404)

        zone_code = request.POST.get('zone_code', '').strip()
        if not zone_code:
            return JsonResponse({'success': False, 'message': '缺少区域编号'}, status=400)

        try:
            zone = Zone.objects.get(code=zone_code)
        except Zone.DoesNotExist:
            return JsonResponse({'success': False, 'message': f'区域编号 {zone_code} 不存在，请检查输入'}, status=404)

        boundary_raw = request.POST.get('boundary_points', '[]')
        try:
            boundary_data = json.loads(boundary_raw)
        except (json.JSONDecodeError, TypeError):
            boundary_data = []

        boundary_data = auto_close_boundary_points(boundary_data)
        zone.boundary_points = boundary_data

        label_lat = request.POST.get('label_lat', '')
        label_lng = request.POST.get('label_lng', '')
        zone.label_lat = float(label_lat) if label_lat else None
        zone.label_lng = float(label_lng) if label_lng else None
        zone.label_scale = float(request.POST.get('label_scale', '1.0') or '1.0')
        zone.label_angle = int(request.POST.get('label_angle', '0') or '0')
        smooth_val = request.POST.get('smooth_override', '')
        zone.smooth_override = int(smooth_val) if smooth_val != '' else None
        boundary_color = request.POST.get('boundary_color')
        if boundary_color:
            zone.boundary_color = boundary_color
        zone.drawn_by = request.user

        zone.save()

        patch_name = zone.patch.name if zone.patch else ''
        return JsonResponse({
            'success': True,
            'message': f'区域 {zone.code} 边界已保存',
            'zone_id': zone.id,
            'zone_name': zone.name,
            'zone_code': zone.code,
            'area_display': zone.area_display,
            'boundary_count': len(zone.boundary_points),
            'boundary_points': zone.boundary_points,
            'boundary_color': zone.boundary_color,
            'label_lat': zone.label_lat,
            'label_lng': zone.label_lng,
            'label_scale': zone.label_scale,
            'label_angle': zone.label_angle,
            'smooth_override': zone.smooth_override,
            'ring_display_modes': zone.ring_display_modes or {},
            'patch_id': zone.patch_id,
            'patch_name': patch_name,
        })

    all_zones = []
    for z in Zone.objects.select_related('patch').order_by('code').only(
        'id', 'code', 'name', 'patch_id', 'patch__name'
    ):
        all_zones.append({
            'id': z.id,
            'code': z.code,
            'name': z.name,
            'patch_name': z.patch.name if z.patch else '',
        })

    all_drawn_zones = []
    for z in Zone.objects.select_related('patch').only(
        'id', 'code', 'name', 'boundary_points', 'boundary_source', 'dxf_boundary_points', 'boundary_color',
        'label_lat', 'label_lng', 'label_scale', 'label_angle', 'smooth_override',
        'ring_display_modes', 'patch_id', 'patch__name', 'area_sqm'
    ):
        all_drawn_zones.append({
            'id': z.id,
            'code': z.code,
            'name': z.name,
            'boundary_points': z.active_boundary_points,
            'boundary_color': z.boundary_color,
            'label_lat': z.label_lat,
            'label_lng': z.label_lng,
            'label_scale': z.label_scale,
            'label_angle': z.label_angle,
            'smooth_override': z.smooth_override,
            'ring_display_modes': z.ring_display_modes or {},
            'patch_id': z.patch_id,
            'patch_name': z.patch.name if z.patch else '',
            'area_display': z.area_display,
        })

    # Drawing stats per patch
    from .models import Patch
    patch_stats = []
    for p in Patch.objects.order_by('name'):
        total = Zone.objects.filter(patch=p).count()
        drawn = Zone.objects.filter(patch=p).exclude(boundary_points__isnull=True).exclude(boundary_points=[]).count() + Zone.objects.filter(patch=p, boundary_source='dxf').exclude(dxf_boundary_points__isnull=True).exclude(dxf_boundary_points=[]).count()
        patch_stats.append({'name': p.name, 'total': total, 'drawn': drawn})
    total_all = Zone.objects.count()
    drawn_all = Zone.objects.exclude(boundary_points__isnull=True).exclude(boundary_points=[]).count() + Zone.objects.filter(boundary_source='dxf').exclude(dxf_boundary_points__isnull=True).exclude(dxf_boundary_points=[]).count()

    context = {
        'all_zones_json': json.dumps(all_zones),
        'all_drawn_zones_json': json.dumps(all_drawn_zones),
        'map_style_json': json.dumps(MapStyleSettings.get_style()),
        'patch_stats_json': json.dumps(patch_stats),
        'drawn_total': drawn_all,
        'zone_total': total_all,
    }
    return render(request, 'core/zone_quick_draw_mobile.html', context)


@login_required(login_url='core:login')
@ensure_csrf_cookie
def map_style_editor(request):
    """Map style customization page with live preview."""
    from .models import ManagerProfile, MapStyleSettings, Worker

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        try:
            Worker.objects.get(user=request.user, active=True)
        except Worker.DoesNotExist:
            messages.error(request, '无权限访问此页面')
            return redirect('core:dashboard')

    if request.method == 'POST':
        try:
            data = json.loads(request.body) if request.body else {}
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'message': '无效数据'}, status=400)
        MapStyleSettings.save_style(data, user=request.user)
        return JsonResponse({'success': True, 'message': '样式已保存'})

    # Load all drawn zones for map preview
    all_drawn_zones = []
    for z in Zone.objects.select_related('patch').only(
        'id', 'code', 'name', 'boundary_points', 'boundary_color',
        'label_lat', 'label_lng', 'label_scale', 'label_angle', 'smooth_override', 'patch_id', 'patch__name', 'current_status'
    ):
        center = None
        bp = z.active_boundary_points
        if bp:
            try:
                if isinstance(bp[0], list):
                    all_pts = [p for ring in bp for p in ring]
                else:
                    all_pts = bp
                if all_pts:
                    lats = [p[0] if isinstance(p, list) else p.get('lat', 0) for p in all_pts]
                    lngs = [p[1] if isinstance(p, list) else p.get('lng', 0) for p in all_pts]
                    center = {'lat': sum(lats) / len(lats), 'lng': sum(lngs) / len(lngs)}
            except Exception:
                pass

        all_drawn_zones.append({
            'id': z.id,
            'code': z.code,
            'name': z.name,
            'boundary_points': z.active_boundary_points,
            'boundary_color': z.boundary_color,
            'label_lat': z.label_lat,
            'label_lng': z.label_lng,
            'label_scale': z.label_scale,
            'label_angle': z.label_angle,
            'smooth_override': z.smooth_override,
            'status': z.current_status,
            'center': center,
        })

    current_style = MapStyleSettings.get_style()

    context = {
        'zones_json': json.dumps(all_drawn_zones),
        'map_style_json': json.dumps(current_style),
        'nav_quickdraw': 'active',
    }
    return render(request, 'core/map_style_editor.html', context)


@login_required(login_url='core:login')
@ensure_csrf_cookie
def zone_detail_page(request, zone_id):
    """Zone detail page showing all zone parameters, plants, equipment, notes, and stats."""
    import json
    from django.db.models import Sum
    from datetime import date, timedelta
    from .models import Plant, ZoneEquipment, WorkReport, WorkReportFault

    zone = get_object_or_404(Zone, pk=zone_id)
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)

    # Current plants
    plants = Plant.objects.filter(zone=zone).filter(
        Q(planting_date__lte=today) | Q(planting_date__isnull=True)
    ).filter(
        Q(end_date__gte=today) | Q(end_date__isnull=True)
    ).order_by('name')

    # Active equipment
    equipment = ZoneEquipment.objects.filter(zone=zone).select_related('equipment').filter(
        Q(installation_date__lte=today) | Q(installation_date__isnull=True)
    ).filter(status__in=['working', 'needs_repair'])

    plant_count = plants.count()
    equipment_count = equipment.count()
    work_report_count = WorkReport.objects.filter(zone_location=zone).count()

    recent_fault_count = WorkReportFault.objects.filter(
        work_report__zone_location=zone,
        work_report__date__gte=thirty_days_ago,
    ).aggregate(total=Sum('count'))['total'] or 0

    for eq in equipment:
        eq.status_display = eq.get_status_display()
        eq.equipment_details = {
            'equipment_type_display': eq.equipment.get_equipment_type_display(),
            'manufacturer': eq.equipment.manufacturer,
            'model_name': eq.equipment.model_name,
        }

    # Recent work reports
    recent_reports = WorkReport.objects.filter(zone_location=zone).select_related(
        'worker', 'work_category', 'location'
    ).order_by('-date', '-id')[:10]

    # Sibling zones (same patch)
    sibling_zones = []
    if zone.patch_id:
        sibling_zones = list(Zone.objects.filter(patch_id=zone.patch_id)
                             .exclude(pk=zone.pk).order_by('code')[:20])

    # Parse maintenance notes
    def _sort_notes(notes):
        def _sort_key(n):
            d = n.get('date', '')
            if not d or not isinstance(d, str) or d == '日期格式错误':
                return (1, '')
            return (0, d)
        return sorted(notes, key=_sort_key, reverse=True)

    try:
        equip_notes = _sort_notes(json.loads(zone.equipment_maintenance_notes)) if zone.equipment_maintenance_notes else []
    except (json.JSONDecodeError, TypeError):
        equip_notes = []
    try:
        irrig_notes = _sort_notes(json.loads(zone.irrigation_management_notes)) if zone.irrigation_management_notes else []
    except (json.JSONDecodeError, TypeError):
        irrig_notes = []
    try:
        remarks = _sort_notes(json.loads(zone.remarks)) if zone.remarks else []
    except (json.JSONDecodeError, TypeError):
        remarks = []
    try:
        confirmed_remarks = _sort_notes(json.loads(zone.confirmed_remarks)) if zone.confirmed_remarks else []
    except (json.JSONDecodeError, TypeError):
        confirmed_remarks = []
    is_manager = _check_zone_admin(request)

    # Priority display
    priority_display = dict(Zone.PRIORITY_CHOICES).get(zone.priority, '一般')
    status_display = zone.current_status if zone.current_status else '正常'

    context = {
        'zone': zone,
        'plants': plants,
        'equipment': equipment,
        'plant_count': plant_count,
        'equipment_count': equipment_count,
        'work_report_count': work_report_count,
        'recent_fault_count': recent_fault_count,
        'recent_reports': recent_reports,
        'sibling_zones': sibling_zones,
        'equip_notes': equip_notes,
        'irrig_notes': irrig_notes,
        'remarks': remarks,
        'confirmed_remarks': confirmed_remarks,
        'is_manager': is_manager,
        'today': today.isoformat(),
        'priority_display': priority_display,
        'status_display': status_display,
    }

    return render(request, 'core/zone_detail_page.html', context)


@login_required(login_url='core:login')
def zone_smooth_update(request, zone_id):
    """API: update per-zone smooth override. POST with {smooth_override: null|int}."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    if not _check_zone_admin(request):
        return JsonResponse({'error': '无权限'}, status=403)
    zone = get_object_or_404(Zone, pk=zone_id)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': '无效数据'}, status=400)
    val = data.get('smooth_override')
    zone.smooth_override = int(val) if val is not None else None
    zone.save(update_fields=['smooth_override', 'updated_at'])
    return JsonResponse({'success': True, 'smooth_override': zone.smooth_override})


@login_required(login_url='core:login')
def zone_remark_add(request, zone_id):
    import json
    from datetime import date as date_cls
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    zone = get_object_or_404(Zone, pk=zone_id)
    date = request.POST.get('date', '').strip()
    content = request.POST.get('content', '').strip()
    if not content:
        return JsonResponse({'error': '内容不能为空'}, status=400)
    if not date:
        date = date_cls.today().isoformat()
    author = _get_user_display_name(request)
    remarks = json.loads(zone.remarks) if zone.remarks else []
    remarks.insert(0, {'date': date, 'content': content, 'author': author})
    zone.remarks = json.dumps(remarks, ensure_ascii=False)
    zone.save(update_fields=['remarks'])
    return JsonResponse({'success': True, 'remark': {'date': date, 'content': content, 'author': author}})


@login_required(login_url='core:login')
def zone_remark_confirm(request, zone_id, index):
    import json
    from datetime import date as date_cls
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    if not _check_zone_admin(request):
        return JsonResponse({'error': '无权限'}, status=403)
    zone = get_object_or_404(Zone, pk=zone_id)
    remarks = json.loads(zone.remarks) if zone.remarks else []
    if index < 0 or index >= len(remarks):
        return JsonResponse({'error': '索引无效'}, status=400)
    remark = remarks.pop(index)
    confirm_reply = request.POST.get('confirm_reply', '').strip()
    confirm_author = _get_user_display_name(request)
    confirmed = {
        **remark,
        'confirm_date': date_cls.today().isoformat(),
        'confirm_reply': confirm_reply,
        'confirm_author': confirm_author,
    }
    confirmed_list = json.loads(zone.confirmed_remarks) if zone.confirmed_remarks else []
    confirmed_list.insert(0, confirmed)
    zone.remarks = json.dumps(remarks, ensure_ascii=False)
    zone.confirmed_remarks = json.dumps(confirmed_list, ensure_ascii=False)
    zone.save(update_fields=['remarks', 'confirmed_remarks'])
    return JsonResponse({'success': True, 'confirmed': confirmed})


@login_required(login_url='core:login')
def zone_remark_move(request, zone_id, index):
    import json
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    if not _check_zone_admin(request):
        return JsonResponse({'error': '无权限'}, status=403)
    zone = get_object_or_404(Zone, pk=zone_id)
    target = request.POST.get('target', '').strip()
    if target not in ('irrigation', 'equipment'):
        return JsonResponse({'error': '目标无效'}, status=400)
    confirmed_list = json.loads(zone.confirmed_remarks) if zone.confirmed_remarks else []
    if index < 0 or index >= len(confirmed_list):
        return JsonResponse({'error': '索引无效'}, status=400)
    entry = confirmed_list.pop(index)
    note = {'date': entry.get('date', ''), 'content': entry.get('content', '')}
    if target == 'irrigation':
        notes = json.loads(zone.irrigation_management_notes) if zone.irrigation_management_notes else []
        notes.insert(0, note)
        zone.irrigation_management_notes = json.dumps(notes, ensure_ascii=False)
        zone.save(update_fields=['irrigation_management_notes'])
    else:
        notes = json.loads(zone.equipment_maintenance_notes) if zone.equipment_maintenance_notes else []
        notes.insert(0, note)
        zone.equipment_maintenance_notes = json.dumps(notes, ensure_ascii=False)
        zone.save(update_fields=['equipment_maintenance_notes'])
    zone.confirmed_remarks = json.dumps(confirmed_list, ensure_ascii=False)
    zone.save(update_fields=['confirmed_remarks'])
    return JsonResponse({'success': True, 'target': target, 'note': note})


@login_required(login_url='core:login')
def pipeline_new(request):
    from .models import ManagerProfile, Pipeline

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        messages.error(request, '无权限创建水管')
        return redirect('core:dashboard')

    if request.method == 'POST':
        pipeline_type = request.POST.get('pipeline_type', Pipeline.TYPE_IRRIGATION)
        zone_ids = request.POST.getlist('zones')
        name, code = _auto_pipeline_name_code(zone_ids, pipeline_type)

        pipeline = Pipeline(
            name=name,
            code=code,
            description=request.POST.get('description', ''),
            pipeline_type=pipeline_type,
            line_weight=int(request.POST.get('line_weight', 3)),
        )

        line_json = request.POST.get('line_points', '[]')
        try:
            pipeline.line_points = json.loads(line_json)
        except json.JSONDecodeError:
            messages.error(request, '坐标数据格式无效')
            rz, rp = _get_reference_map_data()
            return render(request, 'core/pipeline_form.html', {
                'pipeline': pipeline,
                'line_json': line_json,
                'zones': Zone.objects.all().order_by('code'),
                'ref_zones_json': rz,
                'ref_pipelines_json': rp,
            })

        pipeline.save()

        if zone_ids:
            pipeline.zones.set(Zone.objects.filter(id__in=zone_ids))

        messages.success(request, f'水管 "{pipeline.name}" 创建成功')
        return redirect('core:settings')

    ref_zones_json, ref_pipelines_json = _get_reference_map_data()

    zones = Zone.objects.all().order_by('code')
    context = {
        'pipeline': None,
        'line_json': '[]',
        'zones': zones,
        'grouped_zones': _build_grouped_zones(zones),
        'ref_zones_json': ref_zones_json,
        'ref_pipelines_json': ref_pipelines_json,
    }
    return render(request, 'core/pipeline_form.html', context)


@login_required(login_url='core:login')
def pipeline_edit(request, pipeline_id):
    from .models import ManagerProfile, Pipeline

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        messages.error(request, '无权限修改水管')
        return redirect('core:dashboard')

    pipeline = get_object_or_404(Pipeline, pk=pipeline_id)

    if request.method == 'POST':
        pipeline_type = request.POST.get('pipeline_type', pipeline.pipeline_type)
        zone_ids = request.POST.getlist('zones')
        name, code = _auto_pipeline_name_code(zone_ids, pipeline_type)

        pipeline.name = name
        pipeline.code = code
        pipeline.pipeline_type = pipeline_type
        pipeline.line_weight = int(request.POST.get('line_weight', pipeline.line_weight))

        line_json = request.POST.get('line_points', '[]')
        try:
            pipeline.line_points = json.loads(line_json)
        except json.JSONDecodeError:
            messages.error(request, '坐标数据格式无效')
            return redirect('core:pipeline_edit', pipeline_id=pipeline.id)

        pipeline.save()

        pipeline.zones.set(Zone.objects.filter(id__in=zone_ids))
        pipeline.zones.set(Zone.objects.filter(id__in=zone_ids))

        messages.success(request, f'水管 "{pipeline.name}" 更新成功')
        return redirect('core:settings')

    ref_zones_json, ref_pipelines_json = _get_reference_map_data(exclude_pipeline_id=pipeline.id)

    zones = Zone.objects.all().order_by('code')
    context = {
        'pipeline': pipeline,
        'line_json': json.dumps(pipeline.line_points),
        'zones': zones,
        'grouped_zones': _build_grouped_zones(zones),
        'selected_zone_ids': list(pipeline.zones.values_list('id', flat=True)),
        'ref_zones_json': ref_zones_json,
        'ref_pipelines_json': ref_pipelines_json,
    }
    return render(request, 'core/pipeline_form.html', context)


@require_POST
@login_required(login_url='core:login')
def pipeline_delete(request, pipeline_id):
    from .models import ManagerProfile, Pipeline

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        messages.error(request, '无权限删除水管')
        return redirect('core:dashboard')

    pipeline = get_object_or_404(Pipeline, pk=pipeline_id)
    pipeline_name = pipeline.name
    pipeline.delete()
    messages.success(request, f'水管 "{pipeline_name}" 删除成功')
    return redirect('core:settings')


# ─── Region CRUD ───

@login_required(login_url='core:login')
def region_new(request):
    """Create a new region — admin only."""
    from .models import ManagerProfile, Region

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass
    if not is_admin:
        messages.error(request, '无权限')
        return redirect('core:dashboard')

    if request.method == 'POST':
        region = Region(
            name=request.POST['name'],
            description=request.POST.get('description', ''),
            order=int(request.POST.get('order', 0)),
            active=request.POST.get('active') is not None,
        )
        region.full_clean()
        region.save()
        messages.success(request, f'大区 "{region.name}" 创建成功')
        return redirect('core:settings')

    return render(request, 'core/region_form.html', {'mode': 'new'})


@login_required(login_url='core:login')
def region_edit(request, region_id):
    """Edit a region — admin only."""
    from .models import ManagerProfile, Region

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass
    if not is_admin:
        messages.error(request, '无权限')
        return redirect('core:dashboard')

    region = get_object_or_404(Region, pk=region_id)

    if request.method == 'POST':
        region.name = request.POST['name']
        region.description = request.POST.get('description', '')
        region.order = int(request.POST.get('order', 0))
        region.active = request.POST.get('active') is not None
        region.full_clean()
        region.save()
        messages.success(request, f'大区 "{region.name}" 更新成功')
        return redirect('core:settings')

    return render(request, 'core/region_form.html', {'mode': 'edit', 'region': region})


@login_required(login_url='core:login')
@require_POST
def region_delete(request, region_id):
    """Delete a region — admin only. Patches are SET_NULL."""
    from .models import ManagerProfile, Region

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass
    if not is_admin:
        messages.error(request, '无权限')
        return redirect('core:dashboard')

    region = get_object_or_404(Region, pk=region_id)
    region_name = region.name
    region.delete()
    messages.success(request, f'大区 "{region_name}" 已删除')
    return redirect('core:settings')


@login_required(login_url='core:login')
@require_POST
def batch_delete_region(request):
    """Batch delete regions — admin only."""
    from .models import ManagerProfile, Region
    try:
        body = json.loads(request.body)
        ids = body.get('ids', [])
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass
    if not is_admin:
        return JsonResponse({'error': '无权限'}, status=403)

    count, _ = Region.objects.filter(pk__in=ids).delete()
    messages.success(request, f'已删除 {count} 个大区')
    return JsonResponse({'success': True, 'deleted': count})


def _boundary_points_to_shapely(boundary_points):
    """Convert JSON boundary_points to a Shapely geometry."""
    from shapely.geometry import Polygon, MultiPolygon

    if not boundary_points or len(boundary_points) == 0:
        return None

    def to_coord(p):
        if isinstance(p, dict):
            return (p.get('lng', p.get('longitude', 0)), p.get('lat', p.get('latitude', 0)))
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            return (p[1], p[0])
        return None

    first = boundary_points[0]
    if isinstance(first, list) and len(first) > 0 and (isinstance(first[0], (list, dict))):
        rings = boundary_points
    elif isinstance(first, (dict, list)):
        rings = [boundary_points]
    else:
        return None

    polygons = []
    for ring in rings:
        coords = [to_coord(p) for p in ring]
        coords = [c for c in coords if c is not None]
        if len(coords) >= 3:
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            polygons.append(Polygon(coords))

    if len(polygons) == 0:
        return None
    if len(polygons) == 1:
        return polygons[0]
    return MultiPolygon(polygons)


def _recalculate_landmark_assignments():
    """Recalculate all zone↔landmark assignments based on boundary overlap."""
    try:
        from shapely.geometry import MultiPolygon as _MP  # noqa: F401 — verify import
    except ImportError:
        return -1

    from .models import Landmark, ZoneLandmarkAssignment, Zone

    ZoneLandmarkAssignment.objects.all().delete()

    landmarks = Landmark.objects.exclude(boundary_points=[])
    zones = Zone.objects.exclude(boundary_points=[])
    count = 0

    for landmark in landmarks:
        landmark_geom = _boundary_points_to_shapely(landmark.boundary_points)
        if landmark_geom is None:
            continue
        for zone in zones:
            zone_geom = _boundary_points_to_shapely(zone.boundary_points)
            if zone_geom is None:
                continue
            if landmark_geom.intersects(zone_geom):
                ZoneLandmarkAssignment.objects.create(zone=zone, landmark=landmark)
                count += 1

    return count


def _landmark_draw_context(landmark):
    """Build context for the landmark draw page with reference layers."""
    from .models import Landmark
    all_landmarks = []
    for lm in Landmark.objects.order_by('order', 'name'):
        all_landmarks.append({
            'id': lm.id,
            'name': lm.name,
            'boundary_points': lm.boundary_points,
            'boundary_color': lm.boundary_color,
            'area_sqm': lm.area_sqm,
        })
    all_zones = []
    for z in Zone.objects.select_related('patch').only(
        'id', 'code', 'name', 'boundary_points', 'boundary_color',
        'label_lat', 'label_lng', 'label_scale', 'label_angle', 'patch_id'
    ):
        all_zones.append({
            'id': z.id,
            'code': z.code,
            'name': z.name,
            'boundary_points': z.active_boundary_points,
            'boundary_color': z.boundary_color,
        })
    return {
        'landmark': landmark,
        'all_landmarks_json': json.dumps(all_landmarks),
        'all_zones_json': json.dumps(all_zones),
        'nav_settings': True,
    }


@login_required(login_url='core:login')
def landmark_new(request):
    from .models import Landmark
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            return JsonResponse({'error': '名称不能为空'}, status=400)
        boundary_raw = request.POST.get('boundary_points', '[]')
        boundary_color = request.POST.get('boundary_color', '#E8590C')
        try:
            boundary_data = json.loads(boundary_raw)
        except json.JSONDecodeError:
            return JsonResponse({'error': '边界数据格式错误'}, status=400)
        boundary_data = auto_close_boundary_points(boundary_data)
        landmark = Landmark(name=name, boundary_points=boundary_data, boundary_color=boundary_color)
        landmark.center = get_zone_center(boundary_data)
        landmark.save()
        return JsonResponse({'success': True, 'id': landmark.id, 'name': landmark.name})
    return render(request, 'core/landmark_draw.html', _landmark_draw_context(None))


@login_required(login_url='core:login')
def landmark_edit(request, landmark_id):
    from .models import Landmark
    landmark = get_object_or_404(Landmark, pk=landmark_id)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            landmark.name = name
        boundary_raw = request.POST.get('boundary_points', '')
        if boundary_raw:
            try:
                boundary_data = json.loads(boundary_raw)
                boundary_data = auto_close_boundary_points(boundary_data)
                landmark.boundary_points = boundary_data
                landmark.center = get_zone_center(boundary_data)
            except json.JSONDecodeError:
                return JsonResponse({'error': '边界数据格式错误'}, status=400)
        boundary_color = request.POST.get('boundary_color')
        if boundary_color:
            landmark.boundary_color = boundary_color
        landmark.save()
        return JsonResponse({'success': True, 'id': landmark.id, 'name': landmark.name})
    return render(request, 'core/landmark_draw.html', _landmark_draw_context(landmark))


@login_required(login_url='core:login')
@require_POST
def landmark_delete(request, landmark_id):
    from .models import Landmark
    landmark = get_object_or_404(Landmark, pk=landmark_id)
    landmark.delete()
    return JsonResponse({'success': True})


@login_required(login_url='core:login')
def landmarks_api(request):
    from .models import Landmark, ZoneLandmarkAssignment
    landmarks = Landmark.objects.order_by('order', 'name')
    data = []
    for lm in landmarks:
        zone_count = ZoneLandmarkAssignment.objects.filter(landmark=lm).count()
        data.append({
            'id': lm.id,
            'name': lm.name,
            'boundary_points': lm.boundary_points,
            'boundary_color': lm.boundary_color,
            'center': lm.center,
            'area_sqm': lm.area_sqm,
            'zone_count': zone_count,
        })
    return JsonResponse(data, safe=False)


@login_required(login_url='core:login')
@require_POST
def landmarks_recalculate(request):
    from .models import Landmark
    count = _recalculate_landmark_assignments()
    if count < 0:
        return JsonResponse({'error': 'Shapely library not installed. Run: pip install shapely'}, status=500)
    total_landmarks = Landmark.objects.count()
    return JsonResponse({'success': True, 'assignments': count, 'landmarks': total_landmarks})


@login_required(login_url='core:login')
@require_POST
def batch_delete_landmark(request):
    from .models import Landmark
    try:
        body = json.loads(request.body)
        ids = body.get('ids', [])
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    count, _ = Landmark.objects.filter(pk__in=ids).delete()
    return JsonResponse({'success': True, 'deleted': count})


@login_required(login_url='core:login')
def patch_new(request):
    """Create a new patch — admin only."""
    from .models import ManagerProfile, Patch

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        messages.error(request, '无权限创建片区')
        return redirect('core:dashboard')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()
        description = request.POST.get('description', '').strip()
        region_id = request.POST.get('region') or None

        if not name:
            messages.error(request, '片区名称不能为空')
        elif not code:
            messages.error(request, '片区编号不能为空')
        elif Patch.objects.filter(name=name).exists():
            messages.error(request, f'片区名称 "{name}" 已存在')
        elif Patch.objects.filter(code=code).exists():
            messages.error(request, f'片区编号 "{code}" 已存在')
        else:
            from .models import Region
            region = None
            if region_id:
                region = Region.objects.filter(pk=region_id).first()
            Patch.objects.create(name=name, code=code, description=description, region=region)
            messages.success(request, f'片区 "{name}" 创建成功')
            return redirect('core:settings')

    from .models import Region
    return render(request, 'core/patch_form.html', {
        'mode': 'new',
        'regions': Region.objects.order_by('order', 'name'),
    })


@login_required(login_url='core:login')
def patch_edit(request, patch_id):
    """Edit a patch with zone assignment — admin only."""
    from .models import ManagerProfile, Patch

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        messages.error(request, '无权限编辑片区')
        return redirect('core:dashboard')

    patch = get_object_or_404(Patch, pk=patch_id)

    # Fields that propagate from 片区 to linked child patches
    PROPAGATE_FIELDS = [
        'description', 'active', 'time_zone', 'water_pricing',
        'et_current', 'et_default', 'et_minimum', 'et_maximum',
        'crop_coefficient', 'rain_shutdown', 'date_open', 'date_close',
    ]

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()
        description = request.POST.get('description', '').strip()
        region_id = request.POST.get('region') or None

        # Validate uniqueness excluding self
        errors = []
        if not name:
            errors.append('片区名称不能为空')
        elif not code:
            errors.append('片区编号不能为空')
        elif Patch.objects.filter(name=name).exclude(pk=patch.pk).exists():
            errors.append(f'片区名称 "{name}" 已存在')
        elif Patch.objects.filter(code=code).exclude(pk=patch.pk).exists():
            errors.append(f'片区编号 "{code}" 已存在')

        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            from .models import Region
            patch.name = name
            patch.code = code
            patch.description = description
            patch.region_id = region_id
            patch.active = request.POST.get('active') is not None
            patch.time_zone = request.POST.get('time_zone', 'China')
            patch.water_pricing = request.POST.get('water_pricing') or None
            patch.et_current = request.POST.get('et_current') or None
            patch.et_default = request.POST.get('et_default') or None
            patch.et_minimum = request.POST.get('et_minimum') or None
            patch.et_maximum = request.POST.get('et_maximum') or None
            patch.crop_coefficient = request.POST.get('crop_coefficient') or None
            patch.rain_shutdown = request.POST.get('rain_shutdown') is not None
            patch.date_open = request.POST.get('date_open', '')
            patch.date_close = request.POST.get('date_close', '')
            patch.save()

            # Handle zone assignment
            all_zone_ids = request.POST.getlist('zones')
            Zone.objects.filter(patch=patch).exclude(id__in=all_zone_ids).update(patch=None)
            Zone.objects.filter(id__in=all_zone_ids, patch__isnull=True).update(patch=patch)
            Zone.objects.filter(id__in=all_zone_ids).exclude(patch=patch).update(patch=patch)

            # Handle linked patch assignment (location/zone_text only, stations managed by sync)
            linked_ids = request.POST.getlist('linked_patches')
            # Clear parent for children that were linked but are now unchecked
            Patch.objects.filter(parent=patch).exclude(
                id__in=linked_ids
            ).update(parent=None)
            # Set parent for newly checked patches
            Patch.objects.filter(id__in=linked_ids).update(parent=patch)

            # Propagate shared fields to all children
            children = patch.children.all()
            if children:
                update_kwargs = {}
                for f in PROPAGATE_FIELDS:
                    update_kwargs[f] = getattr(patch, f)
                children.update(**update_kwargs)

            messages.success(request, f'片区 "{name}" 已更新')
            return redirect('core:settings')

    # Build grouped zones for the zone picker
    all_zones = Zone.objects.all().order_by('code')
    grouped_zones = _build_grouped_zones(all_zones)

    # IDs of zones assigned to this patch (FK + derived from code prefix)
    selected_zone_ids = set()
    for group in grouped_zones:
        for z in group['zones']:
            if z['patch_id'] == patch.id:
                selected_zone_ids.add(z['id'])

    # Linked patches (children via parent FK)
    linked_patch_ids = set(patch.children.values_list('id', flat=True))
    linkable = Patch.objects.exclude(id=patch.id).order_by('code')
    linked_groups = [{
        'label': '关联片区',
        'patches': linkable,
    }] if linkable.exists() else []

    from .models import Region
    return render(request, 'core/patch_form.html', {
        'mode': 'edit',
        'patch': patch,
        'grouped_zones': grouped_zones,
        'selected_zone_ids': selected_zone_ids,
        'linked_patch_ids': linked_patch_ids,
        'linked_groups': linked_groups,
        'regions': Region.objects.order_by('order', 'name'),
    })


@login_required(login_url='core:login')
@require_POST
def patch_delete(request, patch_id):
    """Delete a patch — admin only. Zones are SET_NULL, not deleted."""
    from .models import ManagerProfile, Patch

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        messages.error(request, '无权限删除片区')
        return redirect('core:dashboard')

    patch = get_object_or_404(Patch, pk=patch_id)
    patch_name = patch.name
    patch.delete()
    messages.success(request, f'片区 "{patch_name}" 已删除')
    return redirect('core:settings')


@login_required(login_url='core:login')
@require_POST
def batch_delete_patch(request):
    """Batch delete patches — admin only."""
    from .models import ManagerProfile, Patch
    try:
        body = json.loads(request.body)
        ids = body.get('ids', [])
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass
    if not is_admin:
        return JsonResponse({'error': '无权限'}, status=403)

    count, _ = Patch.objects.filter(pk__in=ids).delete()
    messages.success(request, f'已删除 {count} 个片区')
    return JsonResponse({'success': True, 'deleted': count})


@login_required(login_url='core:login')
@require_POST
def batch_delete_zone(request):
    """Batch delete zones — admin only."""
    from .models import ManagerProfile, Zone
    try:
        body = json.loads(request.body)
        ids = body.get('ids', [])
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass
    if not is_admin:
        return JsonResponse({'error': '无权限'}, status=403)

    count, _ = Zone.objects.filter(pk__in=ids).delete()
    messages.success(request, f'已删除 {count} 个区域')
    return JsonResponse({'success': True, 'deleted': count})


@login_required(login_url='core:login')
@require_POST
def batch_delete_pipeline(request):
    """Batch delete pipelines — admin only."""
    from .models import ManagerProfile, Pipeline
    try:
        body = json.loads(request.body)
        ids = body.get('ids', [])
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass
    if not is_admin:
        return JsonResponse({'error': '无权限'}, status=403)

    count, _ = Pipeline.objects.filter(pk__in=ids).delete()
    messages.success(request, f'已删除 {count} 条水管')
    return JsonResponse({'success': True, 'deleted': count})


@login_required(login_url='core:login')
def equipment_catalog_autocomplete(request):
    """AJAX autocomplete endpoint for equipment catalog."""
    from .models import EquipmentCatalog

    equipment_type = request.GET.get('equipment_type', '')
    search = request.GET.get('search', '')

    queryset = EquipmentCatalog.objects.all()

    if equipment_type:
        queryset = queryset.filter(equipment_type=equipment_type)

    if search:
        queryset = queryset.filter(
            Q(model_name__icontains=search) |
            Q(manufacturer__icontains=search)
        )

    queryset = queryset.order_by('manufacturer', 'model_name')[:20]

    seen = set()
    results = []
    for item in queryset:
        key = (item.manufacturer, item.model_name)
        if key in seen:
            continue
        seen.add(key)
        label = f"{item.manufacturer} {item.model_name}" if item.manufacturer else item.model_name
        results.append({
            'id': item.id,
            'label': label,
            'model_name': item.model_name,
            'manufacturer': item.manufacturer,
            'equipment_type': item.equipment_type,
        })

    return JsonResponse({'results': results})


@login_required(login_url='core:login')
def requests_page(request):
    """工单管理 — manager inbox.

    A focused view for admins/managers showing four categories of items that
    need attention:
      1. 待修 workorders (with linked 计划性维修工单 when resolved)
      2. open 疑难 workorders
      3. zones with unconfirmed 备注 (inline confirm)
      4. pending-approval 工单/需求 (inline approve/reject)

    Non-admins are redirected. Replaces the old merged record list.
    """
    import json
    from core.models import (
        WorkReport, Zone, MaintenanceRequest, ProjectSupportRequest,
        WaterRequest, WorkOrder, ManagerProfile,
    )
    from django.contrib.auth.decorators import login_required
    from datetime import date

    user = request.user
    is_admin = user.is_superuser or user.is_staff
    if not is_admin:
        is_admin = ManagerProfile.objects.filter(user=user, active=True).exists()
    if not is_admin:
        messages.error(request, '无权限访问工单管理')
        return redirect('core:dashboard')

    show_resolved = bool(request.GET.get('show_resolved'))

    # ── 1. 待修 workorders ────────────────────────────────────────────────
    # Unresolved first; optionally include recently-resolved (with their PM link).
    pm_qs = WorkReport.objects.filter(is_pending_repair=True).select_related(
        'worker', 'location', 'resolved_by_pm').prefetch_related('zones').order_by('-date', '-id')
    pending_repairs = list(pm_qs)
    resolved_repairs = []
    if show_resolved:
        r_qs = WorkReport.objects.filter(
            is_pending_repair=False, resolved_by_pm__isnull=False
        ).select_related('worker', 'location', 'resolved_by_pm').prefetch_related(
            'zones').order_by('-resolved_by_pm__date', '-id')[:40]
        resolved_repairs = list(r_qs)

    # ── 2. open 疑难 workorders ───────────────────────────────────────────
    difficult_qs = WorkReport.objects.filter(
        is_difficult=True, is_difficult_resolved=False
    ).select_related('worker', 'location').prefetch_related('zones').order_by('-date', '-id')
    difficult_reports = list(difficult_qs)

    # ── 3. zones with unconfirmed 备注 ────────────────────────────────────
    remark_zones = []
    for z in Zone.objects.exclude(remarks='').exclude(remarks__isnull=True).order_by('code'):
        try:
            items = json.loads(z.remarks)
        except (ValueError, TypeError):
            continue
        if not items:
            continue
        parsed = []
        for idx, it in enumerate(items):
            if not isinstance(it, dict):
                continue
            parsed.append({
                'index': idx,
                'date': it.get('date', ''),
                'content': it.get('content', ''),
                'author': it.get('author', ''),
            })
        if parsed:
            remark_zones.append({
                'id': z.id, 'code': z.code, 'name': z.name or z.code,
                'remarks': parsed, 'count': len(parsed),
            })

    # ── 4. pending-approval 工单/需求 ────────────────────────────────────
    def _req_row(req, type_code, type_label):
        return {
            'id': req.id, 'type_code': type_code, 'type_label': type_label,
            'zone': req.zone.name if req.zone_id else '—',
            'zone_code': req.zone.code if req.zone_id else '',
            'submitter': req.submitter.full_name if getattr(req, 'submitter_id', None) and req.submitter else '—',
            'created_at': req.created_at,
            'detail': getattr(req, 'work_content', '') or getattr(req, 'request_type', '') or '',
            'status': req.status, 'status_display': req.get_status_display(),
        }

    pending_requests = []
    for r in MaintenanceRequest.objects.filter(status='submitted').select_related('zone', 'submitter').order_by('-created_at'):
        pending_requests.append(_req_row(r, 'maintenance', '维护维修'))
    for r in ProjectSupportRequest.objects.filter(status='submitted').select_related('zone', 'submitter').order_by('-created_at'):
        pending_requests.append(_req_row(r, 'project_support', '项目支持'))
    for r in WaterRequest.objects.filter(status='submitted').select_related('zone', 'submitter').order_by('-created_at'):
        pending_requests.append(_req_row(r, 'water', '浇水协调'))
    pending_requests.sort(key=lambda x: x['created_at'], reverse=True)

    # WorkOrder pending (no approve endpoint — read-only count + list)
    pending_workorders = list(WorkOrder.objects.filter(status='pending').select_related('zone', 'assigned_to').order_by('-created_at')[:50])

    context = {
        'pending_repairs': pending_repairs,
        'resolved_repairs': resolved_repairs,
        'show_resolved': show_resolved,
        'difficult_reports': difficult_reports,
        'remark_zones': remark_zones,
        'pending_requests': pending_requests,
        'pending_workorders': pending_workorders,
        'counts': {
            'repairs': len(pending_repairs),
            'difficult': len(difficult_reports),
            'remarks': sum(z['count'] for z in remark_zones),
            'approvals': len(pending_requests) + len(pending_workorders),
        },
        'is_admin': True,
    }
    return render(request, 'core/requests.html', context)


def request_detail(request, type_code, request_id):
    """
    工单详情页面
    """
    from core.models import (
        MaintenanceRequest, ProjectSupportRequest, WaterRequest,
        ManagerProfile, DepartmentUserProfile, Worker
    )
    from django.utils import timezone

    # Determine role
    is_admin = request.user.is_superuser or request.user.is_staff
    current_worker = None
    current_dept_user = None

    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        try:
            current_worker = Worker.objects.get(user=request.user, active=True)
        except Worker.DoesNotExist:
            pass

    if not is_admin and not current_worker:
        try:
            current_dept_user = DepartmentUserProfile.objects.get(user=request.user, active=True)
        except DepartmentUserProfile.DoesNotExist:
            pass

    # For maintenance and project_support, dept users cannot access
    if type_code in ['maintenance', 'project_support'] and current_dept_user:
        messages.error(request, '无权限查看此工单')
        return redirect('core:requests')

    # 获取对应的请求
    try:
        if type_code == 'maintenance':
            req = MaintenanceRequest.objects.select_related('zone', 'submitter', 'approver').get(pk=request_id)
            type_name = '维护与维修'
            extra_info = {
                'date': req.date,
                'start_time': req.start_time,
                'end_time': req.end_time,
                'participants': req.participants,
                'work_content': req.work_content,
                'materials': req.materials,
                'feedback': req.feedback,
                'photos': req.photos or [],
            }
        elif type_code == 'project_support':
            req = ProjectSupportRequest.objects.select_related('zone', 'submitter', 'approver').get(pk=request_id)
            type_name = '项目支持'
            extra_info = {
                'date': req.date,
                'start_time': req.start_time,
                'end_time': req.end_time,
                'participants': req.participants,
                'work_content': req.work_content,
                'materials': req.materials,
                'feedback': req.feedback,
                'photos': req.photos or [],
            }
        elif type_code == 'water':
            req = WaterRequest.objects.select_related('zone', 'submitter', 'approver').get(pk=request_id)
            type_name = '浇水协调需求'
            extra_info = {
                'user_type': req.get_user_type_display(),
                'user_type_other': req.user_type_other,
                'request_type': req.get_request_type_display(),
                'request_type_other': req.request_type_other,
                'start_datetime': req.start_datetime,
                'end_datetime': req.end_datetime,
                'photos': req.photos or [],
            }
        else:
            raise ValueError('Invalid type')
    except Exception as e:
        messages.error(request, f'请求不存在: {e}')
        return redirect('core:requests')

    # Check permissions - field workers can only see their own requests
    if not is_admin:
        if current_worker and hasattr(req, 'submitter') and req.submitter != current_worker:
            messages.error(request, '无权限查看此工单')
            return redirect('core:requests')

    context = {
        'req': req,
        'type_code': type_code,
        'type_name': type_name,
        'extra_info': extra_info,
        'is_admin': is_admin,
        'current_worker': current_worker,
        'current_dept_user': current_dept_user,
    }

    return render(request, 'core/request_detail.html', context)


@require_POST
@login_required(login_url='core:login')
def update_request_status(request, type_code, request_id):
    """更新工单状态 - 仅限管理员操作"""
    from core.models import (
        MaintenanceRequest, ProjectSupportRequest, WaterRequest,
        ManagerProfile, Worker
    )
    from django.utils import timezone

    # Check admin permission
    is_admin = request.user.is_superuser or request.user.is_staff

    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        messages.error(request, '无权限操作')
        return redirect('core:request_detail', type_code=type_code, request_id=request_id)

    # 获取 approver（Worker 或 None）
    try:
        approver = Worker.objects.get(user=request.user, active=True)
    except Worker.DoesNotExist:
        approver = None

    new_status = request.POST.get('status')
    status_notes = request.POST.get('status_notes', '')

    if new_status not in ['approved', 'rejected', 'info_needed']:
        messages.error(request, '无效的状态')
        return redirect('core:request_detail', type_code=type_code, request_id=request_id)

    # 获取对应的请求
    try:
        if type_code == 'maintenance':
            req = MaintenanceRequest.objects.get(pk=request_id)
        elif type_code == 'project_support':
            req = ProjectSupportRequest.objects.get(pk=request_id)
        elif type_code == 'water':
            req = WaterRequest.objects.get(pk=request_id)
        else:
            raise ValueError('Invalid type')
    except Exception as e:
        messages.error(request, f'请求不存在: {e}')
        return redirect('core:requests')

    req.status = new_status
    req.status_notes = status_notes
    req.approver = approver
    req.processed_at = timezone.now()
    req.save()

    status_names = {
        'approved': '已批准',
        'rejected': '已拒绝',
        'info_needed': '需补充信息',
    }
    messages.success(request, f'工单状态已更新为: {status_names[new_status]}')
    return redirect('core:request_detail', type_code=type_code, request_id=request_id)


def register(request):
    """
    User registration page - submit request for admin approval.

    Department type determines role:
    - 园艺一线 (field_worker) → Field Worker
    - 园艺经理 (manager) → Manager
    - 其他部门 (dept_user) → Department User (requires sub-department selection)
    """
    from core.models import RegistrationRequest, ROLE_FIELD_WORKER, ROLE_DEPT_USER, ROLE_MANAGER
    from django.contrib.auth.hashers import make_password
    from django.contrib.auth.models import User

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        phone = request.POST.get('phone', '').strip()
        employee_id = request.POST.get('employee_id', '').strip()
        department_type = request.POST.get('department_type', '').strip()
        requested_role = request.POST.get('requested_role', ROLE_FIELD_WORKER).strip()
        department = request.POST.get('department', '').strip()
        department_other = request.POST.get('department_other', '').strip()

        # Map department_type to role if needed
        if department_type == 'field_worker':
            requested_role = ROLE_FIELD_WORKER
        elif department_type == 'manager':
            requested_role = ROLE_MANAGER
        elif department_type == 'dept_user':
            requested_role = ROLE_DEPT_USER

        # Valid role choices
        valid_roles = [ROLE_FIELD_WORKER, ROLE_DEPT_USER, ROLE_MANAGER]

        # Validation
        if not full_name:
            messages.error(request, '请输入姓名')
        elif not username:
            messages.error(request, '请输入用户名')
        elif len(username) < 3:
            messages.error(request, '用户名至少需要3个字符')
        elif User.objects.filter(username=username).exists():
            messages.error(request, '该用户名已存在')
        elif not password:
            messages.error(request, '请输入密码')
        elif len(password) < 6:
            messages.error(request, '密码至少需要6个字符')
        elif not phone:
            messages.error(request, '请输入手机号')
        elif not department_type:
            messages.error(request, '请选择部门')
        elif requested_role not in valid_roles:
            messages.error(request, '请选择有效的角色')
        elif department_type == 'dept_user' and not department:
            messages.error(request, '请选择所属部门')
        elif department == '其他' and not department_other:
            messages.error(request, '请输入其他部门名称')
        elif RegistrationRequest.objects.filter(username=username).exists():
            messages.error(request, '该用户名已有待审批的注册申请')
        elif RegistrationRequest.objects.filter(phone=phone, status='pending').exists():
            messages.error(request, '该手机号已有待审批的注册申请')
        else:
            # For non-dept users, clear department info
            if department_type != 'dept_user':
                department = ''
                department_other = ''

            RegistrationRequest.objects.create(
                full_name=full_name,
                username=username,
                password=make_password(password),  # Hash the password
                phone=phone,
                employee_id=employee_id,
                department=department,
                department_other=department_other if department == '其他' else '',
                requested_role=requested_role,
            )
            messages.success(request, '注册申请已提交，请等待管理员审批')
            return redirect('core:register')

    return render(request, 'core/register.html')


@login_required(login_url='core:login')
def registration_approval(request):
    """
    Registration approval page for admins/managers.
    Shows pending registration requests with approve/reject actions.
    Uses applicant-submitted username and password.
    """
    from django.contrib.auth.models import User
    from core.models import (
        RegistrationRequest, ManagerProfile, DepartmentUserProfile, Worker,
        ROLE_MANAGER, ROLE_FIELD_WORKER, ROLE_DEPT_USER
    )
    from core.role_utils import is_admin

    # Check admin permission
    if not is_admin(request.user):
        messages.error(request, '无权限访问此页面')
        return redirect('core:dashboard')

    # Handle POST actions
    if request.method == 'POST':
        request_id = request.POST.get('request_id')
        action = request.POST.get('action')
        reason = request.POST.get('reason', '')

        try:
            reg = RegistrationRequest.objects.get(pk=request_id, status='pending')

            if action == 'approve':
                # Use submitted username and password
                username = reg.username
                password = reg.password  # Already hashed during submission

                # Generate employee_id
                if reg.requested_role == ROLE_MANAGER:
                    prefix = 'ADM'
                    model_class = ManagerProfile
                elif reg.requested_role == ROLE_DEPT_USER:
                    prefix = 'DEPT'
                    model_class = DepartmentUserProfile
                else:
                    prefix = 'EMP'
                    model_class = Worker

                # Use submitted employee_id if provided, otherwise auto-generate
                if reg.employee_id:
                    employee_id = reg.employee_id
                else:
                    # Find max employee_id number by scanning all records
                    max_num = 0
                    for profile in model_class.objects.all():
                        eid = profile.employee_id or ''
                        if eid.startswith(prefix):
                            try:
                                num = int(eid[len(prefix):])
                                if num > max_num:
                                    max_num = num
                            except ValueError:
                                continue

                    next_num = max_num + 1
                    employee_id = f'{prefix}{next_num:03d}'

                # Create Django User with submitted credentials
                user = User.objects.create(
                    username=username,
                    password=password,  # Already hashed
                    first_name=reg.full_name,
                )

                # Create profile based on role
                if reg.requested_role == ROLE_MANAGER:
                    ManagerProfile.objects.create(
                        user=user,
                        employee_id=employee_id,
                        full_name=reg.full_name,
                        phone=reg.phone,
                        is_super_admin=False,
                        can_approve_registrations=True,
                        can_approve_work_orders=True,
                    )
                elif reg.requested_role == ROLE_DEPT_USER:
                    DepartmentUserProfile.objects.create(
                        user=user,
                        employee_id=employee_id,
                        full_name=reg.full_name,
                        phone=reg.phone,
                        department=reg.department or 'ENT',
                        department_other=reg.department_other if reg.department == '其他' else '',
                    )
                else:  # field_worker
                    Worker.objects.create(
                        user=user,
                        employee_id=employee_id,
                        full_name=reg.full_name,
                        phone=reg.phone,
                        department=reg.department or '',
                        department_other=reg.department_other if reg.department == '其他' else '',
                    )

                # Update registration
                reg.status = 'approved'
                reg.employee_id = employee_id
                reg.processed_at = timezone.now()
                reg.created_user = user
                reg.save()

                messages.success(request, f'已批准 {reg.full_name} 的注册申请，用户名：{username}，工号：{employee_id}')

            elif action == 'reject':
                reg.status = 'rejected'
                reg.status_notes = reason
                reg.processed_at = timezone.now()
                reg.save()
                messages.success(request, f'已拒绝 {reg.full_name} 的注册申请')

        except RegistrationRequest.DoesNotExist:
            messages.error(request, '注册申请不存在')

        return redirect('core:registration_approval')

    # GET request - show list
    filter_status = request.GET.get('filter', 'pending')

    if filter_status == 'all':
        requests_qs = RegistrationRequest.objects.all()
    else:
        requests_qs = RegistrationRequest.objects.filter(status=filter_status)

    requests_qs = requests_qs.order_by('-created_at')

    # Stats
    stats = {
        'pending': RegistrationRequest.objects.filter(status='pending').count(),
        'approved': RegistrationRequest.objects.filter(status='approved').count(),
        'rejected': RegistrationRequest.objects.filter(status='rejected').count(),
    }

    context = {
        'requests': requests_qs,
        'stats': stats,
        'filter': filter_status,
    }

    return render(request, 'core/registration_approval.html', context)


@login_required(login_url='core:login')
def user_management(request):
    """
    User management page with two tabs: User List and Registration Approval.
    """
    from django.contrib.auth.models import User
    from core.models import (
        RegistrationRequest, ManagerProfile, DepartmentUserProfile, Worker,
        ROLE_MANAGER, ROLE_FIELD_WORKER, ROLE_DEPT_USER,
        ROLE_SUPER_ADMIN
    )
    from core.role_utils import is_admin

    if not is_admin(request.user):
        messages.error(request, '无权限访问此页面')
        return redirect('core:dashboard')

    # Handle POST actions (registration approval/rejection)
    if request.method == 'POST':
        request_id = request.POST.get('request_id')
        action = request.POST.get('action')
        reason = request.POST.get('reason', '')

        try:
            reg = RegistrationRequest.objects.get(pk=request_id, status='pending')

            if action == 'approve':
                username = reg.username
                password = reg.password

                if reg.requested_role == ROLE_MANAGER:
                    prefix = 'ADM'
                    model_class = ManagerProfile
                elif reg.requested_role == ROLE_DEPT_USER:
                    prefix = 'DEPT'
                    model_class = DepartmentUserProfile
                else:
                    prefix = 'EMP'
                    model_class = Worker

                if reg.employee_id:
                    employee_id = reg.employee_id
                else:
                    max_num = 0
                    for profile in model_class.objects.all():
                        eid = profile.employee_id or ''
                        if eid.startswith(prefix):
                            try:
                                num = int(eid[len(prefix):])
                                if num > max_num:
                                    max_num = num
                            except ValueError:
                                continue
                    next_num = max_num + 1
                    employee_id = f'{prefix}{next_num:03d}'

                user = User.objects.create(
                    username=username,
                    password=password,
                    first_name=reg.full_name,
                )

                if reg.requested_role == ROLE_MANAGER:
                    ManagerProfile.objects.create(
                        user=user, employee_id=employee_id,
                        full_name=reg.full_name, phone=reg.phone,
                        is_super_admin=False,
                        can_approve_registrations=True,
                        can_approve_work_orders=True,
                    )
                elif reg.requested_role == ROLE_DEPT_USER:
                    DepartmentUserProfile.objects.create(
                        user=user, employee_id=employee_id,
                        full_name=reg.full_name, phone=reg.phone,
                        department=reg.department or 'ENT',
                        department_other=reg.department_other if reg.department == '其他' else '',
                    )
                else:
                    Worker.objects.create(
                        user=user, employee_id=employee_id,
                        full_name=reg.full_name, phone=reg.phone,
                        department=reg.department or '',
                        department_other=reg.department_other if reg.department == '其他' else '',
                    )

                reg.status = 'approved'
                reg.employee_id = employee_id
                reg.processed_at = timezone.now()
                reg.created_user = user
                reg.save()
                messages.success(request, f'已批准 {reg.full_name} 的注册申请，用户名：{username}，工号：{employee_id}')

            elif action == 'reject':
                reg.status = 'rejected'
                reg.status_notes = reason
                reg.processed_at = timezone.now()
                reg.save()
                messages.success(request, f'已拒绝 {reg.full_name} 的注册申请')

        except RegistrationRequest.DoesNotExist:
            messages.error(request, '注册申请不存在')

        return redirect('/user-management/?tab=approval')

    # GET request
    active_tab = request.GET.get('tab', 'users')
    filter_status = request.GET.get('filter', 'pending')

    # Zone draw counts per user
    draw_counts = {}
    for row in Zone.objects.exclude(drawn_by__isnull=True).values('drawn_by').annotate(cnt=Count('id')):
        draw_counts[row['drawn_by']] = row['cnt']
    drawn_zone_map = {}
    for z in Zone.objects.exclude(drawn_by__isnull=True).exclude(boundary_points=[]).select_related('patch').order_by('code'):
        uid = z.drawn_by_id
        drawn_zone_map.setdefault(uid, []).append({'code': z.code, 'name': z.name or z.code, 'patch': z.patch.name if z.patch else ''})

    # Build user list
    users_list = []

    for mp in ManagerProfile.objects.select_related('user').all():
        users_list.append({
            'profile_type': 'manager',
            'profile_id': mp.id,
            'user_id': mp.user.id if mp.user else None,
            'username': mp.user.username if mp.user else '-',
            'full_name': mp.full_name,
            'employee_id': mp.employee_id,
            'phone': mp.phone,
            'department': '',
            'role': ROLE_SUPER_ADMIN if mp.is_super_admin else ROLE_MANAGER,
            'role_display': '超级管理员' if mp.is_super_admin else '管理员',
            'active': mp.active,
            'drawn_zones': draw_counts.get(mp.user.id, 0) if mp.user else 0,
        })

    for dup in DepartmentUserProfile.objects.select_related('user').all():
        users_list.append({
            'profile_type': 'dept_user',
            'profile_id': dup.id,
            'user_id': dup.user.id if dup.user else None,
            'username': dup.user.username if dup.user else '-',
            'full_name': dup.full_name,
            'employee_id': dup.employee_id,
            'phone': dup.phone,
            'department': dup.get_department_display_name() if hasattr(dup, 'get_department_display_name') else (dup.department_other or dup.department),
            'role': ROLE_DEPT_USER,
            'role_display': '部门用户',
            'active': dup.active,
            'drawn_zones': draw_counts.get(dup.user.id, 0) if dup.user else 0,
        })

    for w in Worker.objects.select_related('user').all():
        users_list.append({
            'profile_type': 'worker',
            'profile_id': w.id,
            'user_id': w.user.id if w.user else None,
            'username': w.user.username if w.user else '-',
            'full_name': w.full_name,
            'employee_id': w.employee_id,
            'phone': w.phone,
            'department': w.get_department_display_name() if hasattr(w, 'get_department_display_name') else (w.department_other or w.department),
            'role': ROLE_FIELD_WORKER,
            'role_display': '灌溉一线',
            'active': w.active,
            'drawn_zones': draw_counts.get(w.user.id, 0) if w.user else 0,
        })

    users_list.sort(key=lambda x: x['full_name'])

    # Registration approval data
    if filter_status == 'all':
        requests_qs = RegistrationRequest.objects.all()
    else:
        requests_qs = RegistrationRequest.objects.filter(status=filter_status)
    requests_qs = requests_qs.order_by('-created_at')

    stats = {
        'pending': RegistrationRequest.objects.filter(status='pending').count(),
        'approved': RegistrationRequest.objects.filter(status='approved').count(),
        'rejected': RegistrationRequest.objects.filter(status='rejected').count(),
    }

    context = {
        'active_tab': active_tab,
        'filter': filter_status,
        'users_list': users_list,
        'total_users': len(users_list),
        'active_users': sum(1 for u in users_list if u['active']),
        'inactive_users': sum(1 for u in users_list if not u['active']),
        'requests': requests_qs,
        'stats': stats,
        'drawn_zone_map_json': json.dumps(drawn_zone_map),
    }

    return render(request, 'core/user_management.html', context)


@login_required(login_url='core:login')
def user_edit(request, profile_type, profile_id):
    """Edit user profile via AJAX."""
    from core.role_utils import is_admin
    from core.models import ManagerProfile, DepartmentUserProfile, Worker

    if not is_admin(request.user):
        return JsonResponse({'error': '无权限'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    model_map = {
        'manager': ManagerProfile,
        'dept_user': DepartmentUserProfile,
        'worker': Worker,
    }
    model_class = model_map.get(profile_type)
    if not model_class:
        return JsonResponse({'error': 'Invalid profile type'}, status=400)

    profile = get_object_or_404(model_class, pk=profile_id)

    if 'full_name' in request.POST:
        profile.full_name = request.POST['full_name']
    if 'phone' in request.POST:
        profile.phone = request.POST['phone']
    if 'active' in request.POST:
        profile.active = request.POST['active'] in ('true', '1', 'True')
    if profile_type in ('worker', 'dept_user') and 'department' in request.POST:
        dept = request.POST['department']
        profile.department = dept
        if dept == '其他' and 'department_other' in request.POST:
            profile.department_other = request.POST['department_other']
        else:
            profile.department_other = ''

    profile.save()
    return JsonResponse({'success': True, 'message': f'已更新 {profile.full_name}'})


@login_required(login_url='core:login')
def user_preferences_api(request):
    """GET/PUT user preferences (e.g. zone card field visibility)."""
    from .models import ManagerProfile

    if not request.user.is_authenticated:
        return JsonResponse({'preferences': {}})

    profile = None
    try:
        profile = ManagerProfile.objects.get(user=request.user, active=True)
    except ManagerProfile.DoesNotExist:
        pass

    # For users without a ManagerProfile, use a simple request.session fallback
    if profile is None:
        if request.method == 'GET':
            return JsonResponse({'preferences': request.session.get('preferences', {})})
        if request.method in ('PUT', 'POST'):
            import json as _json
            try:
                data = _json.loads(request.body) if request.body else {}
            except _json.JSONDecodeError:
                data = {}
            request.session['preferences'] = data.get('preferences', {})
            request.session.save()
            return JsonResponse({'success': True, 'preferences': request.session['preferences']})
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    if request.method == 'GET':
        return JsonResponse({'preferences': profile.preferences or {}})

    if request.method in ('PUT', 'POST'):
        import json as _json
        try:
            data = _json.loads(request.body) if request.body else {}
        except _json.JSONDecodeError:
            data = {}
        profile.preferences = data.get('preferences', {})
        profile.save(update_fields=['preferences', 'updated_at'])
        return JsonResponse({'success': True, 'preferences': profile.preferences})

    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required(login_url='core:login')
def maxicom_dashboard_api(request):
    """API endpoint providing Maxicom2 irrigation data for the dashboard."""
    from core.models import (
        MaxicomController, MaxicomSchedule,
        MaxicomFlowZone, MaxicomWeatherStation, MaxicomWeatherLog,
        MaxicomEvent, MaxicomETCheckbook, MaxicomRuntime,
        Patch,
    )

    # System overview stats
    stats = {
        'sites': Patch.objects.count(),
        'controllers': MaxicomController.objects.count(),
        'stations': Patch.objects.filter(parent__isnull=False).count(),
        'schedules': MaxicomSchedule.objects.count(),
        'flow_zones': MaxicomFlowZone.objects.count(),
        'weather_stations': MaxicomWeatherStation.objects.count(),
        'weather_logs': MaxicomWeatherLog.objects.count(),
        'events': MaxicomEvent.objects.count(),
        'locked_stations': Patch.objects.filter(parent__isnull=False, lockout=True).count(),
    }

    # Site hierarchy: sites with controller/station counts and station details
    sites = []
    for site in Patch.objects.filter(parent__isnull=True).all():
        ctrl_count = site.controllers.count()
        stn_count = site.children.count()
        sched_count = site.schedules.count()
        fz_count = site.flow_zones.count()

        # Station details for hierarchy table
        station_list = []
        for stn in site.children.all():
            station_list.append({
                'id': stn.id,
                'name': stn.name or f'点位 {stn.controller_channel}',
                'controller_channel': stn.controller_channel,
                'controller_name': '-',
                'precip_rate': stn.precip_rate,
                'flow_rate': stn.flow_rate,
                'cycle_time': stn.cycle_time,
                'soak_time': stn.soak_time,
                'lockout': stn.lockout,
                'memo': stn.description,
            })

        sites.append({
            'id': site.id,
            'mdb_index': site.mdb_index,
            'name': site.name,
            'site_number': site.site_number,
            'et_current': site.et_current,
            'et_default': site.et_default,
            'water_pricing': site.water_pricing,
            'rain_shutdown': site.rain_shutdown,
            'controller_count': ctrl_count,
            'station_count': stn_count,
            'schedule_count': sched_count,
            'flow_zone_count': fz_count,
            'stations': station_list,
        })

    # Recent events (last 50)
    recent_events = []
    for ev in MaxicomEvent.objects.all()[:50]:
        recent_events.append({
            'timestamp': ev.timestamp,
            'source': ev.source,
            'flag': ev.flag,
            'text': ev.text,
        })

    # Weather summary: latest reading per station
    weather_summary = []
    for ws in MaxicomWeatherStation.objects.all():
        latest = ws.readings.order_by('-timestamp').first()
        if latest:
            weather_summary.append({
                'station': ws.name,
                'timestamp': latest.timestamp,
                'temperature': latest.temperature,
                'humidity': latest.humidity,
                'rainfall': latest.rainfall,
                'et': latest.et,
                'wind_run': latest.wind_run,
                'solar_radiation': latest.solar_radiation,
            })

    # ET trend: last 30 days of ET readings aggregated by day
    et_trend = []
    et_readings = MaxicomWeatherLog.objects.order_by('-timestamp')[:720]  # ~30 days * 24hrs
    et_by_date = {}
    for r in et_readings:
        ts = r.timestamp or ''
        if len(ts) >= 8:
            date_str = ts[:8]  # YYYYMMDD
            if date_str not in et_by_date:
                et_by_date[date_str] = []
            if r.et is not None:
                et_by_date[date_str].append(r.et)
    for date_str in sorted(et_by_date.keys()):
        vals = et_by_date[date_str]
        et_trend.append({
            'date': f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}",
            'avg_et': round(sum(vals) / len(vals), 3) if vals else 0,
            'count': len(vals),
        })

    # Station status breakdown
    station_status = {
        'total': Patch.objects.filter(parent__isnull=False).count(),
        'locked': Patch.objects.filter(parent__isnull=False, lockout=True).count(),
        'active': Patch.objects.filter(parent__isnull=False, lockout=False).count(),
    }

    # Top sites by station count
    top_sites = sorted(sites, key=lambda x: x['station_count'], reverse=True)[:10]

    # ET Checkbook latest
    et_checkbook_latest = []
    for ec in MaxicomETCheckbook.objects.select_related('site').order_by('-timestamp')[:20]:
        et_checkbook_latest.append({
            'site': ec.site.name,
            'timestamp': ec.timestamp,
            'soil_moisture': ec.soil_moisture,
            'rainfall': ec.rainfall,
            'et': ec.et,
            'irrigation': ec.irrigation,
        })

    return JsonResponse({
        'stats': stats,
        'sites': sites,
        'recent_events': recent_events,
        'weather_summary': weather_summary,
        'et_trend': et_trend,
        'station_status': station_status,
        'top_sites': top_sites,
        'et_checkbook': et_checkbook_latest,
    })


# ==========================================================================
# 维修工单系统 Views
# ==========================================================================


@login_required(login_url='core:login')
def stats_dashboard(request):
    """Data statistics dashboard with weekly work report stats and demand stats."""
    from core.models import WorkReport, WorkReportEntry, WorkItem, DemandRecord, Patch
    from core.role_utils import is_admin
    from django.db.models import Count, Q, Sum
    from django.utils import timezone
    from datetime import datetime, timedelta, date
    from collections import defaultdict

    user = request.user
    admin = is_admin(user)

    # === Work Report Weekly Stats ===
    week_param = request.GET.get('week')
    if week_param:
        try:
            week_start = datetime.strptime(week_param, '%Y-%m-%d').date()
            week_start = week_start - timedelta(days=week_start.weekday())
        except Exception:
            week_start = timezone.now().date() - timedelta(days=timezone.now().date().weekday())
    else:
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())

    week_end = week_start + timedelta(days=6)
    week_number = week_start.isocalendar()[1]

    # Generate week options
    years = []
    year_weeks = {}
    current_year = timezone.now().date().year

    for year in [current_year - 1, current_year, current_year + 1]:
        weeks = []
        jan_1 = date(year, 1, 1)
        first_monday = jan_1
        while first_monday.weekday() != 0:
            first_monday = first_monday + timedelta(days=1)

        week_start_iter = first_monday
        week_num = 1

        while week_start_iter.year == year or (week_start_iter.year == year + 1 and week_start_iter.month == 1 and week_num <= 53):
            week_end_iter = week_start_iter + timedelta(days=6)
            weeks.append({
                'week': week_num,
                'start': week_start_iter,
                'end': week_end_iter
            })
            week_start_iter = week_start_iter + timedelta(days=7)
            week_num += 1
            if week_num > 53:
                break

        if weeks:
            years.append(year)
            year_weeks[year] = weeks

    # Base queryset for this week
    week_qs = WorkReport.objects.select_related('worker', 'location', 'work_category')
    if not admin:
        try:
            worker = user.worker_profile
            week_qs = week_qs.filter(worker=worker)
        except Exception:
            week_qs = week_qs.none()

    week_qs = week_qs.filter(date__gte=week_start, date__lte=week_end)

    total_this_week = week_qs.count()

    reports_by_day = []
    for i in range(7):
        day = week_start + timedelta(days=i)
        count = week_qs.filter(date=day).count()
        reports_by_day.append({
            'date': day.strftime('%m-%d'),
            'weekday': ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][i],
            'count': count
        })

    reports_by_location = list(
        week_qs.values('location__name', 'location__code')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )

    reports_by_zone = list(
        week_qs.values('zone_location__name', 'zone_location__code')
        .annotate(count=Count('id'))
        .exclude(zone_location__isnull=True)
        .order_by('-count')[:10]
    )

    reports_by_category = list(
        week_qs.values('work_category__name', 'work_category__code')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )

    top_faults = list(
        week_qs.filter(fault_entries__isnull=False)
        .values('fault_entries__fault_subtype__name_zh', 'fault_entries__fault_subtype__category__name_zh')
        .annotate(count=Count('fault_entries__fault_subtype'))
        .order_by('-count')[:10]
    )

    # Zone-Fault Type Matrix
    fault_entries_data = list(
        week_qs.filter(fault_entries__isnull=False)
        .values('zone_location__code', 'zone_location__name', 'fault_entries__fault_subtype__name_zh')
        .annotate(count=Count('fault_entries__fault_subtype'))
    )

    fault_types_set = set()
    zones_dict = defaultdict(lambda: defaultdict(int))

    for entry in fault_entries_data:
        zone_code = entry.get('zone_location__code') or '未指定'
        zone_name = entry.get('zone_location__name') or zone_code
        fault_type = entry.get('fault_entries__fault_subtype__name_zh') or '未分类'
        count = entry['count']

        fault_types_set.add(fault_type)
        zones_dict[zone_code][fault_type] += count
        zones_dict[zone_code]['_zone_name'] = zone_name

    fault_type_totals = defaultdict(int)
    for zone_data in zones_dict.values():
        for fault_type, count in zone_data.items():
            if fault_type != '_zone_name':
                fault_type_totals[fault_type] += count

    sorted_fault_types = sorted(fault_types_set, key=lambda x: fault_type_totals[x], reverse=True)[:8]

    zone_fault_matrix = {
        'fault_types': [{'name': ft} for ft in sorted_fault_types],
        'rows': [],
        'column_totals': [fault_type_totals[ft] for ft in sorted_fault_types],
        'grand_total': 0
    }

    grand_total = 0
    for zone_code, zone_data in sorted(zones_dict.items()):
        if zone_code == '_zone_name':
            continue
        row = {
            'zone_name': zone_data.get('_zone_name', zone_code),
            'zone_code': zone_code,
            'counts': [],
            'total': 0
        }
        for fault_type in sorted_fault_types:
            count = zone_data.get(fault_type, 0)
            row['counts'].append(count)
            row['total'] += count
        grand_total += row['total']
        if row['total'] > 0:
            zone_fault_matrix['rows'].append(row)

    zone_fault_matrix['rows'].sort(key=lambda x: x['total'], reverse=True)
    zone_fault_matrix['rows'] = zone_fault_matrix['rows'][:10]
    zone_fault_matrix['column_totals'].append(grand_total)
    zone_fault_matrix['grand_total'] = grand_total

    # === 工作内容明细 (新现场作业记录树 WorkReportEntry) — additive alongside 故障 stats ===
    section_labels = dict(WorkItem.SECTION_CHOICES)
    entries_qs = WorkReportEntry.objects.filter(
        work_report__in=week_qs, work_item__active=True
    )
    entries_total = entries_qs.count()
    entries_count_sum = entries_qs.filter(
        work_item__value_type='count'
    ).aggregate(s=Sum('count'))['s'] or 0
    entries_by_section = list(
        entries_qs.values('work_item__section')
        .annotate(entries=Count('id'), counts=Sum('count'))
        .order_by('-entries')
    )
    for row in entries_by_section:
        row['label'] = section_labels.get(row['work_item__section'], row['work_item__section'])
    top_work_nodes = list(
        entries_qs.values('work_item__name_zh')
        .annotate(entries=Count('id'), counts=Sum('count'))
        .order_by('-entries')[:10]
    )
    entries_by_project = list(
        entries_qs.exclude(project__isnull=True)
        .values('project__name', 'project__category')
        .annotate(entries=Count('id'), counts=Sum('count'))
        .order_by('-entries')[:10]
    )

    worker_stats = []
    if admin:
        worker_stats = list(
            week_qs.values('worker__full_name', 'worker__employee_id')
            .annotate(
                total=Count('id'),
                difficult=Count('id', filter=Q(is_difficult=True))
            )
            .order_by('-total')[:10]
        )

    # === Demand Stats ===
    demand_qs = DemandRecord.objects.all()
    today = timezone.now().date()
    month_start = today.replace(day=1)

    demand_stats = {
        'total': demand_qs.count(),
        'pending': demand_qs.filter(status='submitted').count(),
        'approved': demand_qs.filter(status='approved').count(),
        'in_progress': demand_qs.filter(status='in_progress').count(),
        'completed': demand_qs.filter(status='completed').count(),
        'completed_this_month': demand_qs.filter(status='completed', date__gte=month_start).count(),
    }

    demand_by_category = list(
        demand_qs.values('category__name')
        .annotate(count=Count('id'))
        .exclude(category__isnull=True)
        .order_by('-count')[:10]
    )

    demand_by_department = list(
        demand_qs.values('demand_department__name')
        .annotate(count=Count('id'))
        .exclude(demand_department__isnull=True)
        .order_by('-count')[:10]
    )

    demand_by_status = list(
        demand_qs.values('status')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    context = {
        'is_admin': admin,
        # Work report weekly stats
        'week_start': week_start,
        'week_end': week_end,
        'week_number': week_number,
        'week_iso': week_start.isoformat(),
        'years': years,
        'year_weeks': year_weeks,
        'total_this_week': total_this_week,
        'reports_by_day': reports_by_day,
        'reports_by_location': reports_by_location,
        'reports_by_zone': reports_by_zone,
        'reports_by_category': reports_by_category,
        'top_faults': top_faults,
        'zone_fault_matrix': zone_fault_matrix,
        'entries_total': entries_total,
        'entries_count_sum': entries_count_sum,
        'entries_by_section': entries_by_section,
        'top_work_nodes': top_work_nodes,
        'entries_by_project': entries_by_project,
        'worker_stats': worker_stats,
        # Demand stats
        'demand_stats': demand_stats,
        'demand_by_category': demand_by_category,
        'demand_by_department': demand_by_department,
        'demand_by_status': demand_by_status,
    }

    return render(request, 'core/stats_dashboard.html', context)


# ==========================================================================
# Custom Report API
# ==========================================================================

from django.http import JsonResponse
from django.views.decorators.http import require_POST
import json


@require_POST
@login_required(login_url='core:login')
def custom_report_api(request):
    """Return aggregated data for custom chart configurations."""
    from core.models import WorkReport, DemandRecord
    from django.db.models import Count, Q
    from django.utils import timezone
    from collections import defaultdict

    try:
        body = json.loads(request.body)
        charts = body.get('charts', [])
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    user = request.user
    is_worker_user = False
    worker = None
    try:
        worker = user.worker_profile
        is_worker_user = True
    except Exception:
        pass

    from core.role_utils import is_admin as check_is_admin

    is_admin_user = check_is_admin(user)

    results = []

    for chart_cfg in charts:
        try:
            chart_id = chart_cfg.get('id', '')
            data_source = chart_cfg.get('dataSource', '')
            metric = chart_cfg.get('metric', '')
            date_from = chart_cfg.get('dateFrom', '')
            date_to = chart_cfg.get('dateTo', '')
            chart_type = chart_cfg.get('chartType', 'bar')
            bar_mode = chart_cfg.get('barMode', 'stacked')
            stack_by = chart_cfg.get('stackBy', '')
            title = chart_cfg.get('title', '')

            chart_data = _build_chart_data(data_source, metric, date_from, date_to,
                                            is_admin_user, is_worker_user, worker,
                                            bar_mode, stack_by)
            if chart_data is None:
                results.append({'id': chart_id, 'error': 'No data'})
                continue

            chart_data['id'] = chart_id
            chart_data['chartType'] = chart_type
            chart_data['barMode'] = bar_mode
            chart_data['title'] = title
            results.append(chart_data)
        except Exception as e:
            import traceback
            results.append({'id': chart_cfg.get('id', ''), 'error': str(e), 'traceback': traceback.format_exc()})

    return JsonResponse({'charts': results})


def _build_chart_data(data_source, metric, date_from, date_to,
                      is_admin, is_worker, worker, bar_mode='stacked', stack_by=''):
    """Build chart data dict for a given metric. Returns None if no data."""
    from core.models import WorkReport, WorkReportEntry, WorkItem, DemandRecord
    from django.db.models import Count, Q
    from django.utils import timezone
    from datetime import timedelta, datetime

    # Apply date filter helper
    def date_filter(qs, date_field='date'):
        if date_from:
            qs = qs.filter(**{f'{date_field}__gte': date_from})
        if date_to:
            qs = qs.filter(**{f'{date_field}__lte': date_to})
        return qs

    # === WORK REPORTS ===
    if data_source == 'work_reports':
        qs = WorkReport.objects.select_related('worker', 'location', 'work_category', 'info_source')
        if not is_admin:
            if is_worker:
                qs = qs.filter(worker=worker)
            else:
                qs = qs.none()

        qs = date_filter(qs)

        # Stacked bar chart: two-level group-by
        if stack_by:
            primary, stack_field = _get_metric_groupings(data_source, metric, stack_by)
            if primary is None:
                return None
            entries = list(qs.values(primary, stack_field)
                           .annotate(count=Count('id'))
                           .order_by(primary))
            if not entries:
                return None
            labels_seen = []
            label_set = set()
            stack_values = []
            data_map = {}
            for e in entries:
                label = str(e[primary] or '未指定')
                sv = e.get(stack_field) or '未指定'
                if label not in label_set:
                    labels_seen.append(label)
                    label_set.add(label)
                if sv not in stack_values:
                    stack_values.append(sv)
                data_map.setdefault(label, {})[sv] = e['count']

            datasets = []
            for i, sv in enumerate(stack_values[:15]):
                ds_data = []
                for lbl in labels_seen:
                    ds_data.append(data_map.get(lbl, {}).get(sv, 0))
                color_idx = i % len(_chart_colors_palette())
                datasets.append({
                    'label': str(sv),
                    'data': ds_data,
                    'backgroundColor': _chart_colors_palette()[color_idx],
                    'borderColor': 'rgba(255,255,255,1)',
                    'borderWidth': 1,
                })

            return {
                'labels': labels_seen,
                'datasets': datasets,
            }

        if metric == 'daily_trend':
            if not date_from or not date_to:
                today = timezone.now().date()
                date_from = (today - timedelta(days=29)).isoformat()
                date_to = today.isoformat()
                qs = date_filter(qs)
            entries = list(qs.values('date').annotate(count=Count('id')).order_by('date'))
            if not entries:
                return None
            return {
                'labels': [str(e['date']) for e in entries],
                'datasets': [{
                    'label': '维修日志数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric == 'by_location':
            entries = list(qs.values('location__name').annotate(count=Count('id')).order_by('-count')[:15])
            if not entries:
                return None
            return {
                'labels': [e['location__name'] or '未指定' for e in entries],
                'datasets': [{
                    'label': '日志数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric == 'by_zone':
            entries = list(qs.values('zone_location__name').annotate(count=Count('id')).exclude(zone_location__isnull=True).order_by('-count')[:15])
            if not entries:
                return None
            return {
                'labels': [e['zone_location__name'] or '未指定' for e in entries],
                'datasets': [{
                    'label': '日志数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric == 'by_category':
            entries = list(qs.values('work_category__name').annotate(count=Count('id')).order_by('-count')[:15])
            if not entries:
                return None
            return {
                'labels': [e['work_category__name'] or '未指定' for e in entries],
                'datasets': [{
                    'label': '日志数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric == 'by_fault_type':
            entries = list(qs.filter(fault_entries__isnull=False).values('fault_entries__fault_subtype__name_zh').annotate(count=Count('fault_entries__fault_subtype')).order_by('-count')[:15])
            if not entries:
                return None
            return {
                'labels': [e['fault_entries__fault_subtype__name_zh'] or '未分类' for e in entries],
                'datasets': [{
                    'label': '故障数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric == 'by_info_source':
            entries = list(qs.values('info_source__name').annotate(count=Count('id'))
                           .exclude(info_source__isnull=True).order_by('-count')[:15])
            if not entries:
                return None
            return {
                'labels': [e['info_source__name'] or '未指定' for e in entries],
                'datasets': [{
                    'label': '日志数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric == 'by_fault_category':
            entries = list(qs.filter(fault_entries__isnull=False)
                           .values('fault_entries__fault_subtype__category__name_zh')
                           .annotate(count=Count('fault_entries__fault_subtype'))
                           .order_by('-count')[:15])
            if not entries:
                return None
            return {
                'labels': [e['fault_entries__fault_subtype__category__name_zh'] or '未分类' for e in entries],
                'datasets': [{
                    'label': '故障数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric == 'by_equipment':
            entries = list(qs.filter(fault_entries__isnull=False)
                           .filter(fault_entries__equipment__isnull=False)
                           .values('fault_entries__equipment__equipment__model_name')
                           .annotate(count=Count('fault_entries__equipment'))
                           .order_by('-count')[:15])
            if not entries:
                return None
            return {
                'labels': [e['fault_entries__equipment__equipment__model_name'] or '未指定' for e in entries],
                'datasets': [{
                    'label': '故障数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric == 'by_worker_department':
            entries = list(qs.values('worker__department').annotate(count=Count('id')).order_by('-count'))
            if not entries:
                return None
            return {
                'labels': [e['worker__department'] or '未指定' for e in entries],
                'datasets': [{
                    'label': '日志数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric in ('by_entry_section', 'by_entry_node', 'by_entry_project'):
            # 工作内容明细 (WorkReportEntry) — additive, reads the new tree-form data
            eqs = WorkReportEntry.objects.filter(work_item__active=True)
            eqs = date_filter(eqs, 'work_report__date')
            if not is_admin:
                if is_worker:
                    eqs = eqs.filter(work_report__worker=worker)
                else:
                    eqs = eqs.none()
            if metric == 'by_entry_section':
                labels_map = dict(WorkItem.SECTION_CHOICES)
                rows = list(eqs.values('work_item__section')
                            .annotate(c=Count('id')).order_by('-c')[:15])
                labels = [labels_map.get(r['work_item__section'], r['work_item__section']) for r in rows]
            elif metric == 'by_entry_node':
                rows = list(eqs.values('work_item__name_zh')
                            .annotate(c=Count('id')).order_by('-c')[:15])
                labels = [r['work_item__name_zh'] or '未指定' for r in rows]
            else:  # by_entry_project
                rows = list(eqs.exclude(project__isnull=True)
                            .values('project__name').annotate(c=Count('id')).order_by('-c')[:15])
                labels = [r['project__name'] or '未指定' for r in rows]
            if not rows:
                return None
            return {
                'labels': labels,
                'datasets': [{
                    'label': '填报次数',
                    'data': [r['c'] for r in rows],
                    'backgroundColor': _chart_colors(len(rows)),
                }],
            }

        elif metric == 'difficult_rate_by_category':
            entries = list(qs.values('work_category__name').annotate(
                total=Count('id'),
                difficult=Count('id', filter=Q(is_difficult=True))
            ).order_by('-total')[:15])
            if not entries:
                return None
            return {
                'labels': [e['work_category__name'] or '未指定' for e in entries],
                'datasets': [
                    {
                        'label': '总数',
                        'data': [e['total'] for e in entries],
                        'backgroundColor': 'rgba(27, 67, 50, 0.7)',
                        'borderColor': 'rgba(27, 67, 50, 1)',
                    },
                    {
                        'label': '疑难',
                        'data': [e['difficult'] for e in entries],
                        'backgroundColor': 'rgba(204, 119, 34, 0.7)',
                        'borderColor': 'rgba(204, 119, 34, 1)',
                    }
                ]
            }

        elif metric == 'by_worker' and is_admin:
            entries = list(qs.values('worker__full_name').annotate(
                total=Count('id'),
                difficult=Count('id', filter=Q(is_difficult=True))
            ).order_by('-total')[:15])
            if not entries:
                return None
            return {
                'labels': [e['worker__full_name'] or '未指定' for e in entries],
                'datasets': [
                    {
                        'label': '总数',
                        'data': [e['total'] for e in entries],
                        'backgroundColor': 'rgba(27, 67, 50, 0.7)',
                        'borderColor': 'rgba(27, 67, 50, 1)',
                    },
                    {
                        'label': '疑难',
                        'data': [e['difficult'] for e in entries],
                        'backgroundColor': 'rgba(204, 119, 34, 0.7)',
                        'borderColor': 'rgba(204, 119, 34, 1)',
                    }
                ]
            }

        elif metric == 'difficult_rate_by_worker' and is_admin:
            entries = list(qs.values('worker__full_name').annotate(
                total=Count('id'),
                difficult=Count('id', filter=Q(is_difficult=True)),
                resolved=Count('id', filter=Q(is_difficult=True, is_difficult_resolved=True))
            ).order_by('-total')[:15])
            if not entries:
                return None
            return {
                'labels': [e['worker__full_name'] or '未指定' for e in entries],
                'datasets': [
                    {
                        'label': '总数',
                        'data': [e['total'] for e in entries],
                        'backgroundColor': 'rgba(27, 67, 50, 0.7)',
                        'borderColor': 'rgba(27, 67, 50, 1)',
                    },
                    {
                        'label': '疑难',
                        'data': [e['difficult'] for e in entries],
                        'backgroundColor': 'rgba(204, 119, 34, 0.7)',
                        'borderColor': 'rgba(204, 119, 34, 1)',
                    },
                    {
                        'label': '已处理',
                        'data': [e['resolved'] for e in entries],
                        'backgroundColor': 'rgba(64, 145, 108, 0.7)',
                        'borderColor': 'rgba(64, 145, 108, 1)',
                    }
                ]
            }

    # === DEMAND RECORDS ===
    elif data_source == 'demand_records':
        qs = DemandRecord.objects.select_related('zone', 'category', 'submitter', 'approver')
        qs = date_filter(qs)

        # Stacked bar chart: two-level group-by
        if stack_by:
            primary, stack_field = _get_metric_groupings(data_source, metric, stack_by)
            if primary is None:
                return None
            entries = list(qs.values(primary, stack_field)
                           .annotate(count=Count('id'))
                           .order_by(primary))
            if not entries:
                return None
            labels_seen = []
            label_set = set()
            stack_values = []
            data_map = {}
            for e in entries:
                label = str(e[primary] or '未指定')
                sv = e.get(stack_field) or '未指定'
                if label not in label_set:
                    labels_seen.append(label)
                    label_set.add(label)
                if sv not in stack_values:
                    stack_values.append(sv)
                data_map.setdefault(label, {})[sv] = e['count']

            datasets = []
            for i, sv in enumerate(stack_values[:15]):
                ds_data = []
                for lbl in labels_seen:
                    ds_data.append(data_map.get(lbl, {}).get(sv, 0))
                color_idx = i % len(_chart_colors_palette())
                datasets.append({
                    'label': str(sv),
                    'data': ds_data,
                    'backgroundColor': _chart_colors_palette()[color_idx],
                    'borderColor': 'rgba(255,255,255,1)',
                    'borderWidth': 1,
                })

            return {
                'labels': labels_seen,
                'datasets': datasets,
            }

        if metric == 'daily_trend':
            if not date_from or not date_to:
                today = timezone.now().date()
                date_from = (today - timedelta(days=29)).isoformat()
                date_to = today.isoformat()
                qs = date_filter(qs)
            entries = list(qs.values('date').annotate(count=Count('id')).order_by('date'))
            if not entries:
                return None
            return {
                'labels': [str(e['date']) for e in entries],
                'datasets': [{
                    'label': '需求日志数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric == 'by_category':
            entries = list(qs.values('category__name').annotate(count=Count('id')).exclude(category__isnull=True).order_by('-count')[:15])
            if not entries:
                return None
            return {
                'labels': [e['category__name'] or '未指定' for e in entries],
                'datasets': [{
                    'label': '需求数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric == 'by_department':
            entries = list(qs.values('demand_department__name').annotate(count=Count('id')).exclude(demand_department__isnull=True).order_by('-count')[:15])
            if not entries:
                return None
            return {
                'labels': [e['demand_department__name'] or '未指定' for e in entries],
                'datasets': [{
                    'label': '需求数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric == 'by_status':
            status_map = {'submitted': '已提交', 'approved': '已批准', 'rejected': '已拒绝', 'in_progress': '进行中', 'completed': '已完成'}
            entries = list(qs.values('status').annotate(count=Count('id')).order_by('-count'))
            if not entries:
                return None
            return {
                'labels': [status_map.get(e['status'], e['status']) for e in entries],
                'datasets': [{
                    'label': '需求数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric == 'global_events':
            entries = list(qs.filter(is_global_event=True).values('category__name').annotate(count=Count('id')).order_by('-count')[:15])
            if not entries:
                return None
            return {
                'labels': [e['category__name'] or '未指定' for e in entries],
                'datasets': [{
                    'label': '全局事件数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric == 'by_zone':
            entries = list(qs.filter(zone__isnull=False)
                           .values('zone__name').annotate(count=Count('id'))
                           .order_by('-count')[:15])
            if not entries:
                return None
            return {
                'labels': [e['zone__name'] or '未指定' for e in entries],
                'datasets': [{
                    'label': '需求数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric == 'by_contact':
            entries = list(qs.exclude(demand_contact='')
                           .values('demand_contact').annotate(count=Count('id'))
                           .order_by('-count')[:15])
            if not entries:
                return None
            return {
                'labels': [e['demand_contact'] or '未指定' for e in entries],
                'datasets': [{
                    'label': '需求数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric == 'by_submitter':
            entries = list(qs.filter(submitter__isnull=False)
                           .values('submitter__full_name').annotate(count=Count('id'))
                           .order_by('-count')[:15])
            if not entries:
                return None
            return {
                'labels': [e['submitter__full_name'] or '未指定' for e in entries],
                'datasets': [{
                    'label': '需求数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

        elif metric == 'global_event_volume':
            if not date_from or not date_to:
                today = timezone.now().date()
                date_from = (today - timedelta(days=29)).isoformat()
                date_to = today.isoformat()
                qs = date_filter(qs)
            entries = list(qs.filter(is_global_event=True)
                           .values('date').annotate(count=Count('id')).order_by('date'))
            if not entries:
                return None
            return {
                'labels': [str(e['date']) for e in entries],
                'datasets': [{
                    'label': '全局事件数',
                    'data': [e['count'] for e in entries],
                    'backgroundColor': _chart_colors(len(entries)),
                }]
            }

    return None


def _get_metric_groupings(data_source, metric, stack_by):
    """Return (primary_field, stack_field) for stacked bar chart. Returns (None, None) if invalid."""
    mapping = {
        'work_reports': {
            'worker': ('worker__full_name', 'worker__full_name'),
            'location': ('location__name', 'location__name'),
            'work_category': ('work_category__name', 'work_category__name'),
            'zone': ('zone_location__name', 'zone_location__name'),
            'info_source': ('info_source__name', 'info_source__name'),
            'fault_subtype': ('fault_entries__fault_subtype__name_zh', 'fault_entries__fault_subtype__name_zh'),
            'date': ('date', 'date'),
        },
        'demand_records': {
            'category': ('category__name', 'category__name'),
            'department': ('demand_department__name', 'demand_department__name'),
            'zone': ('zone__name', 'zone__name'),
            'status': ('status', 'status'),
            'contact': ('demand_contact', 'demand_contact'),
            'date': ('date', 'date'),
        },
    }

    table = mapping.get(data_source, {})
    stack_field = table.get(stack_by)
    if not stack_field:
        return None, None

    # Determine primary (label) field based on metric
    primary_map = {
        'work_reports': {
            'daily_trend': 'date',
            'by_location': ('location__name', 'location__name'),
            'by_zone': ('zone_location__name', 'zone_location__name'),
            'by_category': ('work_category__name', 'work_category__name'),
            'by_fault_type': ('fault_entries__fault_subtype__name_zh', 'fault_entries__fault_subtype__name_zh'),
            'by_info_source': ('info_source__name', 'info_source__name'),
            'by_fault_category': ('fault_entries__fault_subtype__category__name_zh', 'fault_entries__fault_subtype__category__name_zh'),
            'by_equipment': ('fault_entries__equipment__equipment__model_name', 'fault_entries__equipment__equipment__model_name'),
            'by_worker_department': ('worker__department', 'worker__department'),
            'difficult_rate_by_category': ('work_category__name', 'work_category__name'),
            'by_worker': ('worker__full_name', 'worker__full_name'),
            'difficult_rate_by_worker': ('worker__full_name', 'worker__full_name'),
        },
        'demand_records': {
            'daily_trend': 'date',
            'by_category': ('category__name', 'category__name'),
            'by_department': ('demand_department__name', 'demand_department__name'),
            'by_status': ('status', 'status'),
            'global_events': ('category__name', 'category__name'),
            'by_zone': ('zone__name', 'zone__name'),
            'by_contact': ('demand_contact', 'demand_contact'),
            'by_submitter': ('submitter__full_name', 'submitter__full_name'),
            'global_event_volume': 'date',
        },
    }

    primary_entry = primary_map.get(data_source, {}).get(metric)
    if primary_entry is None:
        return None, None

    if isinstance(primary_entry, str):
        # Single field metric (e.g. daily_trend) — use that as primary, stack_by as stack
        return primary_entry, stack_field[0]

    # Two-element tuple: (group_field, display_field)
    return primary_entry[0], stack_field[0]


def _chart_colors_palette():
    """Return the full color palette for stacked charts."""
    return [
        'rgba(27, 67, 50, 0.7)',
        'rgba(45, 106, 79, 0.7)',
        'rgba(64, 145, 108, 0.7)',
        'rgba(82, 183, 136, 0.7)',
        'rgba(204, 119, 34, 0.7)',
        'rgba(155, 34, 38, 0.7)',
        'rgba(45, 106, 150, 0.7)',
        'rgba(108, 117, 125, 0.7)',
        'rgba(27, 67, 100, 0.7)',
        'rgba(120, 50, 120, 0.7)',
        'rgba(180, 80, 40, 0.7)',
        'rgba(60, 140, 140, 0.7)',
        'rgba(140, 100, 40, 0.7)',
        'rgba(80, 60, 140, 0.7)',
        'rgba(160, 60, 80, 0.7)',
    ]


def _chart_colors(n):
    """Return a list of n distinct chart background colors."""
    palette = [
        'rgba(27, 67, 50, 0.7)',
        'rgba(45, 106, 79, 0.7)',
        'rgba(64, 145, 108, 0.7)',
        'rgba(82, 183, 136, 0.7)',
        'rgba(204, 119, 34, 0.7)',
        'rgba(155, 34, 38, 0.7)',
        'rgba(45, 106, 150, 0.7)',
        'rgba(108, 117, 125, 0.7)',
        'rgba(27, 67, 100, 0.7)',
        'rgba(120, 50, 120, 0.7)',
        'rgba(180, 80, 40, 0.7)',
        'rgba(60, 140, 140, 0.7)',
        'rgba(140, 100, 40, 0.7)',
        'rgba(80, 60, 140, 0.7)',
        'rgba(160, 60, 80, 0.7)',
    ]
    return palette[:n]


@login_required(login_url='core:login')
def custom_report(request):
    """Custom report page - user selects data and generates charts."""
    from core.role_utils import is_admin
    admin = is_admin(request.user)
    return render(request, 'core/custom_report.html', {'is_admin': admin})


@login_required(login_url='core:login')
def work_reports_list(request):
    from core.models import WorkReport, Patch, WorkCategory, Worker
    from core.role_utils import is_admin, get_worker_for_user
    from core.workorder_tree_views import workitem_path_map, enrich_reports

    user = request.user
    admin = is_admin(user)

    qs = WorkReport.objects.select_related(
        'worker', 'location', 'work_category', 'info_source'
    ).prefetch_related(
        'entries__work_item', 'entries__project'
    ).order_by('-date', '-id')

    # Scope by submitter for non-admins. Managers have no direct worker link,
    # so resolve via profile (they get the same Worker row the submit path uses).
    if not admin:
        worker = get_worker_for_user(user)
        qs = qs.filter(worker=worker) if worker else qs.none()

    # Filters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    location_id = request.GET.get('location')
    work_category_id = request.GET.get('work_category')
    worker_id = request.GET.get('worker')
    difficult = request.GET.get('is_difficult')
    pending = request.GET.get('is_pending_repair')

    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    if location_id:
        qs = qs.filter(location_id=location_id)
    if work_category_id:
        qs = qs.filter(work_category_id=work_category_id)
    if worker_id:
        qs = qs.filter(worker_id=worker_id)
    if difficult:
        qs = qs.filter(is_difficult=True)
    if pending:
        qs = qs.filter(is_pending_repair=True)

    reports = list(qs[:200])
    enrich_reports(reports, workitem_path_map())
    locations = Patch.objects.filter(active=True).order_by('order')
    work_categories = WorkCategory.objects.filter(active=True).order_by('order')
    workers = Worker.objects.all().order_by('full_name') if admin else []

    return render(request, 'core/work_reports.html', {
        'reports': reports,
        'locations': locations,
        'work_categories': work_categories,
        'workers': workers,
        'is_admin': admin,
        'filters': {
            'date_from': date_from or '',
            'date_to': date_to or '',
            'location': int(location_id) if location_id else '',
            'work_category': int(work_category_id) if work_category_id else '',
            'worker': int(worker_id) if worker_id else '',
            'is_difficult': bool(difficult),
            'is_pending_repair': bool(pending),
        },
    })


@login_required(login_url='core:login')
def work_report_detail(request, report_id):
    from core.models import WorkReport, WorkItem
    from core.role_utils import is_admin
    from collections import OrderedDict

    report = get_object_or_404(
        WorkReport.objects.select_related(
            'worker', 'location', 'work_category', 'info_source'
        ).prefetch_related('fault_entries__fault_subtype__category',
                           'entries__work_item', 'entries__project'),
        pk=report_id
    )

    if not is_admin(request.user):
        try:
            if report.worker != request.user.worker_profile:
                messages.error(request, '无权查看此记录')
                return redirect('core:work_reports')
        except Exception:
            messages.error(request, '无权查看此记录')
            return redirect('core:work_reports')

    # Group tree-form entries (WorkReportEntry) by section for display.
    section_labels = dict(WorkItem.SECTION_CHOICES)
    grouped = OrderedDict()
    for e in report.entries.select_related('work_item', 'project'):
        sec = e.work_item.section
        grouped.setdefault(sec, {'label': section_labels.get(sec, sec), 'items': []})
        grouped[sec]['items'].append(e)

    return render(request, 'core/work_report_detail.html', {
        'report': report,
        'fault_entries': report.fault_entries.select_related('fault_subtype__category').all(),
        'tree_entry_groups': list(grouped.values()),
    })


@login_required(login_url='core:login')
def work_report_create(request):
    from core.models import WorkReport, WorkReportFault, Patch, WorkCategory, InfoSource, FaultCategory, Worker, Zone, ZoneEquipment
    from core.role_utils import is_admin

    if request.method == 'POST':
        try:
            worker = request.user.worker_profile
        except Exception:
            messages.error(request, '当前用户未关联处理人账号')
            return redirect('core:work_reports')

        zone_code = request.POST.get('zone_location', '').strip()
        zone = Zone.objects.filter(code=zone_code).first() if zone_code else None

        report = WorkReport.objects.create(
            date=request.POST.get('date'),
            weather=request.POST.get('weather', ''),
            worker=worker,
            location_id=request.POST.get('location'),
            work_category_id=request.POST.get('work_category'),
            zone_location=zone,
            remark=request.POST.get('remark', ''),
            info_source_id=request.POST.get('info_source') or None,
            is_difficult=bool(request.POST.get('is_difficult')),
            is_difficult_resolved=bool(request.POST.get('is_difficult_resolved')),
        )

        # Parse fault entries
        fault_json = request.POST.get('fault_entries', '[]')
        try:
            fault_data = json.loads(fault_json)
            for entry in fault_data:
                if entry.get('count', 0) > 0 and entry.get('fault_subtype'):
                    WorkReportFault.objects.create(
                        work_report=report,
                        fault_subtype_id=entry['fault_subtype'],
                        count=entry['count'],
                        equipment_id=entry.get('equipment') or None,
                    )
        except (json.JSONDecodeError, KeyError):
            pass

        messages.success(request, f'工作日报已创建 (ID: {report.id})')

        if request.POST.get('save_and_new'):
            return redirect('core:work_report_create')
        return redirect('core:work_reports')

    locations = Patch.objects.filter(active=True).order_by('order')
    work_categories = WorkCategory.objects.filter(active=True).order_by('order')
    info_sources = InfoSource.objects.filter(active=True).order_by('order')
    fault_categories = FaultCategory.objects.filter(active=True).prefetch_related(
        'sub_types'
    ).order_by('order', 'id')
    zones = Zone.objects.order_by('code')

    # Build zone equipment map for frontend lookup
    zone_equipment_map = {}
    for ze in ZoneEquipment.objects.select_related('zone', 'equipment').all():
        zone_code = ze.zone.code
        if zone_code not in zone_equipment_map:
            zone_equipment_map[zone_code] = []
        zone_equipment_map[zone_code].append({
            'id': ze.id,
            'equipment_details': {
                'equipment_type': ze.equipment.equipment_type,
                'equipment_type_display': ze.equipment.get_equipment_type_display(),
                'model_name': ze.equipment.model_name,
            },
            'location_in_zone': ze.location_in_zone or '',
        })

    from datetime import date
    return render(request, 'core/work_report_form.html', {
        'locations': locations,
        'work_categories': work_categories,
        'info_sources': info_sources,
        'fault_categories': fault_categories,
        'zones': zones,
        'grouped_zones': _build_grouped_zones(zones),
        'zone_equipment_json': json.dumps(zone_equipment_map),
        'fault_categories_json': json.dumps([
            {'id': c.id, 'name_zh': c.name_zh, 'name_en': c.name_en,
             'sub_types': [{'id': s.id, 'name_zh': s.name_zh, 'name_en': s.name_en} for s in c.sub_types.all()]}
            for c in fault_categories
        ]),
        'today': date.today().isoformat(),
    })


@login_required(login_url='core:login')
def work_report_edit(request, report_id):
    from core.models import WorkReport, WorkReportFault, Patch, WorkCategory, InfoSource, FaultCategory, Zone, ZoneEquipment
    from core.role_utils import is_admin

    report = get_object_or_404(WorkReport, pk=report_id)

    if not is_admin(request.user):
        try:
            if report.worker != request.user.worker_profile:
                messages.error(request, '无权编辑此记录')
                return redirect('core:work_reports')
        except Exception:
            messages.error(request, '无权编辑此记录')
            return redirect('core:work_reports')

    if request.method == 'POST':
        report.date = request.POST.get('date')
        report.weather = request.POST.get('weather', '')
        report.location_id = request.POST.get('location')
        report.work_category_id = request.POST.get('work_category')
        zone_code = request.POST.get('zone_location', '').strip()
        report.zone_location = Zone.objects.filter(code=zone_code).first() if zone_code else None
        report.remark = request.POST.get('remark', '')
        report.info_source_id = request.POST.get('info_source') or None
        report.is_difficult = bool(request.POST.get('is_difficult'))
        report.is_difficult_resolved = bool(request.POST.get('is_difficult_resolved'))
        report.save()

        # Replace fault entries
        report.fault_entries.all().delete()
        fault_json = request.POST.get('fault_entries', '[]')
        try:
            fault_data = json.loads(fault_json)
            for entry in fault_data:
                if entry.get('count', 0) > 0 and entry.get('fault_subtype'):
                    WorkReportFault.objects.create(
                        work_report=report,
                        fault_subtype_id=entry['fault_subtype'],
                        count=entry['count'],
                    )
        except (json.JSONDecodeError, KeyError):
            pass

        messages.success(request, f'工作日报已更新 (ID: {report.id})')
        return redirect('core:work_reports')

    # GET — pre-populate form
    locations = Patch.objects.filter(active=True).order_by('order')
    work_categories = WorkCategory.objects.filter(active=True).order_by('order')
    info_sources = InfoSource.objects.filter(active=True).order_by('order')
    fault_categories = FaultCategory.objects.filter(active=True).prefetch_related(
        'sub_types'
    ).order_by('order', 'id')
    zones = Zone.objects.order_by('code')

    # Build zone equipment map for frontend lookup
    zone_equipment_map = {}
    for ze in ZoneEquipment.objects.select_related('zone', 'equipment').all():
        zone_code = ze.zone.code
        if zone_code not in zone_equipment_map:
            zone_equipment_map[zone_code] = []
        zone_equipment_map[zone_code].append({
            'id': ze.id,
            'equipment_details': {
                'equipment_type': ze.equipment.equipment_type,
                'equipment_type_display': ze.equipment.get_equipment_type_display(),
                'model_name': ze.equipment.model_name,
            },
            'location_in_zone': ze.location_in_zone or '',
        })

    existing_faults = {
        str(e.fault_subtype_id): {'count': e.count, 'equipment': e.equipment_id}
        for e in report.fault_entries.all()
    }

    return render(request, 'core/work_report_form.html', {
        'report': report,
        'existing_faults_json': json.dumps(existing_faults),
        'locations': locations,
        'work_categories': work_categories,
        'info_sources': info_sources,
        'fault_categories': fault_categories,
        'zones': zones,
        'grouped_zones': _build_grouped_zones(zones),
        'zone_equipment_json': json.dumps(zone_equipment_map),
        'fault_categories_json': json.dumps([
            {'id': c.id, 'name_zh': c.name_zh, 'name_en': c.name_en,
             'sub_types': [{'id': s.id, 'name_zh': s.name_zh, 'name_en': s.name_en} for s in c.sub_types.all()]}
            for c in fault_categories
        ]),
        'today': report.date.isoformat(),
    })


@require_POST
@login_required(login_url='core:login')
def work_report_upload_photo(request, report_id):
    import os
    from django.conf import settings
    from datetime import datetime
    from core.models import WorkReport
    from core.role_utils import is_admin

    if not is_admin(request.user):
        return JsonResponse({'error': '仅管理员可上传照片'}, status=403)

    report = get_object_or_404(WorkReport, pk=report_id)
    files = request.FILES.getlist('files')
    if not files:
        return JsonResponse({'error': '未选择文件'}, status=400)

    photo_paths = list(report.photos or [])
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'work_reports', str(report.id))
    os.makedirs(upload_dir, exist_ok=True)

    for f in files:
        ext = os.path.splitext(f.name)[1]
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(photo_paths)}{ext}"
        filepath = os.path.join(upload_dir, filename)
        with open(filepath, 'wb') as dest:
            for chunk in f.chunks():
                dest.write(chunk)
        photo_paths.append(f"work_reports/{report.id}/{filename}")

    report.photos = photo_paths
    report.save(update_fields=['photos'])

    return JsonResponse({'photos': photo_paths})


@require_POST
@login_required(login_url='core:login')
def work_report_remove_photo(request, report_id):
    import os
    from django.conf import settings
    from core.models import WorkReport
    from core.role_utils import is_admin

    if not is_admin(request.user):
        return JsonResponse({'error': '仅管理员可删除照片'}, status=403)

    report = get_object_or_404(WorkReport, pk=report_id)
    photo = request.POST.get('photo')
    if not photo:
        return JsonResponse({'error': '缺少照片参数'}, status=400)

    photo_paths = list(report.photos or [])
    if photo in photo_paths:
        photo_paths.remove(photo)
        report.photos = photo_paths
        report.save(update_fields=['photos'])
        filepath = os.path.join(settings.MEDIA_ROOT, photo)
        if os.path.exists(filepath):
            os.remove(filepath)

    return JsonResponse({'photos': photo_paths})


@require_POST
@login_required(login_url='core:login')
def work_report_delete(request, report_id):
    from core.models import WorkReport
    from core.role_utils import is_admin

    if not is_admin(request.user):
        messages.error(request, '仅管理员可删除记录')
        return redirect('core:work_reports')

    report = get_object_or_404(WorkReport, pk=report_id)
    report.delete()
    messages.success(request, f'工作日报已删除')
    return redirect('core:work_reports')


@login_required(login_url='core:login')
def demands_page(request):
    """
    需求周报列表页面 - 显示所有需求记录
    """
    from core.models import DemandRecord, DemandCategory, DemandDepartment
    from core.role_utils import is_admin

    user = request.user
    admin = is_admin(user)

    qs = DemandRecord.objects.select_related(
        'zone', 'category', 'demand_department', 'submitter', 'approver'
    ).order_by('-date', '-id')

    if not admin:
        qs = qs.filter(status__in=['approved', 'in_progress', 'completed'])

    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    status_filter = request.GET.get('status')
    category_filter = request.GET.get('category')
    department_filter = request.GET.get('department')

    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    if status_filter:
        qs = qs.filter(status=status_filter)
    if category_filter:
        qs = qs.filter(category_id=category_filter)
    if department_filter:
        qs = qs.filter(demand_department_id=department_filter)

    demands = qs[:200]
    categories = DemandCategory.objects.filter(active=True).order_by('order')
    departments = DemandDepartment.objects.filter(active=True).order_by('order')

    context = {
        'demands': demands,
        'categories': categories,
        'departments': departments,
        'is_admin': admin,
        'date_from': date_from or '',
        'date_to': date_to or '',
        'status_filter': status_filter or '',
        'category_filter': int(category_filter) if category_filter else '',
        'department_filter': int(department_filter) if department_filter else '',
    }

    return render(request, 'core/demands.html', context)



@login_required(login_url='core:login')
def zone_geo_api(request):
    from core.models import Zone
    import json as _json
    zones = Zone.objects.filter(Q(boundary_points__isnull=False) | Q(dxf_boundary_points__isnull=False)).exclude(boundary_points=[]).exclude(dxf_boundary_points=[]).only('code', 'name', 'boundary_points', 'dxf_boundary_points', 'boundary_source')
    data = []
    for z in zones:
        bp = z.active_boundary_points
        if not bp:
            continue
        all_pts = bp if isinstance(bp[0], dict) else []
        if isinstance(bp[0], list):
            all_pts = [p for ring in bp for p in ring]
        center = None
        if all_pts:
            lat = sum(p.get('lat', 0) for p in all_pts) / len(all_pts)
            lng = sum(p.get('lng', 0) for p in all_pts) / len(all_pts)
            center = [round(lat, 6), round(lng, 6)]
        data.append({'c': z.code, 'n': z.name or z.code, 'b': bp, 't': center})
    return JsonResponse(data, safe=False)


@login_required(login_url='core:login')
def workorder_history(request):
    from core.models import WorkReport, Worker
    from core.role_utils import get_worker_for_user, is_admin, get_user_role, ROLE_FIELD_WORKER
    from core.role_utils import ROLE_SUPER_ADMIN, ROLE_MANAGER
    from core.workorder_tree_views import workitem_path_map, enrich_reports
    from datetime import date

    role = get_user_role(request.user)
    if role not in (ROLE_FIELD_WORKER, ROLE_SUPER_ADMIN, ROLE_MANAGER):
        messages.error(request, '无权限访问此页面')
        return redirect('core:login')

    worker = get_worker_for_user(request.user)
    pending = request.GET.get('pending')

    if worker:
        reports = WorkReport.objects.filter(worker=worker)
    elif is_admin(request.user):
        reports = WorkReport.objects.all()
    else:
        reports = WorkReport.objects.none()

    if pending:
        reports = reports.filter(is_pending_repair=True)

    reports = list(reports.select_related('worker', 'work_category', 'location')
                   .prefetch_related('zones', 'entries__work_item', 'entries__project')
                   .order_by('-date', '-id')[:50])
    enrich_reports(reports, workitem_path_map())

    context = {
        'reports': reports,
        'worker_name': worker.full_name if worker else request.user.get_full_name() or request.user.username,
        'pending_filter': bool(pending),
    }
    return render(request, 'core/workorder_history.html', context)


def _build_zone_geo_data():
    from core.models import Zone
    zones = Zone.objects.filter(Q(boundary_points__isnull=False) | Q(dxf_boundary_points__isnull=False)).exclude(boundary_points=[]).exclude(dxf_boundary_points=[]).only('code', 'name', 'boundary_points', 'dxf_boundary_points', 'boundary_source')
    data = []
    for z in zones:
        bp = z.active_boundary_points
        if not bp:
            continue
        all_pts = bp if isinstance(bp[0], dict) else []
        if isinstance(bp[0], list):
            all_pts = [p for ring in bp for p in ring]
        center = None
        if all_pts:
            lat = sum(p.get('lat', 0) for p in all_pts) / len(all_pts)
            lng = sum(p.get('lng', 0) for p in all_pts) / len(all_pts)
            center = [round(lat, 6), round(lng, 6)]
        data.append({'c': z.code, 'n': z.name or z.code, 'b': bp, 't': center})
    return data


@login_required(login_url='core:login')
def workorder_mobile_v2(request):
    from core.models import WorkReport, Patch, Zone, Worker
    from core.role_utils import get_worker_for_user, is_admin, get_user_role, ROLE_FIELD_WORKER
    from core.role_utils import ROLE_SUPER_ADMIN, ROLE_MANAGER, resolve_or_create_worker
    from core.workorder_tree_views import (
        _calc_hours, _save_entries, _collect_entry_photos, _save_photo,
        _resolve_pending_repairs,
    )
    from datetime import date, datetime, time

    role = get_user_role(request.user)
    if role not in (ROLE_FIELD_WORKER, ROLE_SUPER_ADMIN, ROLE_MANAGER):
        messages.error(request, '无权限访问此页面')
        return redirect('core:login')

    worker = get_worker_for_user(request.user)
    if not worker and not is_admin(request.user):
        messages.error(request, '未关联处理人账号')
        return redirect('core:login')

    if request.method == 'POST':
        try:
            if not worker and not is_admin(request.user):
                return JsonResponse({'success': False, 'message': '未关联处理人账号'}, status=400)

            # Resolve the real submitter. Managers/admins have no Worker row,
            # so provision one from their ManagerProfile (idempotent via employee_id).
            # Previously this fell back to Worker.objects.first(), which attributed
            # every manager submission to the same arbitrary worker.
            post_worker, _created = resolve_or_create_worker(request.user)
            if not post_worker:
                return JsonResponse({'success': False, 'message': '未关联处理人账号'}, status=400)

            shift = request.POST.get('shift', '')
            start_str = request.POST.get('work_start_time', '')
            end_str = request.POST.get('work_end_time', '')

            work_start = None
            work_end = None
            if start_str:
                h, m = start_str.split(':')
                work_start = time(int(h), int(m))
            if end_str:
                h, m = end_str.split(':')
                work_end = time(int(h), int(m))

            team_size = int(request.POST.get('team_size', 1) or 1)
            third_party_count = int(request.POST.get('third_party_count', 0) or 0)

            team_hours = _calc_hours(work_start, work_end, team_size)
            third_party_hours = _calc_hours(work_start, work_end, third_party_count)

            zone_codes = request.POST.getlist('zones')
            first_zone = Zone.objects.filter(code__in=zone_codes).select_related('patch').first() if zone_codes else None
            location = first_zone.patch if first_zone else Patch.objects.first()

            selected_zones = Zone.objects.filter(code__in=zone_codes)
            zone_names = ', '.join(z.name or z.code for z in selected_zones) if selected_zones else ''

            report = WorkReport.objects.create(
                date=request.POST.get('date') or date.today().isoformat(),
                weather='',
                worker=post_worker,
                location=location,
                zone_location=first_zone,
                remark=request.POST.get('remark', ''),
                is_pending_repair=bool(request.POST.get('is_pending_repair')),
                is_difficult=bool(request.POST.get('is_difficult')),
                is_difficult_resolved=bool(request.POST.get('is_difficult_resolved')),
                shift=shift,
                work_start_time=work_start,
                work_end_time=work_end,
                team_size=team_size,
                third_party_count=third_party_count,
                team_hours=team_hours,
                third_party_hours=third_party_hours,
                zone_names=zone_names,
                work_content=request.POST.get('work_content', ''),
            )

            if selected_zones:
                report.zones.set(selected_zones)

            # Work-content tree entries (replaces the old two-level fault model).
            entries = json.loads(request.POST.get('entries', '[]') or '[]')
            _save_entries(report, entries, _collect_entry_photos(request))
            # 计划性维修: resolve the checked past 待修 workorders.
            pm_ids = [x for x in (request.POST.get('pm_resolved') or '').split(',') if x.strip().isdigit()]
            if pm_ids:
                _resolve_pending_repairs(report, pm_ids)
            entry_count = report.entries.count()

            if report.is_difficult:
                note = request.POST.get('remark', '').strip()
                remark_content = note or (f'疑难工单 · {entry_count} 项' if entry_count else '疑难工单')
                remark_entry = {
                    'date': report.date if isinstance(report.date, str) else report.date.isoformat(),
                    'content': remark_content,
                    'author': worker.full_name if worker else str(request.user),
                    'workorder_id': report.id,
                }
                for z in selected_zones:
                    remarks = json.loads(z.remarks) if z.remarks else []
                    remarks.insert(0, remark_entry)
                    z.remarks = json.dumps(remarks, ensure_ascii=False)
                    z.save(update_fields=['remarks'])

            # Report-level photos (1.1.12).
            photo_paths = [_save_photo(report, f)
                           for f in request.FILES.getlist('report_photos')]
            if photo_paths:
                report.photos = photo_paths
                report.save(update_fields=['photos'])

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': f'工作记录已提交 (ID: {report.id})'})
            messages.success(request, f'工作记录已提交 (ID: {report.id})')
            return redirect('core:dashboard')

        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': str(e)}, status=400)
            messages.error(request, f'提交失败: {e}')
            return redirect('core:dashboard')

    # GET: redirect to dashboard (modal handles form)
    return redirect('core:dashboard')


@login_required(login_url='core:login')
def water_request_mobile_v2(request):
    from core.models import WaterRequest, Zone, Patch, Worker, DepartmentUserProfile
    from core.role_utils import (
        get_worker_for_user, get_user_role, is_admin,
        ROLE_DEPT_USER, ROLE_MANAGER, ROLE_SUPER_ADMIN,
    )
    from datetime import date, datetime

    role = get_user_role(request.user)
    if role not in (ROLE_DEPT_USER, ROLE_MANAGER, ROLE_SUPER_ADMIN):
        messages.error(request, '无权限访问此页面')
        return redirect('core:login')

    worker = get_worker_for_user(request.user)
    user_name = worker.full_name if worker else request.user.get_full_name() or request.user.username
    today = date.today()
    now_time = datetime.now().strftime('%H:%M')

    dept_profile = DepartmentUserProfile.objects.filter(user=request.user).first()
    user_type = dept_profile.department if dept_profile else 'ENT'

    if request.method == 'POST':
        try:
            zone_codes = json.loads(request.POST.get('zone_codes', '[]'))
            if not zone_codes:
                return JsonResponse({'success': False, 'message': '请选择至少一个区域'}, status=400)

            request_type = request.POST.get('request_type', '停水需求')
            start_dt = request.POST.get('start_datetime')
            end_dt = request.POST.get('end_datetime')
            remark = request.POST.get('remark', '')

            if not start_dt or not end_dt:
                return JsonResponse({'success': False, 'message': '请填写需求时间段'}, status=400)

            start_datetime = datetime.fromisoformat(start_dt)
            end_datetime = datetime.fromisoformat(end_dt)

            zones = Zone.objects.filter(code__in=zone_codes)
            created_count = 0
            for z in zones:
                WaterRequest.objects.create(
                    zone=z,
                    submitter=worker,
                    user_type=user_type,
                    request_type=request_type,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    status='submitted',
                )
                created_count += 1

            return JsonResponse({
                'success': True,
                'message': f'已提交 {created_count} 个区域的浇水协调需求',
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=400)

    # GET: redirect to dashboard (modal handles form)
    return redirect('core:dashboard')


@login_required(login_url='core:login')
def workorder_modal_data(request):
    """API: return workorder form metadata as JSON for dashboard modal."""
    from core.models import WorkReport, Worker
    from core.role_utils import get_worker_for_user, get_user_role, is_admin, ROLE_FIELD_WORKER, ROLE_SUPER_ADMIN, ROLE_MANAGER
    from core.workorder_tree_views import serialize_workitem_tree, serialize_projects, IRRIGATION_SUBCATEGORIES
    from datetime import date, datetime

    role = get_user_role(request.user)
    if role not in (ROLE_FIELD_WORKER, ROLE_SUPER_ADMIN, ROLE_MANAGER):
        return JsonResponse({'error': '无权限'}, status=403)

    worker = get_worker_for_user(request.user)

    now = datetime.now()
    rounded_min = (now.minute // 15) * 15
    default_time = now.replace(minute=rounded_min, second=0, microsecond=0).strftime('%H:%M')

    shift_freq = {'早班': 0, '白班': 0, '夜班': 0}
    if worker:
        recent = WorkReport.objects.filter(worker=worker, shift__in=shift_freq.keys()).values_list('shift', flat=True)
        for s in recent:
            if s in shift_freq:
                shift_freq[s] += 1
    sorted_shifts = sorted(shift_freq.keys(), key=lambda s: -shift_freq[s])

    return JsonResponse({
        'work_tree': serialize_workitem_tree(),
        'projects': serialize_projects(),
        'irrigation_subcategories': IRRIGATION_SUBCATEGORIES(),
        'can_create_project': role in (ROLE_MANAGER, ROLE_SUPER_ADMIN),
        'sorted_shifts': sorted_shifts,
        'today': date.today().isoformat(),
        'now_time': now.strftime('%H:%M'),
        'default_time': default_time,
        'worker_name': worker.full_name if worker else request.user.get_full_name() or request.user.username,
    })


@login_required(login_url='core:login')
def water_request_modal_data(request):
    """API: return water request form metadata as JSON for dashboard modal."""
    from core.models import WaterRequest, Worker
    from core.role_utils import get_worker_for_user, get_user_role, ROLE_DEPT_USER, ROLE_MANAGER, ROLE_SUPER_ADMIN
    from datetime import date, datetime

    role = get_user_role(request.user)
    if role not in (ROLE_DEPT_USER, ROLE_MANAGER, ROLE_SUPER_ADMIN):
        return JsonResponse({'error': '无权限'}, status=403)

    worker = get_worker_for_user(request.user)
    now = datetime.now()

    return JsonResponse({
        'request_type_choices': list(WaterRequest.REQUEST_TYPE_CHOICES),
        'user_name': worker.full_name if worker else request.user.get_full_name() or request.user.username,
        'today': date.today().isoformat(),
        'now_time': now.strftime('%H:%M'),
    })


@login_required(login_url='core:login')
def zones_in_area_api(request):
    """API: given a drawn polygon/rect/circle, return zone codes whose centroid falls inside."""
    from core.models import Zone

    shape_type = request.GET.get('type', 'polygon')
    points_json = request.GET.get('points', '[]')
    center_lat = request.GET.get('center_lat')
    center_lng = request.GET.get('center_lng')
    radius = request.GET.get('radius')  # in meters

    try:
        points = json.loads(points_json)
    except (json.JSONDecodeError, TypeError):
        points = []

    def point_in_polygon(lat, lng, polygon):
        """Ray casting algorithm."""
        n = len(polygon)
        inside = False
        j = n - 1
        for i in range(n):
            yi, xi = polygon[i]['lat'], polygon[i]['lng']
            yj, xj = polygon[j]['lat'], polygon[j]['lng']
            if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    # Get all zones with at least one boundary source (boundary_points OR dxf_boundary_points).
    zones = Zone.objects.exclude(Q(boundary_points=[]) & Q(dxf_boundary_points=[]))
    result_codes = []

    for z in zones:
        bp = z.active_boundary_points
        if not bp:
            continue
        # Calculate centroid
        all_pts = bp if isinstance(bp[0], dict) else []
        if isinstance(bp[0], list):
            all_pts = [p for ring in bp for p in ring]
        if not all_pts:
            continue
        clat = sum(p.get('lat', 0) for p in all_pts) / len(all_pts)
        clng = sum(p.get('lng', 0) for p in all_pts) / len(all_pts)

        if shape_type == 'polygon' and len(points) >= 3:
            if point_in_polygon(clat, clng, points):
                result_codes.append(z.code)
        elif shape_type == 'circle' and center_lat and center_lng and radius:
            from math import radians, cos, sin, asin, sqrt
            dlat = radians(clat - float(center_lat))
            dlng = radians(clng - float(center_lng))
            a = sin(dlat/2)**2 + cos(radians(float(center_lat))) * cos(radians(clat)) * sin(dlng/2)**2
            d = 2 * 6371000 * asin(sqrt(a))  # distance in meters
            if d <= float(radius):
                result_codes.append(z.code)
        elif shape_type == 'rect' and len(points) >= 2:
            lats = [p['lat'] for p in points]
            lngs = [p['lng'] for p in points]
            if min(lats) <= clat <= max(lats) and min(lngs) <= clng <= max(lngs):
                result_codes.append(z.code)

    return JsonResponse({'zone_codes': result_codes, 'count': len(result_codes)})


@login_required(login_url='core:login')
@ensure_csrf_cookie
def zone_dxf_import(request):
    """DXF boundary import page — upload DXF, georeference, assign shapes to zones."""
    import json
    from .models import ManagerProfile, Worker, MapStyleSettings
    from .dxf_utils import (
        parse_dxf_shapes, detect_nesting, detect_coord_system,
        shapes_to_latlng_auto, compute_affine_transform,
        transform_shape, transform_group_to_boundary,
        shapes_to_geojson_preview, auto_calibrate,
    )

    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        try:
            Worker.objects.get(user=request.user, active=True)
        except Worker.DoesNotExist:
            messages.error(request, '无权限访问此页面')
            return redirect('core:dashboard')

    if request.method == 'POST':
        action = request.POST.get('action', '')

        # ── Upload DXF ──
        if action == 'upload_dxf':
            uploaded = request.FILES.get('file')
            if not uploaded:
                return JsonResponse({'success': False, 'message': '未选择文件'}, status=400)
            if not uploaded.name.lower().endswith('.dxf'):
                return JsonResponse({'success': False, 'message': '请上传 .dxf 格式文件'}, status=400)

            shapes = parse_dxf_shapes(uploaded)
            if isinstance(shapes, dict) and 'error' in shapes:
                return JsonResponse({'success': False, 'message': shapes['error']}, status=400)

            groups = detect_nesting(shapes)
            coord_info = detect_coord_system(shapes)

            # Store in session
            request.session['dxf_shapes'] = shapes
            request.session['dxf_groups'] = groups
            request.session['dxf_filename'] = uploaded.name
            request.session['dxf_coord_info'] = coord_info
            # Clear previous anchors/transformed data
            request.session.pop('dxf_anchors', None)
            request.session.pop('dxf_transformed', None)

            preview = shapes_to_geojson_preview(shapes, groups)

            # If WGS84 auto-detected, pre-transform
            if coord_info.get('type') == 'wgs84' and not coord_info.get('need_anchors'):
                axis_map = coord_info.get('axis_map', 'xy_to_lnglat')
                transformed = shapes_to_latlng_auto(shapes, axis_map)
                request.session['dxf_transformed'] = transformed
                preview['transformed'] = transformed
            elif coord_info.get('auto_calibrated'):
                # Local coords with site calibration — auto-transform
                transformed = auto_calibrate(shapes)
                if transformed:
                    request.session['dxf_transformed'] = transformed
                    preview['transformed'] = transformed
                    coord_info['need_anchors'] = False
                    coord_info['info'] += ' — 已自动配准'

            return JsonResponse({
                'success': True,
                'message': f'识别到 {len(shapes)} 个封闭图形，{len(groups)} 个图形组',
                'filename': uploaded.name,
                'coord_info': coord_info,
                **preview,
            })

        # ── Set anchors (georeference) ──
        if action == 'set_anchors':
            shapes = request.session.get('dxf_shapes')
            groups = request.session.get('dxf_groups')
            if not shapes:
                return JsonResponse({'success': False, 'message': '请先上传DXF文件'}, status=400)

            anchors_raw = request.POST.get('anchors', '[]')
            try:
                anchors = json.loads(anchors_raw)
            except (json.JSONDecodeError, TypeError):
                return JsonResponse({'success': False, 'message': '锚点数据格式错误'}, status=400)

            if len(anchors) < 2:
                return JsonResponse({'success': False, 'message': '需要至少2个锚点'}, status=400)

            transform_fn = compute_affine_transform(anchors)
            if isinstance(transform_fn, str):
                return JsonResponse({'success': False, 'message': transform_fn}, status=400)

            # Transform all shapes
            transformed = [transform_shape(s, transform_fn) for s in shapes]

            request.session['dxf_anchors'] = anchors
            request.session['dxf_transformed'] = transformed

            return JsonResponse({
                'success': True,
                'message': '坐标配准成功',
                'transformed': transformed,
            })

        # ── Preview transform ──
        if action == 'preview_transform':
            shapes = request.session.get('dxf_shapes')
            if not shapes:
                return JsonResponse({'success': False, 'message': '请先上传DXF文件'}, status=400)

            anchors_raw = request.POST.get('anchors', '[]')
            try:
                anchors = json.loads(anchors_raw)
            except (json.JSONDecodeError, TypeError):
                return JsonResponse({'success': False, 'message': '锚点数据格式错误'}, status=400)

            if len(anchors) < 2:
                return JsonResponse({'success': False, 'message': '需要至少2个锚点才能预览', 'status': 'need_more'})

            transform_fn = compute_affine_transform(anchors)
            if isinstance(transform_fn, str):
                return JsonResponse({'success': False, 'message': transform_fn}, status=400)

            transformed = [transform_shape(s, transform_fn) for s in shapes]
            return JsonResponse({
                'success': True,
                'transformed': transformed,
            })

        # ── Assign shape to zone ──
        if action == 'assign_shape':
            shapes = request.session.get('dxf_shapes')
            groups = request.session.get('dxf_groups')
            filename = request.session.get('dxf_filename', '')

            # Prefer client-sent transformed coords (includes drag offsets)
            transformed = None
            transformed_json = request.POST.get('transformed_json', '')
            if transformed_json:
                try:
                    transformed = json.loads(transformed_json)
                except (json.JSONDecodeError, TypeError):
                    pass
            if not transformed:
                transformed = request.session.get('dxf_transformed')
            else:
                # Sync client offset back to session for future assigns / reloads
                request.session['dxf_transformed'] = transformed

            if not transformed:
                # Check if auto WGS84
                coord_info = request.session.get('dxf_coord_info', {})
                if coord_info.get('type') == 'wgs84':
                    transformed = shapes_to_latlng_auto(shapes, coord_info.get('axis_map', 'xy_to_lnglat'))
                else:
                    return JsonResponse({'success': False, 'message': '请先完成坐标配准'}, status=400)

            zone_code = request.POST.get('zone_code', '').strip()

            # Support multi-group: accept group_ids (JSON array) or legacy group_id
            group_ids_raw = request.POST.get('group_ids', '')
            group_id_legacy = request.POST.get('group_id', '').strip()
            if group_ids_raw:
                try:
                    group_ids = json.loads(group_ids_raw)
                except (json.JSONDecodeError, TypeError):
                    group_ids = []
            elif group_id_legacy:
                group_ids = [group_id_legacy]
            else:
                group_ids = []

            if not zone_code:
                return JsonResponse({'success': False, 'message': '缺少区域编号'}, status=400)
            if not group_ids:
                return JsonResponse({'success': False, 'message': '请先选择图形组'}, status=400)

            try:
                zone = Zone.objects.get(code=zone_code)
            except Zone.DoesNotExist:
                return JsonResponse({'success': False, 'message': f'区域 {zone_code} 不存在'}, status=404)

            # Build boundary from one or more groups
            # Multi-group format: [[outer1, hole1a, ...], [outer2, hole2a, ...]]
            # Single-group (backward compat): [outer, hole1, hole2, ...]
            target_groups = []
            for gid in group_ids:
                for g in (groups or []):
                    if g['id'] == gid:
                        target_groups.append(g)
                        break

            if not target_groups:
                return JsonResponse({'success': False, 'message': '图形组不存在'}, status=404)

            if len(target_groups) == 1:
                # Single group — flat ring list (backward compatible)
                tg = target_groups[0]
                boundary_rings = []
                outer_t = transformed[tg['outer']]
                boundary_rings.append(outer_t['vertices_latlng'])
                for hole_idx in tg['holes']:
                    hole_t = transformed[hole_idx]
                    boundary_rings.append(hole_t['vertices_latlng'])
                zone.dxf_boundary_points = boundary_rings
            else:
                # Multi group — nested format: [[group1_rings], [group2_rings], ...]
                boundary_groups = []
                for tg in target_groups:
                    group_rings = []
                    outer_t = transformed[tg['outer']]
                    group_rings.append(outer_t['vertices_latlng'])
                    for hole_idx in tg['holes']:
                        hole_t = transformed[hole_idx]
                        group_rings.append(hole_t['vertices_latlng'])
                    boundary_groups.append(group_rings)
                zone.dxf_boundary_points = boundary_groups

            zone.dxf_boundary_source = filename
            zone.boundary_source = 'dxf'
            zone.save()

            group_label = f'{len(target_groups)}个图形组' if len(target_groups) > 1 else '图形'
            return JsonResponse({
                'success': True,
                'message': f'已将{group_label}分配给区域 {zone.code}',
                'zone_id': zone.id,
                'zone_code': zone.code,
                'zone_name': zone.name,
                'boundary_source': zone.boundary_source,
                'dxf_boundary_points': zone.dxf_boundary_points,
                'area_display': zone.area_display,
            })

        # ── Switch boundary source ──
        if action == 'switch_source':
            zone_code = request.POST.get('zone_code', '').strip()
            source = request.POST.get('source', 'manual').strip()

            if source not in ('manual', 'dxf'):
                return JsonResponse({'success': False, 'message': '无效的来源类型'}, status=400)

            try:
                zone = Zone.objects.get(code=zone_code)
            except Zone.DoesNotExist:
                return JsonResponse({'success': False, 'message': f'区域 {zone_code} 不存在'}, status=404)

            if source == 'dxf' and not zone.dxf_boundary_points:
                return JsonResponse({'success': False, 'message': f'区域 {zone_code} 没有DXF边界数据'}, status=400)

            zone.boundary_source = source
            zone.save()

            label = 'DXF导入' if source == 'dxf' else '手动绘制'
            return JsonResponse({
                'success': True,
                'message': f'区域 {zone.code} 已切换为「{label}」',
                'zone_code': zone.code,
                'boundary_source': zone.boundary_source,
                'area_display': zone.area_display,
            })

        return JsonResponse({'success': False, 'message': '未知操作'}, status=400)

    # ── GET: render page ──
    all_zones = []
    for z in Zone.objects.select_related('patch').order_by('code').only(
        'id', 'code', 'name', 'patch_id', 'patch__name',
        'boundary_source', 'dxf_boundary_points',
    ):
        all_zones.append({
            'id': z.id,
            'code': z.code,
            'name': z.name,
            'patch_name': z.patch.name if z.patch else '',
            'boundary_source': z.boundary_source,
            'has_dxf_boundary': bool(z.dxf_boundary_points),
        })

    # All drawn zones for reference layer (use active boundary)
    all_drawn_zones = []
    for z in Zone.objects.select_related('patch').only(
        'id', 'code', 'name', 'boundary_points', 'dxf_boundary_points',
        'boundary_color', 'boundary_source',
        'label_lat', 'label_lng', 'label_scale', 'label_angle',
        'smooth_override', 'ring_display_modes', 'patch_id', 'patch__name'
    ):
        active_bp = z.active_boundary_points
        if not active_bp:
            continue
        all_drawn_zones.append({
            'id': z.id,
            'code': z.code,
            'name': z.name,
            'boundary_points': active_bp,
            'boundary_color': z.boundary_color,
            'label_lat': z.label_lat,
            'label_lng': z.label_lng,
            'label_scale': z.label_scale,
            'label_angle': z.label_angle,
            'smooth_override': z.smooth_override,
            'ring_display_modes': z.ring_display_modes or {},
            'patch_id': z.patch_id,
            'patch_name': z.patch.name if z.patch else '',
            'area_display': z.area_display,
        })

    # Restore session DXF data for page reload
    session_dxf = None
    if request.session.get('dxf_transformed'):
        session_dxf = {
            'shapes': request.session.get('dxf_shapes', []),
            'groups': request.session.get('dxf_groups', []),
            'transformed': request.session.get('dxf_transformed', []),
            'coord_info': request.session.get('dxf_coord_info', {}),
            'filename': request.session.get('dxf_filename', ''),
        }

    context = {
        'all_zones_json': json.dumps(all_zones),
        'all_drawn_zones_json': json.dumps(all_drawn_zones),
        'map_style_json': json.dumps(MapStyleSettings.get_style()),
        'session_dxf_json': json.dumps(session_dxf) if session_dxf else 'null',
    }
    return render(request, 'core/zone_dxf_import.html', context)
