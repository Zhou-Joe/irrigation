import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Avg, Sum
from django.views.decorators.http import require_POST
from django.http import JsonResponse
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


def _build_grouped_zones(zones_qs=None):
    """Build Patch→Zone grouped structure for template rendering.

    Groups zones by their Patch FK. Returns a list of
    dicts: {id, name, code, type, zone_count, zones: [{id, name, code, ...}]}
    Includes an 'orphan' group for zones without a patch.
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
            'patch_type': z.patch.type if z.patch else None,
            'patch_type_display': z.patch.get_type_display() if z.patch else None,
            'boundary_points': z.boundary_points,
            'boundary_color': z.boundary_color,
        })

    # Group by patch_id (preserving FK order)
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
            'type': zones[0]['patch_type'],
            'id': patch_id,
            'name': zones[0]['patch_name'],
            'code': zones[0]['patch_code'],
            'type_display': zones[0]['patch_type_display'],
            'zones': zones,
            'zone_count': len(zones),
        })

    if orphans:
        grouped.append({
            'type': 'orphan',
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
        if z.boundary_points:
            ref_zones.append({
                'id': z.id, 'name': z.name, 'code': z.code,
                'boundary_points': z.boundary_points,
                'boundary_color': z.boundary_color or '#52B788',
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
                'type': '现场工作人员',
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

    if is_multi:
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
        Pipeline
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

    # Get all zones with annotations
    zones = Zone.objects.all().annotate(
        plant_count=Count('plants', distinct=True),
        equipment_count=Count('equipments', distinct=True),
        pending_work_orders=Count(
            'work_orders',
            filter=Q(work_orders__status='pending'),
            distinct=True
        )
    )

    # Recent fault count (last 30 days)
    thirty_days_ago = today - timedelta(days=30)
    from django.db.models import Sum

    # Prepare zones data for template with center coordinates and detailed info
    zones_list = []
    for zone in zones:
        center = get_zone_center(zone.boundary_points)
        zone.center = center  # Add center as attribute for template access

        # Get pending requests for today (only water requests need approval markers)
        pending_requests = []

        # Water requests (by datetime range) - only these need approval markers
        for req in WaterRequest.objects.filter(
            zone=zone,
            status='submitted',
            start_datetime__date__lte=today,
            end_datetime__date__gte=today
        ):
            pending_requests.append({
                'id': req.id,
                'type': 'water',
                'type_display': '浇水协调',
            })

        # Get detailed zone info for cards
        # Recent maintenance requests (last 7 days)
        recent_maintenance = MaintenanceRequest.objects.filter(
            zone=zone,
            date__gte=week_ago
        ).order_by('-date')[:3]

        # Recent water requests
        recent_water = WaterRequest.objects.filter(
            zone=zone
        ).order_by('-created_at')[:3]

        # Recent project support
        recent_project = ProjectSupportRequest.objects.filter(
            zone=zone
        ).order_by('-created_at')[:3]

        # Counts for summary
        maintenance_count = MaintenanceRequest.objects.filter(zone=zone).count()
        water_count = WaterRequest.objects.filter(zone=zone).count()
        project_count = ProjectSupportRequest.objects.filter(zone=zone).count()

        # Recent fault count (last 30 days)
        from core.models import WorkReportFault
        recent_fault_count = WorkReportFault.objects.filter(
            work_report__zone_location=zone,
            work_report__date__gte=thirty_days_ago,
        ).aggregate(total=Sum('count'))['total'] or 0

        zones_list.append({
            'id': zone.id,
            'code': zone.code,
            'name': zone.name,
            'description': zone.description,
            'boundary_points': zone.boundary_points,
            'boundary_color': zone.boundary_color,
            'status': zone.get_today_status(),
            'statusDisplay': zone.get_status_display(),
            'plant_count': zone.plant_count or 0,
            'equipment_count': zone.equipment_count or 0,
            'pending_work_orders': zone.pending_work_orders or 0,
            'recent_fault_count': recent_fault_count,
            'center': center,
            'pending_requests': pending_requests,
            # Patch info
            'patch_id': zone.patch.id if zone.patch else None,
            'patch_name': zone.patch.name if zone.patch else None,
            'patch_code': zone.patch.code if zone.patch else None,
            'patch_type': zone.patch.type if zone.patch else None,
            'patch_type_display': zone.patch.get_type_display() if zone.patch else None,
            # Detailed info for cards
            'maintenance_count': maintenance_count,
            'water_count': water_count,
            'project_count': project_count,
            'recent_maintenance': [
                {
                    'id': m.id,
                    'date': m.date.strftime('%Y-%m-%d'),
                    'status': m.status,
                    'status_display': m.get_status_display(),
                    'work_content': m.work_content[:50] + '...' if len(m.work_content) > 50 else m.work_content,
                } for m in recent_maintenance
            ],
            'recent_water': [
                {
                    'id': w.id,
                    'type': w.get_request_type_display(),
                    'status': w.status,
                    'status_display': w.get_status_display(),
                    'start': w.start_datetime.strftime('%m-%d %H:%M'),
                    'end': w.end_datetime.strftime('%m-%d %H:%M'),
                } for w in recent_water
            ],
            'recent_project': [
                {
                    'id': p.id,
                    'date': p.date.strftime('%Y-%m-%d'),
                    'status': p.status,
                    'status_display': p.get_status_display(),
                    'work_content': p.work_content[:50] + '...' if len(p.work_content) > 50 else p.work_content,
                } for p in recent_project
            ],
        })

    # Group zones by patch for sidebar display
    from .models import Patch
    patches = Patch.objects.all().prefetch_related('zones')

    # Build grouped structure: patches with their zones, plus orphan zones (no patch)
    grouped_zones = []
    for patch in patches:
        patch_zones = [z for z in zones_list if z['patch_id'] == patch.id]
        if patch_zones:
            grouped_zones.append({
                'type': 'patch',
                'id': patch.id,
                'name': patch.name,
                'code': patch.code,
                'zones': patch_zones,
                'zone_count': len(patch_zones),
            })

    # Add orphan zones (zones without patch)
    orphan_zones = [z for z in zones_list if z['patch_id'] is None]
    if orphan_zones:
        grouped_zones.append({
            'type': 'orphan',
            'name': '未分配片区',
            'zones': orphan_zones,
            'zone_count': len(orphan_zones),
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
    for req in MaintenanceRequest.objects.filter(created_at__date__gte=week_ago).order_by('-created_at')[:5]:
        recent_activity.append({
            'type': 'maintenance',
            'type_display': '维护维修',
            'zone': req.zone.name,
            'date': req.created_at.strftime('%m-%d %H:%M'),
            'status': req.get_status_display(),
        })
    for req in WaterRequest.objects.filter(created_at__date__gte=week_ago).order_by('-created_at')[:5]:
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

    # Prepare pipelines data for map
    pipelines_list = []
    for pipeline in Pipeline.objects.all():
        pipelines_list.append({
            'id': pipeline.id,
            'code': pipeline.code,
            'name': pipeline.name,
            'pipeline_type': pipeline.pipeline_type,
            'pipeline_type_display': pipeline.get_pipeline_type_display(),
            'line_points': pipeline.line_points,
            'line_color': pipeline.line_color,
            'line_weight': pipeline.line_weight,
            'zone_names': list(pipeline.zones.values_list('name', flat=True)),
        })

    context = {
        'zones': zones,
        'zones_json': json.dumps(zones_list),
        'grouped_zones': grouped_zones,  # For hierarchical sidebar display
        'pipelines_json': json.dumps(pipelines_list),
        'is_admin': is_admin,
        'is_manager': is_manager,
        'is_dept_user': is_dept_user,
        'is_field_worker': is_field_worker,
        'pending_counts': pending_counts,
        'status_distribution': status_distribution,
        'recent_activity': recent_activity,
        'total_zones': len(zones_list),
        'total_plants': sum(z['plant_count'] for z in zones_list),
    }

    return render(request, 'core/dashboard.html', context)


@login_required(login_url='core:login')
def settings_page(request):
    """
    Settings page to manage zones and system configuration - admin only.
    """
    from .models import ManagerProfile, Pipeline, Patch

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
    # Only show site-type patches as 片区 in the UI
    site_patches = Patch.objects.filter(type=Patch.TYPE_SITE).order_by('code')

    # Precompute zone counts per patch (FK + derived from code prefix)
    grouped_zones_data = _build_grouped_zones(zones)
    patch_zone_counts = {}
    for group in grouped_zones_data:
        pid = group.get('id')
        if pid:
            patch_zone_counts[pid] = group['zone_count']

    # Precompute linked patch counts (children via parent FK)
    child_counts = {}
    for p in site_patches:
        child_counts[p.id] = p.children.count()

    context = {
        'zones': zones,
        'grouped_zones': grouped_zones_data,
        'status_choices': Zone.STATUS_CHOICES,
        'pipelines': pipelines,
        'site_patches': site_patches,
        'patch_zone_counts': patch_zone_counts,
        'child_counts': child_counts,
    }

    return render(request, 'core/settings.html', context)


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
        messages.error(request, '无权限修改区域')
        return redirect('core:dashboard')

    zone = get_object_or_404(Zone, pk=zone_id)

    if request.method == 'POST':
        zone.name = request.POST.get('name', zone.name)
        zone.code = request.POST.get('code', zone.code)
        zone.description = request.POST.get('description', zone.description)
        zone.boundary_color = request.POST.get('boundary_color', zone.boundary_color)

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
            messages.error(request, 'Invalid boundary points JSON format')
            return redirect('core:zone_edit', zone_id=zone.id)

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
                        scientific_name=item.get('scientific_name', ''),
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

        messages.success(request, f'Zone "{zone.name}" updated successfully.')
        return redirect('core:settings')

    # Get available plants (distinct names from all plants)
    available_plants = Plant.objects.values_list('name', flat=True).distinct().order_by('name')

    # Get zone equipment
    zone_equipments = zone.equipments.select_related('equipment').all()

    # Get all patches for selection
    patches = Patch.objects.all()

    ref_zones_json, ref_pipelines_json = _get_reference_map_data(exclude_zone_id=zone.id)

    context = {
        'zone': zone,
        'boundary_json': json.dumps(zone.boundary_points),
        'available_plants': available_plants,
        'zone_equipments': zone_equipments,
        'patches': patches,
        'ref_zones_json': ref_zones_json,
        'ref_pipelines_json': ref_pipelines_json,
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
        messages.error(request, '无权限创建区域')
        return redirect('core:dashboard')

    if request.method == 'POST':
        zone = Zone(
            name=request.POST.get('name'),
            code=request.POST.get('code'),
            description=request.POST.get('description', ''),
            boundary_color=request.POST.get('boundary_color', '#52B788'),
        )

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
            messages.error(request, 'Invalid boundary points JSON format')
            return render(request, 'core/zone_form.html', {
                'zone': zone,
                'boundary_json': boundary_json,
            })

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
                        scientific_name=item.get('scientific_name', ''),
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

        messages.success(request, f'Zone "{zone.name}" created successfully.')
        return redirect('core:settings')

    # Get available plants
    available_plants = Plant.objects.values_list('name', flat=True).distinct().order_by('name')

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
def zone_detail_page(request, zone_id):
    """
    Zone detail page showing plants, equipment, and stats.
    """
    from django.db.models import Sum
    from datetime import date, timedelta
    from .models import Plant, ZoneEquipment, WorkReport, WorkReportFault

    zone = get_object_or_404(Zone, pk=zone_id)
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)

    # Filter plants: current date is within the date range
    plants = Plant.objects.filter(zone=zone).filter(
        Q(planting_date__lte=today) | Q(planting_date__isnull=True)
    ).filter(
        Q(end_date__gte=today) | Q(end_date__isnull=True)
    ).order_by('name')

    # Filter equipment: installed and active
    equipment = ZoneEquipment.objects.filter(zone=zone).select_related('equipment').filter(
        Q(installation_date__lte=today) | Q(installation_date__isnull=True)
    ).filter(status__in=['working', 'needs_repair'])

    # Counts
    plant_count = plants.count()
    equipment_count = equipment.count()
    work_report_count = WorkReport.objects.filter(zone_location=zone).count()

    # Recent fault count (last 30 days)
    recent_fault_count = WorkReportFault.objects.filter(
        work_report__zone_location=zone,
        work_report__date__gte=thirty_days_ago,
    ).aggregate(total=Sum('count'))['total'] or 0

    # Add status_display to equipment
    for eq in equipment:
        eq.status_display = eq.get_status_display()
        eq.equipment_details = {
            'equipment_type_display': eq.equipment.get_equipment_type_display(),
            'manufacturer': eq.equipment.manufacturer,
            'model_name': eq.equipment.model_name,
        }

    context = {
        'zone': zone,
        'plants': plants,
        'equipment': equipment,
        'plant_count': plant_count,
        'equipment_count': equipment_count,
        'work_report_count': work_report_count,
        'recent_fault_count': recent_fault_count,
    }

    return render(request, 'core/zone_detail_page.html', context)


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
        p_type = request.POST.get('type', Patch.TYPE_SITE)
        description = request.POST.get('description', '').strip()

        if not name:
            messages.error(request, '片区名称不能为空')
        elif not code:
            messages.error(request, '片区编号不能为空')
        elif Patch.objects.filter(name=name).exists():
            messages.error(request, f'片区名称 "{name}" 已存在')
        elif Patch.objects.filter(code=code).exists():
            messages.error(request, f'片区编号 "{code}" 已存在')
        else:
            Patch.objects.create(name=name, code=code, type=Patch.TYPE_SITE, description=description)
            messages.success(request, f'片区 "{name}" 创建成功')
            return redirect('core:settings')

    return render(request, 'core/patch_form.html', {
        'mode': 'new',
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
            patch.name = name
            patch.code = code
            patch.description = description
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
                type=Patch.TYPE_STATION
            ).exclude(id__in=linked_ids).update(parent=None)
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

    # Linked patches (children via parent FK), grouped by type
    linked_patch_ids = set(patch.children.values_list('id', flat=True))
    linkable = Patch.objects.exclude(type__in=[Patch.TYPE_SITE, Patch.TYPE_PATCH]).order_by('type', 'code')
    linked_groups = []
    for ptype, plabel in Patch.TYPE_CHOICES:
        if ptype == Patch.TYPE_SITE:
            continue
        items = linkable.filter(type=ptype)
        if items.exists():
            linked_groups.append({
                'type': ptype,
                'label': plabel,
                'patches': items,
                'is_sync_managed': ptype == Patch.TYPE_STATION,
            })

    return render(request, 'core/patch_form.html', {
        'mode': 'edit',
        'patch': patch,
        'grouped_zones': grouped_zones,
        'selected_zone_ids': selected_zone_ids,
        'linked_patch_ids': linked_patch_ids,
        'linked_groups': linked_groups,
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
def equipment_catalog_autocomplete(request):
    """AJAX autocomplete endpoint for equipment catalog."""
    from .models import EquipmentCatalog

    equipment_type = request.GET.get('equipment_type', '')
    search = request.GET.get('search', '')

    results = []
    if search and len(search) >= 2:
        queryset = EquipmentCatalog.objects.all()

        if equipment_type:
            queryset = queryset.filter(equipment_type=equipment_type)

        queryset = queryset.filter(
            Q(model_name__icontains=search) |
            Q(manufacturer__icontains=search)
        )[:10]

        for item in queryset:
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
    """
    工单记录页面 - 显示所有维护维修、项目支持、浇水协调请求
    """
    from core.models import (
        MaintenanceRequest, ProjectSupportRequest, WaterRequest,
        ManagerProfile, DepartmentUserProfile, Worker
    )
    from datetime import date

    today = date.today()
    user = request.user

    # Determine role
    is_admin = user.is_superuser or user.is_staff
    current_worker = None
    current_dept_user = None

    if not is_admin:
        try:
            ManagerProfile.objects.get(user=user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass

    if not is_admin:
        try:
            current_worker = Worker.objects.get(user=user, active=True)
        except Worker.DoesNotExist:
            pass

    if not is_admin and not current_worker:
        try:
            current_dept_user = DepartmentUserProfile.objects.get(user=user, active=True)
        except DepartmentUserProfile.DoesNotExist:
            pass

    # Get requests and filter based on role
    all_requests = []

    # Maintenance requests - only admins and field workers
    if is_admin or current_worker:
        maintenance_qs = MaintenanceRequest.objects.select_related('zone', 'submitter')
        if current_worker:
            maintenance_qs = maintenance_qs.filter(submitter=current_worker)

        for req in maintenance_qs:
            all_requests.append({
                'id': req.id,
                'type': '维护与维修',
                'type_code': 'maintenance',
                'zone': req.zone,
                'submitter': req.submitter,
                'date': req.date,
                'status': req.status,
                'status_display': req.get_status_display(),
                'created_at': req.created_at,
                'detail': f"{req.start_time} - {req.end_time}, {req.participants}",
            })

    # Project support requests - only admins and field workers
    if is_admin or current_worker:
        project_qs = ProjectSupportRequest.objects.select_related('zone', 'submitter')
        if current_worker:
            project_qs = project_qs.filter(submitter=current_worker)

        for req in project_qs:
            all_requests.append({
                'id': req.id,
                'type': '项目支持',
                'type_code': 'project_support',
                'zone': req.zone,
                'submitter': req.submitter,
                'date': req.date,
                'status': req.status,
                'status_display': req.get_status_display(),
                'created_at': req.created_at,
                'detail': f"{req.start_time} - {req.end_time}, {req.participants}",
            })

    # Water requests - all roles can see
    # Dept users see ALL, field workers see own, admins see all
    water_qs = WaterRequest.objects.select_related('zone', 'submitter')
    if current_worker:
        water_qs = water_qs.filter(submitter=current_worker)
    # Note: Dept users and admins see all water requests

    for req in water_qs:
        all_requests.append({
            'id': req.id,
            'type': '浇水协调需求',
            'type_code': 'water',
            'zone': req.zone,
            'submitter': req.submitter,
            'date': req.start_datetime.date() if req.start_datetime else None,
            'status': req.status,
            'status_display': req.get_status_display(),
            'created_at': req.created_at,
            'detail': f"{req.get_request_type_display()} - {req.user_type}",
        })

    # 按创建时间倒序排列
    all_requests.sort(key=lambda x: x['created_at'], reverse=True)

    context = {
        'requests': all_requests,
        'today': today,
        'is_admin': is_admin,
        'is_dept_user': bool(current_dept_user),
        'is_field_worker': bool(current_worker),
    }

    return render(request, 'core/requests.html', context)


@login_required(login_url='core:login')
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
            'role_display': '现场工作人员',
            'active': w.active,
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
        'sites': Patch.objects.filter(type=Patch.TYPE_SITE).count(),
        'controllers': MaxicomController.objects.count(),
        'stations': Patch.objects.filter(type=Patch.TYPE_STATION).count(),
        'schedules': MaxicomSchedule.objects.count(),
        'flow_zones': MaxicomFlowZone.objects.count(),
        'weather_stations': MaxicomWeatherStation.objects.count(),
        'weather_logs': MaxicomWeatherLog.objects.count(),
        'events': MaxicomEvent.objects.count(),
        'locked_stations': Patch.objects.filter(type=Patch.TYPE_STATION, lockout=True).count(),
    }

    # Site hierarchy: sites with controller/station counts and station details
    sites = []
    for site in Patch.objects.filter(type=Patch.TYPE_SITE).all():
        ctrl_count = site.controllers.count()
        stn_count = site.children.filter(type=Patch.TYPE_STATION).count()
        sched_count = site.schedules.count()
        fz_count = site.flow_zones.count()

        # Station details for hierarchy table
        station_list = []
        for stn in site.children.filter(type=Patch.TYPE_STATION).all():
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
        'total': Patch.objects.filter(type=Patch.TYPE_STATION).count(),
        'locked': Patch.objects.filter(type=Patch.TYPE_STATION, lockout=True).count(),
        'active': Patch.objects.filter(type=Patch.TYPE_STATION, lockout=False).count(),
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
    from core.models import WorkReport, DemandRecord, Patch
    from core.role_utils import is_admin
    from django.db.models import Count, Q
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
    from core.models import WorkReport, DemandRecord
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
                    'backgroundColor': 'rgba(27, 67, 50, 0.7)',
                    'borderColor': 'rgba(27, 67, 50, 1)',
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
                    'backgroundColor': 'rgba(64, 145, 108, 0.7)',
                    'borderColor': 'rgba(64, 145, 108, 1)',
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
                    'backgroundColor': 'rgba(155, 34, 38, 0.7)',
                    'borderColor': 'rgba(155, 34, 38, 1)',
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


def work_reports_list(request):
    from core.models import WorkReport, Patch, WorkCategory, Worker
    from core.role_utils import is_admin

    user = request.user
    admin = is_admin(user)

    qs = WorkReport.objects.select_related(
        'worker', 'location', 'work_category', 'info_source'
    ).prefetch_related('fault_entries__fault_subtype').order_by('-date', '-id')

    if not admin:
        try:
            worker = user.worker_profile
            qs = qs.filter(worker=worker)
        except Exception:
            qs = qs.none()

    # Filters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    location_id = request.GET.get('location')
    work_category_id = request.GET.get('work_category')
    worker_id = request.GET.get('worker')
    difficult = request.GET.get('is_difficult')

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

    reports = qs[:200]
    locations = Patch.objects.filter(type=Patch.TYPE_LOCATION, active=True).order_by('order')
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
        },
    })


@login_required(login_url='core:login')
def work_report_detail(request, report_id):
    from core.models import WorkReport
    from core.role_utils import is_admin

    report = get_object_or_404(
        WorkReport.objects.select_related(
            'worker', 'location', 'work_category', 'info_source'
        ).prefetch_related('fault_entries__fault_subtype__category'),
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

    return render(request, 'core/work_report_detail.html', {
        'report': report,
        'fault_entries': report.fault_entries.select_related('fault_subtype__category').all(),
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

    locations = Patch.objects.filter(type=Patch.TYPE_LOCATION, active=True).order_by('order')
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
    locations = Patch.objects.filter(type=Patch.TYPE_LOCATION, active=True).order_by('order')
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
