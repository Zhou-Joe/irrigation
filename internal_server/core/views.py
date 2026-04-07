import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.views.decorators.http import require_POST
from core.models import Zone


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


def get_zone_center(boundary_points):
    """Calculate the center point of a zone from its boundary points."""
    if not boundary_points or len(boundary_points) == 0:
        return None

    lats = []
    lngs = []

    for point in boundary_points:
        if isinstance(point, list) and len(point) >= 2:
            lats.append(point[0])
            lngs.append(point[1])
        elif isinstance(point, dict) and 'lat' in point and 'lng' in point:
            lats.append(point['lat'])
            lngs.append(point['lng'])

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
    from datetime import date
    from core.models import (
        MaintenanceRequest, ProjectSupportRequest, WaterRequest,
        ManagerProfile, DepartmentUserProfile, RegistrationRequest, WorkOrder, Worker
    )

    user = request.user
    today = date.today()

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
        pending_work_orders=Count(
            'work_orders',
            filter=Q(work_orders__status='pending'),
            distinct=True
        )
    )

    # Prepare zones data for template with center coordinates
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
            'pending_work_orders': zone.pending_work_orders or 0,
            'center': center,
            'pending_requests': pending_requests,
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

    context = {
        'zones': zones,
        'zones_json': json.dumps(zones_list),
        'is_admin': is_admin,
        'is_manager': is_manager,
        'is_dept_user': is_dept_user,
        'is_field_worker': is_field_worker,
        'pending_counts': pending_counts,
    }

    return render(request, 'core/dashboard.html', context)


@login_required(login_url='core:login')
def settings_page(request):
    """
    Settings page to manage zones and system configuration.
    """
    zones = Zone.objects.all().order_by('code')

    context = {
        'zones': zones,
        'status_choices': Zone.STATUS_CHOICES,
    }

    return render(request, 'core/settings.html', context)


@login_required(login_url='core:login')
def zone_edit(request, zone_id):
    """
    Edit a specific zone.
    """
    from core.models import Plant
    zone = get_object_or_404(Zone, pk=zone_id)

    if request.method == 'POST':
        zone.name = request.POST.get('name', zone.name)
        zone.code = request.POST.get('code', zone.code)
        zone.description = request.POST.get('description', zone.description)
        zone.boundary_color = request.POST.get('boundary_color', zone.boundary_color)

        # Parse boundary points from JSON
        boundary_json = request.POST.get('boundary_points', '[]')
        try:
            zone.boundary_points = json.loads(boundary_json)
        except json.JSONDecodeError:
            messages.error(request, 'Invalid boundary points JSON format')
            return redirect('core:zone_edit', zone_id=zone.id)

        zone.save()

        # Handle plants - just names, comma separated in hidden field
        plants_data = request.POST.get('plants_data', '')
        if plants_data:
            plant_names = [p.strip() for p in plants_data.split(',') if p.strip()]

            # Clear existing plants for this zone
            zone.plants.all().delete()

            # Add new plants
            for name in plant_names:
                Plant.objects.create(zone=zone, name=name)

        messages.success(request, f'Zone "{zone.name}" updated successfully.')
        return redirect('core:settings')

    # Get available plants (distinct names from all plants)
    available_plants = Plant.objects.values_list('name', flat=True).distinct().order_by('name')

    context = {
        'zone': zone,
        'boundary_json': json.dumps(zone.boundary_points),
        'available_plants': available_plants,
    }

    return render(request, 'core/zone_form.html', context)


@login_required(login_url='core:login')
def zone_new(request):
    """
    Create a new zone.
    """
    from core.models import Plant

    if request.method == 'POST':
        zone = Zone(
            name=request.POST.get('name'),
            code=request.POST.get('code'),
            description=request.POST.get('description', ''),
            boundary_color=request.POST.get('boundary_color', '#52B788'),
        )

        # Parse boundary points from JSON
        boundary_json = request.POST.get('boundary_points', '[]')
        try:
            zone.boundary_points = json.loads(boundary_json)
        except json.JSONDecodeError:
            messages.error(request, 'Invalid boundary points JSON format')
            return render(request, 'core/zone_form.html', {
                'zone': zone,
                'boundary_json': boundary_json,
            })

        zone.save()

        # Handle plants - just names
        plants_data = request.POST.get('plants_data', '')
        if plants_data:
            plant_names = [p.strip() for p in plants_data.split(',') if p.strip()]
            for name in plant_names:
                Plant.objects.create(zone=zone, name=name)

        messages.success(request, f'Zone "{zone.name}" created successfully.')
        return redirect('core:settings')

    # Get available plants
    available_plants = Plant.objects.values_list('name', flat=True).distinct().order_by('name')

    context = {
        'zone': None,
        'boundary_json': '[]',
        'available_plants': available_plants,
    }

    return render(request, 'core/zone_form.html', context)


@require_POST
@login_required(login_url='core:login')
def zone_delete(request, zone_id):
    """
    Delete a zone.
    """
    zone = get_object_or_404(Zone, pk=zone_id)
    zone_name = zone.name
    zone.delete()
    messages.success(request, f'Zone "{zone_name}" deleted successfully.')
    return redirect('core:settings')


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
    """
    更新工单状态（管理员操作）
    """
    from core.models import MaintenanceRequest, ProjectSupportRequest, WaterRequest, Worker
    from django.utils import timezone

    # 检查是否是管理员（超级用户、staff 或 Worker 的 ADM 用户）
    is_admin = request.user.is_superuser or request.user.is_staff

    if not is_admin:
        try:
            worker = Worker.objects.get(user=request.user)
            if worker.employee_id.startswith('ADM'):
                is_admin = True
        except Worker.DoesNotExist:
            pass

    if not is_admin:
        messages.error(request, '无权限操作')
        return redirect('core:request_detail', type_code=type_code, request_id=request_id)

    # 获取 approver（Worker 或 None）
    try:
        approver = Worker.objects.get(user=request.user)
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
    """
    from core.models import RegistrationRequest

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        requested_role = request.POST.get('requested_role', 'field_worker').strip()
        employee_id = request.POST.get('employee_id', '').strip()
        department = request.POST.get('department', '')
        department_other = request.POST.get('department_other', '').strip()

        # Valid role choices
        valid_roles = ['field_worker', 'dept_user', 'manager']

        # Validation
        if not full_name:
            messages.error(request, '请输入姓名')
        elif not phone:
            messages.error(request, '请输入手机号')
        elif not requested_role or requested_role not in valid_roles:
            messages.error(request, '请选择有效的角色')
        elif not department:
            messages.error(request, '请选择部门')
        elif department == '其他' and not department_other:
            messages.error(request, '请输入其他部门名称')
        elif RegistrationRequest.objects.filter(phone=phone, status='pending').exists():
            messages.error(request, '该手机号已有待审批的注册申请')
        elif employee_id and RegistrationRequest.objects.filter(employee_id=employee_id, status='pending').exists():
            messages.error(request, '该工号已有待审批的注册申请')
        else:
            RegistrationRequest.objects.create(
                full_name=full_name,
                phone=phone,
                department=department,
                department_other=department_other if department == '其他' else '',
                requested_role=requested_role,
                employee_id=employee_id
            )
            messages.success(request, '注册申请已提交，请等待管理员审批')
            return redirect('core:register')

    return render(request, 'core/register.html')
