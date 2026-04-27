from rest_framework import serializers, viewsets, permissions, status, authentication
from rest_framework.decorators import api_view, permission_classes, authentication_classes, action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.contrib.auth import authenticate, login
from django.utils import timezone
from django.db import models
from datetime import timedelta, date
from .models import Zone, Plant, Worker, WorkOrder, Event, WorkLog, WeatherData, MaintenanceRequest, ProjectSupportRequest, WaterRequest, ManagerProfile, DepartmentUserProfile, EquipmentCatalog, ZoneEquipment, Pipeline, Patch, WorkCategory, InfoSource, FaultCategory, FaultSubType, WorkReport, WorkReportFault, DemandCategory, DemandDepartment, DemandRecord
from .authentication import TokenAuthentication
from .permissions import IsAdminOrReadOnly, IsOwnerOrAdmin, IsDeptUserWaterOnly, IsFieldWorker


# Custom permission for token OR session auth
class IsAuthenticatedByTokenOrSession(permissions.BasePermission):
    """
    Allow access if authenticated via token OR Django session.
    Used to support both mobile app (token) and admin (session) authentication.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


# Login endpoint for mobile app
@api_view(['POST'])
@permission_classes([AllowAny])
def worker_login(request):
    """
    Authenticate a user by username and password.
    Returns the user's API token and role info on success.
    Supports: field_worker, manager, dept_user roles
    """
    username = request.data.get('username')
    password = request.data.get('password')

    if not username or not password:
        return Response(
            {'error': 'username and password are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Try to authenticate with Django auth
    from django.contrib.auth import authenticate
    user = authenticate(request, username=username, password=password)

    if user is None or not user.is_authenticated:
        return Response(
            {'error': '用户名或密码错误'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    # Determine user role and get profile
    role = None
    profile_data = {}

    # Check for Manager profile
    try:
        manager = ManagerProfile.objects.get(user=user, active=True)
        role = 'manager'
        profile_data = {
            'id': manager.id,
            'username': user.username,
            'employee_id': manager.employee_id,
            'full_name': manager.full_name,
            'phone': manager.phone,
            'role': 'manager',
            'is_super_admin': manager.is_super_admin,
            'can_approve_registrations': manager.can_approve_registrations,
            'can_approve_work_orders': manager.can_approve_work_orders,
        }
        token = str(manager.api_token)
    except ManagerProfile.DoesNotExist:
        pass

    # Check for Department User profile
    if role is None:
        try:
            dept_user = DepartmentUserProfile.objects.get(user=user, active=True)
            role = 'dept_user'
            profile_data = {
                'id': dept_user.id,
                'username': user.username,
                'employee_id': dept_user.employee_id,
                'full_name': dept_user.full_name,
                'phone': dept_user.phone,
                'role': 'dept_user',
                'department': dept_user.department,
                'department_other': dept_user.department_other,
            }
            token = str(dept_user.api_token)
        except DepartmentUserProfile.DoesNotExist:
            pass

    # Check for Worker profile (field worker)
    if role is None:
        try:
            worker = Worker.objects.get(user=user, active=True)
            role = 'field_worker'
            profile_data = {
                'id': worker.id,
                'username': user.username,
                'employee_id': worker.employee_id,
                'full_name': worker.full_name,
                'phone': worker.phone,
                'role': 'field_worker',
                'department': worker.department,
                'department_other': worker.department_other,
            }
            token = str(worker.api_token)
        except Worker.DoesNotExist:
            pass

    # Check for superuser (super admin)
    if role is None and user.is_superuser:
        role = 'super_admin'
        profile_data = {
            'id': user.id,
            'username': user.username,
            'full_name': user.first_name or user.username,
            'role': 'super_admin',
        }
        token = str(user.id)

    if role is None:
        return Response(
            {'error': '用户未关联任何角色，请联系管理员'},
            status=status.HTTP_403_FORBIDDEN
        )

    return Response({
        'token': token,
        'user': profile_data,
    })


# Serializers
class ZoneSerializer(serializers.ModelSerializer):
    """Serializer for Zone model - returns today's status based on requests."""

    # 当天状态（由工单决定）
    status = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    pending_requests = serializers.SerializerMethodField()
    center = serializers.SerializerMethodField()
    # Patch info for grouping
    patch_id = serializers.SerializerMethodField()
    patch_name = serializers.SerializerMethodField()
    patch_code = serializers.SerializerMethodField()
    patch_type = serializers.SerializerMethodField()
    patch_type_display = serializers.SerializerMethodField()

    class Meta:
        model = Zone
        fields = [
            'id', 'name', 'code', 'description', 'boundary_points',
            'boundary_color', 'status', 'status_display',
            'pending_requests', 'center',
            'patch_id', 'patch_name', 'patch_code',
            'patch_type', 'patch_type_display',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_patch_id(self, obj):
        return obj.patch.id if obj.patch else None

    def get_patch_name(self, obj):
        return obj.patch.name if obj.patch else None

    def get_patch_code(self, obj):
        return obj.patch.code if obj.patch else None

    def get_patch_type(self, obj):
        return obj.patch.type if obj.patch else None

    def get_patch_type_display(self, obj):
        return obj.patch.get_type_display() if obj.patch else None

    def get_status(self, obj):
        """返回当天状态。"""
        return obj.get_today_status()

    def get_status_display(self, obj):
        """返回当天状态的中文显示。"""
        return obj.get_status_display()

    def get_pending_requests(self, obj):
        """返回待审批的浇水协调需求。"""
        from datetime import date
        today = date.today()
        pending = []
        for req in WaterRequest.objects.filter(
            zone=obj,
            status='submitted',
            start_datetime__date__lte=today,
            end_datetime__date__gte=today
        ):
            pending.append({
                'id': req.id,
                'type': 'water',
                'type_display': '浇水协调',
                'request_type': req.get_request_type_display(),
                'start_datetime': req.start_datetime.isoformat() if req.start_datetime else None,
                'end_datetime': req.end_datetime.isoformat() if req.end_datetime else None,
            })
        return pending

    def get_center(self, obj):
        """返回区域中心坐标。"""
        from core.views import get_zone_center
        return get_zone_center(obj.boundary_points)


class PlantSerializer(serializers.ModelSerializer):
    """Serializer for Plant model."""

    class Meta:
        model = Plant
        fields = ['id', 'zone', 'name', 'scientific_name', 'quantity', 'planting_date', 'end_date', 'notes']


class EquipmentCatalogSerializer(serializers.ModelSerializer):
    """Serializer for EquipmentCatalog model."""
    equipment_type_display = serializers.CharField(source='get_equipment_type_display', read_only=True)

    class Meta:
        model = EquipmentCatalog
        fields = ['id', 'equipment_type', 'equipment_type_display', 'model_name', 'manufacturer', 'specifications', 'created_at', 'updated_at']


class ZoneEquipmentSerializer(serializers.ModelSerializer):
    """Serializer for ZoneEquipment model."""
    equipment_details = EquipmentCatalogSerializer(source='equipment', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ZoneEquipment
        fields = ['id', 'zone', 'equipment', 'equipment_details', 'quantity', 'installation_date', 'status', 'status_display', 'location_in_zone', 'notes', 'created_at', 'updated_at']


class WorkerSerializer(serializers.ModelSerializer):
    """Serializer for Worker model."""

    class Meta:
        model = Worker
        fields = [
            'id', 'user', 'employee_id', 'full_name', 'phone',
            'active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class WorkOrderSerializer(serializers.ModelSerializer):
    """Serializer for WorkOrder model."""

    class Meta:
        model = WorkOrder
        fields = [
            'id', 'zone', 'assigned_to', 'title', 'description',
            'status', 'priority', 'scheduled_date', 'due_date',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class EventSerializer(serializers.ModelSerializer):
    """Serializer for Event model."""

    class Meta:
        model = Event
        fields = ['id', 'name', 'description', 'start_date', 'end_date', 'affects_zones', 'created_at']
        read_only_fields = ['created_at']


class WorkLogSerializer(serializers.ModelSerializer):
    """Serializer for WorkLog model."""

    class Meta:
        model = WorkLog
        fields = [
            'id', 'zone', 'worker', 'work_order', 'work_type',
            'notes', 'latitude', 'longitude', 'work_timestamp',
            'uploaded_at', 'relay_id'
        ]
        read_only_fields = ['uploaded_at']


class MaintenanceRequestSerializer(serializers.ModelSerializer):
    """Serializer for MaintenanceRequest model."""

    zone_name = serializers.CharField(source='zone.name', read_only=True)
    submitter_name = serializers.CharField(source='submitter.full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    approver_name = serializers.CharField(source='approver.full_name', read_only=True)

    class Meta:
        model = MaintenanceRequest
        fields = [
            'id', 'zone', 'zone_name', 'submitter', 'submitter_name',
            'status', 'status_display', 'status_notes',
            'approver', 'approver_name', 'processed_at',
            'date', 'start_time', 'end_time',
            'participants', 'work_content', 'materials', 'feedback', 'photos',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['submitter', 'approver', 'processed_at', 'created_at', 'updated_at']


class ProjectSupportRequestSerializer(serializers.ModelSerializer):
    """Serializer for ProjectSupportRequest model."""

    zone_name = serializers.CharField(source='zone.name', read_only=True)
    submitter_name = serializers.CharField(source='submitter.full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    approver_name = serializers.CharField(source='approver.full_name', read_only=True)

    class Meta:
        model = ProjectSupportRequest
        fields = [
            'id', 'zone', 'zone_name', 'submitter', 'submitter_name',
            'status', 'status_display', 'status_notes',
            'approver', 'approver_name', 'processed_at',
            'date', 'start_time', 'end_time',
            'participants', 'work_content', 'materials', 'feedback', 'photos',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['submitter', 'approver', 'processed_at', 'created_at', 'updated_at']


class WaterRequestSerializer(serializers.ModelSerializer):
    """Serializer for WaterRequest model."""

    zone_name = serializers.CharField(source='zone.name', read_only=True)
    submitter_name = serializers.CharField(source='submitter.full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    user_type_display = serializers.CharField(source='get_user_type_display', read_only=True)
    request_type_display = serializers.CharField(source='get_request_type_display', read_only=True)
    approver_name = serializers.CharField(source='approver.full_name', read_only=True)

    class Meta:
        model = WaterRequest
        fields = [
            'id', 'zone', 'zone_name', 'submitter', 'submitter_name',
            'status', 'status_display', 'status_notes',
            'approver', 'approver_name', 'processed_at',
            'user_type', 'user_type_display', 'user_type_other',
            'request_type', 'request_type_display', 'request_type_other',
            'start_datetime', 'end_datetime', 'photos',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['submitter', 'approver', 'processed_at', 'created_at', 'updated_at']


class AllRequestsSerializer(serializers.Serializer):
    """Combined serializer for all request types for the status list."""

    id = serializers.IntegerField()
    type = serializers.CharField()
    zone = serializers.CharField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    date = serializers.CharField()
    user = serializers.CharField()
    created_at = serializers.DateTimeField()


# ViewSets
class ZoneViewSet(viewsets.ModelViewSet):
    """ViewSet for Zone - all authenticated users can read, only admin can write."""

    queryset = Zone.objects.all()
    serializer_class = ZoneSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAdminOrReadOnly]

    def perform_create(self, serializer):
        """Auto-close boundary polygons before saving."""
        from .views import auto_close_boundary_points
        boundary_points = serializer.validated_data.get('boundary_points', [])
        serializer.save(boundary_points=auto_close_boundary_points(boundary_points))

    def perform_update(self, serializer):
        """Auto-close boundary polygons before saving."""
        from .views import auto_close_boundary_points
        boundary_points = serializer.validated_data.get('boundary_points', [])
        serializer.save(boundary_points=auto_close_boundary_points(boundary_points))

    @action(detail=True, methods=['get'], url_path='zone-detail')
    def zone_detail(self, request, pk=None):
        zone = self.get_object()
        today = date.today()

        # Filter plants: current date is within the date range
        # planting_date <= today (or null) AND (end_date >= today or end_date IS NULL)
        plants = Plant.objects.filter(zone=zone).filter(
            models.Q(planting_date__lte=today) | models.Q(planting_date__isnull=True)
        ).filter(
            models.Q(end_date__gte=today) | models.Q(end_date__isnull=True)
        )

        # Filter equipment: installation_date <= today (or null) AND status is active (working or needs_repair)
        equipment = ZoneEquipment.objects.filter(zone=zone).select_related('equipment').filter(
            models.Q(installation_date__lte=today) | models.Q(installation_date__isnull=True)
        ).filter(status__in=['working', 'needs_repair'])

        work_report_count = WorkReport.objects.filter(zone_location=zone).count()

        from django.db.models import Count, Sum
        from datetime import timedelta
        thirty_days_ago = today - timedelta(days=30)
        recent_fault_count = WorkReportFault.objects.filter(
            work_report__zone_location=zone,
            work_report__date__gte=thirty_days_ago,
        ).aggregate(total=Sum('count'))['total'] or 0

        return Response({
            'id': zone.id,
            'name': zone.name,
            'code': zone.code,
            'description': zone.description or '',
            'status': zone.get_today_status(),
            'status_display': zone.get_status_display(),
            'boundary_color': zone.boundary_color,
            'plants': PlantSerializer(plants, many=True).data,
            'equipment': ZoneEquipmentSerializer(equipment, many=True).data,
            'plant_count': plants.count(),
            'equipment_count': equipment.count(),
            'work_report_count': work_report_count,
            'recent_fault_count': recent_fault_count,
        })


class PlantViewSet(viewsets.ModelViewSet):
    queryset = Plant.objects.all()
    serializer_class = PlantSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAdminOrReadOnly]


class EquipmentCatalogViewSet(viewsets.ModelViewSet):
    """ViewSet for EquipmentCatalog - admin only for write."""
    queryset = EquipmentCatalog.objects.all()
    serializer_class = EquipmentCatalogSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        queryset = super().get_queryset()
        equipment_type = self.request.query_params.get('equipment_type')
        search = self.request.query_params.get('search')

        if equipment_type:
            queryset = queryset.filter(equipment_type=equipment_type)

        if search:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(model_name__icontains=search) |
                Q(manufacturer__icontains=search)
            )

        return queryset


class ZoneEquipmentViewSet(viewsets.ModelViewSet):
    """ViewSet for ZoneEquipment - admin only for write."""
    queryset = ZoneEquipment.objects.all()
    serializer_class = ZoneEquipmentSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        queryset = super().get_queryset()
        zone_id = self.request.query_params.get('zone')
        zone_code = self.request.query_params.get('zone_code')
        if zone_id:
            queryset = queryset.filter(zone_id=zone_id)
        if zone_code:
            queryset = queryset.filter(zone__code=zone_code)
        return queryset


class WorkerViewSet(viewsets.ModelViewSet):
    """ViewSet for Worker - admin only for write."""
    queryset = Worker.objects.all()
    serializer_class = WorkerSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAdminOrReadOnly]


class WorkOrderViewSet(viewsets.ModelViewSet):
    queryset = WorkOrder.objects.all()
    serializer_class = WorkOrderSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAdminOrReadOnly]


class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAdminOrReadOnly]


class WorkLogViewSet(viewsets.ModelViewSet):
    """ViewSet for WorkLog - admin sees all, field workers see own."""
    queryset = WorkLog.objects.all()
    serializer_class = WorkLogSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsOwnerOrAdmin]

    def get_queryset(self):
        from .role_utils import is_admin, get_worker_for_user
        if is_admin(self.request.user):
            return WorkLog.objects.all()
        worker = get_worker_for_user(self.request.user)
        if worker:
            return WorkLog.objects.filter(worker=worker)
        return WorkLog.objects.none()


class MaintenanceRequestViewSet(viewsets.ModelViewSet):
    """ViewSet for MaintenanceRequest - dept users cannot access."""
    queryset = MaintenanceRequest.objects.all().order_by('-created_at')
    serializer_class = MaintenanceRequestSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsOwnerOrAdmin]

    def get_queryset(self):
        from .role_utils import is_admin, is_dept_user, get_worker_for_user
        if is_dept_user(self.request.user):
            return MaintenanceRequest.objects.none()
        if is_admin(self.request.user):
            return MaintenanceRequest.objects.all().order_by('-created_at')
        worker = get_worker_for_user(self.request.user)
        if worker:
            return MaintenanceRequest.objects.filter(submitter=worker).order_by('-created_at')
        return MaintenanceRequest.objects.none()

    def perform_create(self, serializer):
        # request.user is Worker when using token auth, or User when using session auth
        if isinstance(self.request.user, Worker):
            serializer.save(submitter=self.request.user)
        else:
            serializer.save(submitter=self.request.user.worker_profile)


class ProjectSupportRequestViewSet(viewsets.ModelViewSet):
    """ViewSet for ProjectSupportRequest - dept users cannot access."""
    queryset = ProjectSupportRequest.objects.all().order_by('-created_at')
    serializer_class = ProjectSupportRequestSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsOwnerOrAdmin]

    def get_queryset(self):
        from .role_utils import is_admin as is_admin_user, is_dept_user, get_worker_for_user
        if is_dept_user(self.request.user):
            return ProjectSupportRequest.objects.none()
        if is_admin_user(self.request.user):
            return ProjectSupportRequest.objects.all().order_by('-created_at')
        worker = get_worker_for_user(self.request.user)
        if worker:
            return ProjectSupportRequest.objects.filter(submitter=worker).order_by('-created_at')
        return ProjectSupportRequest.objects.none()

    def perform_create(self, serializer):
        if isinstance(self.request.user, Worker):
            serializer.save(submitter=self.request.user)
        else:
            serializer.save(submitter=self.request.user.worker_profile)


class WaterRequestViewSet(viewsets.ModelViewSet):
    """ViewSet for WaterRequest - all roles can access with different permissions."""
    queryset = WaterRequest.objects.all().order_by('-created_at')
    serializer_class = WaterRequestSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsOwnerOrAdmin]

    def get_queryset(self):
        from .role_utils import is_admin, is_dept_user, get_worker_for_user
        if is_dept_user(self.request.user):
            return WaterRequest.objects.all().order_by('-created_at')
        if is_admin(self.request.user):
            return WaterRequest.objects.all().order_by('-created_at')
        worker = get_worker_for_user(self.request.user)
        if worker:
            return WaterRequest.objects.filter(submitter=worker).order_by('-created_at')
        return WaterRequest.objects.none()

    def perform_create(self, serializer):
        if isinstance(self.request.user, Worker):
            serializer.save(submitter=self.request.user)
        else:
            serializer.save(submitter=self.request.user.worker_profile)


@api_view(['GET'])
@permission_classes([AllowAny])
@authentication_classes([TokenAuthentication, authentication.SessionAuthentication])
def get_all_requests(request):
    """Get all requests combined for the status list.

    Role-based filtering:
    - Dept users: Only see water requests (all)
    - Managers/Admins: See all requests (all)
    - Field workers: See their own requests only
    """
    user = request.user
    role = None
    profile = None

    # Determine user role - handle both Django User and profile model instances
    if isinstance(user, ManagerProfile):
        role = 'admin'
        profile = user
    elif isinstance(user, DepartmentUserProfile):
        role = 'dept_user'
        profile = user
    elif isinstance(user, Worker):
        role = 'field_worker'
        profile = user
    elif getattr(user, 'is_superuser', False) or getattr(user, 'is_staff', False):
        role = 'admin'
    else:
        # Check for Manager profile
        try:
            manager = ManagerProfile.objects.get(user=user, active=True)
            role = 'manager'
            profile = manager
        except ManagerProfile.DoesNotExist:
            pass

        # Check for Department User profile
        if role is None:
            try:
                dept_user = DepartmentUserProfile.objects.get(user=user, active=True)
                role = 'dept_user'
                profile = dept_user
            except DepartmentUserProfile.DoesNotExist:
                pass

        # Check for Worker profile (field worker)
        if role is None:
            try:
                worker = Worker.objects.get(user=user, active=True)
                role = 'field_worker'
                profile = worker
            except Worker.DoesNotExist:
                pass

    results = []

    # Maintenance requests - only for non-dept users
    if role != 'dept_user':
        maintenance_qs = MaintenanceRequest.objects.all()
        if role == 'field_worker' and profile:
            maintenance_qs = maintenance_qs.filter(submitter=profile)

        for req in maintenance_qs:
            results.append({
                'id': req.id,
                'type': '维护与维修',
                'type_code': 'maintenance',
                'zone': req.zone.name,
                'status': req.status,
                'status_display': req.get_status_display(),
                'date': str(req.date),
                'user': req.submitter.full_name,
                'created_at': req.created_at,
            })

    # Project support requests - only for non-dept users
    if role != 'dept_user':
        project_qs = ProjectSupportRequest.objects.all()
        if role == 'field_worker' and profile:
            project_qs = project_qs.filter(submitter=profile)

        for req in project_qs:
            results.append({
                'id': req.id,
                'type': '项目支持',
                'type_code': 'project_support',
                'zone': req.zone.name,
                'status': req.status,
                'status_display': req.get_status_display(),
                'date': str(req.date),
                'user': req.submitter.full_name,
                'created_at': req.created_at,
            })

    # Water requests - all roles can see (dept users see all, others filtered)
    water_qs = WaterRequest.objects.all()
    if role == 'field_worker' and profile:
        water_qs = water_qs.filter(submitter=profile)

    for req in water_qs:
        results.append({
            'id': req.id,
            'type': '浇水协调需求',
            'type_code': 'water',
            'zone': req.zone.name,
            'status': req.status,
            'status_display': req.get_status_display(),
            'date': str(req.start_datetime.date()),
            'user': req.submitter.full_name,
            'created_at': req.created_at,
        })

    # Sort by created_at descending
    results.sort(key=lambda x: x['created_at'], reverse=True)

    return Response(results)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_weather(request):
    """Get weather data for current hour, 1 hour before, and 4 hours after."""
    lat = request.query_params.get('lat')
    lon = request.query_params.get('lon')

    now = timezone.localtime()  # Use local time (Shanghai)
    current_hour = now.hour
    today = now.date()

    queryset = WeatherData.objects.filter(date=today)

    if lat and lon:
        queryset = queryset.filter(
            latitude=round(float(lat), 5),
            longitude=round(float(lon), 5)
        )

    weather_record = queryset.first()

    if not weather_record:
        return Response({'current_hour': current_hour, 'count': 0, 'data': []})

    # Filter hourly data: 1 hour before to 4 hours after
    hourly_data = weather_record.hourly_data or []
    filtered_data = []

    for h in hourly_data:
        hour = h.get('hour')
        if hour is not None and current_hour - 1 <= hour <= current_hour + 4:
            filtered_data.append({
                'hour': hour,
                'temperature': h.get('temp'),
                'humidity': h.get('humidity'),
                'precipitation': h.get('precip'),
                'wind_speed': h.get('wind'),
                'weather_code': h.get('code'),
                'weather_description': weather_record.get_weather_description(h.get('code')),
            })

    return Response({
        'current_hour': current_hour,
        'date': str(today),
        'count': len(filtered_data),
        'data': filtered_data
    })


class PipelineSerializer(serializers.ModelSerializer):
    line_color = serializers.ReadOnlyField()
    pipeline_type_display = serializers.CharField(source='get_pipeline_type_display', read_only=True)
    zone_names = serializers.SerializerMethodField()

    class Meta:
        model = Pipeline
        fields = [
            'id', 'name', 'code', 'description',
            'pipeline_type', 'pipeline_type_display',
            'line_points', 'line_color', 'line_weight',
            'zones', 'zone_names',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_zone_names(self, obj):
        return list(obj.zones.values_list('name', flat=True))


class PipelineViewSet(viewsets.ModelViewSet):
    queryset = Pipeline.objects.all()
    serializer_class = PipelineSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAdminOrReadOnly]


# ==========================================================================
# 维修工单系统 API
# ==========================================================================


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patch
        fields = ['id', 'name', 'code', 'order', 'active']


class WorkCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkCategory
        fields = ['id', 'name', 'code', 'order', 'active']


class InfoSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = InfoSource
        fields = ['id', 'name', 'code', 'order', 'active']


class FaultSubTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = FaultSubType
        fields = ['id', 'category', 'name_zh', 'name_en', 'code', 'order', 'active']


class FaultCategorySerializer(serializers.ModelSerializer):
    sub_types = FaultSubTypeSerializer(many=True, read_only=True)

    class Meta:
        model = FaultCategory
        fields = ['id', 'name_zh', 'name_en', 'order', 'active', 'sub_types']


class WorkReportFaultSerializer(serializers.ModelSerializer):
    fault_subtype_name = serializers.CharField(source='fault_subtype.name_zh', read_only=True)
    fault_category_name = serializers.CharField(source='fault_subtype.category.name_zh', read_only=True)
    equipment_details = ZoneEquipmentSerializer(source='equipment', read_only=True)

    class Meta:
        model = WorkReportFault
        fields = ['fault_subtype', 'count', 'fault_subtype_name', 'fault_category_name', 'equipment', 'equipment_details']


class WorkReportSerializer(serializers.ModelSerializer):
    fault_entries = WorkReportFaultSerializer(many=True, required=False)
    worker_name = serializers.CharField(source='worker.full_name', read_only=True)
    patch = serializers.IntegerField(write_only=True, required=True, source='location_id')
    location_name = serializers.CharField(source='location.name', read_only=True, default=None)
    work_category_name = serializers.CharField(source='work_category.name', read_only=True, default=None)
    info_source_name = serializers.CharField(source='info_source.name', read_only=True, default=None)
    zone_location_code = serializers.CharField(write_only=True, required=False, allow_null=True, allow_blank=True)
    zone_location_display = serializers.SerializerMethodField()
    total_faults = serializers.SerializerMethodField()
    photo_urls = serializers.SerializerMethodField()

    class Meta:
        model = WorkReport
        fields = [
            'id', 'date', 'weather', 'worker', 'worker_name',
            'patch', 'location_name', 'work_category', 'work_category_name',
            'zone_location', 'zone_location_code', 'zone_location_display',
            'remark', 'info_source', 'info_source_name',
            'is_difficult', 'is_difficult_resolved',
            'fault_entries', 'total_faults', 'photos', 'photo_urls',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']
        extra_kwargs = {
            'zone_location': {'required': False, 'allow_null': True},
            'worker': {'required': False},
        }

    def get_total_faults(self, obj):
        return sum(e.count for e in obj.fault_entries.all())

    def get_photo_urls(self, obj):
        from django.conf import settings
        request = self.context.get('request')
        if not obj.photos:
            return []
        base = request.build_absolute_uri(settings.MEDIA_URL) if request else settings.MEDIA_URL
        return [base + p for p in obj.photos]

    def get_zone_location_display(self, obj):
        return obj.zone_location.code if obj.zone_location else None

    def validate_zone_location_code(self, value):
        if value:
            from core.models import Zone
            zone = Zone.objects.filter(code=value).first()
            if not zone:
                raise serializers.ValidationError(f"Zone with code '{value}' not found")
            return zone
        return None

    def create(self, validated_data):
        fault_data = validated_data.pop('fault_entries', [])
        zone = validated_data.pop('zone_location_code', None)
        if zone:
            validated_data['zone_location'] = zone
        report = WorkReport.objects.create(**validated_data)
        for entry in fault_data:
            WorkReportFault.objects.create(work_report=report, **entry)
        return report

    def update(self, instance, validated_data):
        fault_data = validated_data.pop('fault_entries', None)
        zone = validated_data.pop('zone_location_code', None)
        if zone:
            validated_data['zone_location'] = zone
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if fault_data is not None:
            instance.fault_entries.all().delete()
            for entry in fault_data:
                WorkReportFault.objects.create(work_report=instance, **entry)
        return instance


class LocationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Patch.objects.filter(type=Patch.TYPE_LOCATION, active=True).order_by('order', 'code')
    serializer_class = LocationSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]


class WorkCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = WorkCategory.objects.filter(active=True).order_by('order', 'code')
    serializer_class = WorkCategorySerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]


class InfoSourceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = InfoSource.objects.filter(active=True).order_by('order', 'code')
    serializer_class = InfoSourceSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]


class FaultCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = FaultCategory.objects.filter(active=True).prefetch_related('sub_types').order_by('order', 'id')
    serializer_class = FaultCategorySerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]


class FaultSubTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = FaultSubType.objects.filter(active=True).select_related('category').order_by('category__order', 'order', 'id')
    serializer_class = FaultSubTypeSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]


class WorkReportViewSet(viewsets.ModelViewSet):
    serializer_class = WorkReportSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]

    def get_queryset(self):
        qs = WorkReport.objects.select_related(
            'worker', 'location', 'work_category', 'info_source'
        ).prefetch_related('fault_entries__fault_subtype__category').order_by('-date', '-id')

        from .role_utils import is_admin, get_worker_for_user
        if not is_admin(self.request.user):
            worker = get_worker_for_user(self.request.user)
            if worker:
                qs = qs.filter(worker=worker)
            else:
                qs = qs.none()

        # Filters
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        patch = self.request.query_params.get('patch') or self.request.query_params.get('location')
        work_category = self.request.query_params.get('work_category')
        worker_id = self.request.query_params.get('worker')
        zone_id = self.request.query_params.get('zone')
        is_difficult = self.request.query_params.get('is_difficult')

        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        if patch:
            qs = qs.filter(location_id=patch)
        if work_category:
            qs = qs.filter(work_category_id=work_category)
        if worker_id:
            qs = qs.filter(worker_id=worker_id)
        if zone_id:
            qs = qs.filter(zone_location_id=zone_id)
        if is_difficult is not None:
            qs = qs.filter(is_difficult=is_difficult.lower() in ('true', '1', 'yes'))

        return qs

    def perform_create(self, serializer):
        # If worker was explicitly passed, use it
        if 'worker' in serializer.validated_data:
            serializer.save()
            return
        from .role_utils import get_worker_for_user
        worker = get_worker_for_user(self.request.user)
        if worker is None:
            from .models import Worker
            django_user = getattr(self.request.user, 'user', self.request.user)
            worker, _ = Worker.objects.get_or_create(
                employee_id=f"USR-{django_user.id}",
                defaults={
                    'full_name': getattr(django_user, 'get_full_name', lambda: '')() or getattr(django_user, 'username', ''),
                },
            )
        serializer.save(worker=worker)

    @action(detail=True, methods=['post'], url_path='upload-photos')
    def upload_photos(self, request, pk=None):
        """Upload photos for a work report. Accepts multipart form with 'files' field."""
        report = self.get_object()
        files = request.FILES.getlist('files')

        if not files:
            return Response({'error': 'No files provided'}, status=status.HTTP_400_BAD_REQUEST)

        import os
        from django.conf import settings
        from datetime import datetime

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

        return Response({
            'photos': photo_paths,
            'photo_urls': [request.build_absolute_uri(settings.MEDIA_URL + p) for p in photo_paths],
        })

    @action(detail=True, methods=['delete'], url_path='remove-photo')
    def remove_photo(self, request, pk=None):
        """Remove a photo from a work report. Pass 'photo' query param with the path."""
        report = self.get_object()
        photo = request.query_params.get('photo')
        if not photo:
            return Response({'error': 'photo parameter required'}, status=status.HTTP_400_BAD_REQUEST)

        import os
        from django.conf import settings

        photo_paths = list(report.photos or [])
        if photo in photo_paths:
            photo_paths.remove(photo)
            report.photos = photo_paths
            report.save(update_fields=['photos'])
            # Delete file from disk
            filepath = os.path.join(settings.MEDIA_ROOT, photo)
            if os.path.exists(filepath):
                os.remove(filepath)

        return Response({'photos': photo_paths})
# 需求周报系统 API
# ==========================================================================


class DemandCategorySerializer(serializers.ModelSerializer):
    """Serializer for DemandCategory."""

    category_type_display = serializers.CharField(source='get_category_type_display', read_only=True)

    class Meta:
        model = DemandCategory
        fields = ['id', 'name', 'code', 'category_type', 'category_type_display', 'order', 'active']
        read_only_fields = ['created_at', 'updated_at']


class DemandDepartmentSerializer(serializers.ModelSerializer):
    """Serializer for DemandDepartment."""

    class Meta:
        model = DemandDepartment
        fields = ['id', 'name', 'code', 'order', 'active']
        read_only_fields = ['created_at']


class DemandRecordSerializer(serializers.ModelSerializer):
    """Serializer for DemandRecord with full context."""

    # Related fields
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_type = serializers.CharField(source='category.category_type', read_only=True)
    zone_name = serializers.CharField(source='zone.name', read_only=True)
    zone_code = serializers.CharField(source='zone.code', read_only=True)
    demand_department_name = serializers.CharField(source='demand_department.name', read_only=True)
    submitter_name = serializers.SerializerMethodField()
    approver_name = serializers.SerializerMethodField()

    # Display fields
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    time_display = serializers.SerializerMethodField()
    duration_hours = serializers.SerializerMethodField()

    class Meta:
        model = DemandRecord
        fields = [
            'id', 'date', 'content', 'original_text',
            'zone', 'zone_name', 'zone_code', 'zone_text',
            'is_global_event',
            'category', 'category_name', 'category_type', 'category_text',
            'start_time', 'end_time', 'crosses_midnight', 'time_parsed',
            'time_display', 'duration_hours',
            'demand_department', 'demand_department_name', 'demand_department_text', 'demand_contact',
            'status', 'status_display',
            'submitter', 'submitter_name',
            'approver', 'approver_name', 'processed_at', 'status_notes',
            'work_order',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at', 'submitter', 'approver', 'processed_at']

    def get_submitter_name(self, obj):
        if obj.submitter:
            return obj.submitter.full_name if hasattr(obj.submitter, 'full_name') else str(obj.submitter)
        return None

    def get_approver_name(self, obj):
        if obj.approver:
            return obj.approver.full_name if hasattr(obj.approver, 'full_name') else str(obj.approver)
        return None

    def get_time_display(self, obj):
        if obj.start_time and obj.end_time:
            return f"{obj.start_time.strftime('%H:%M')} - {obj.end_time.strftime('%H:%M')}"
        return None

    def get_duration_hours(self, obj):
        if obj.start_time and obj.end_time:
            start_minutes = obj.start_time.hour * 60 + obj.start_time.minute
            end_minutes = obj.end_time.hour * 60 + obj.end_time.minute
            if obj.crosses_midnight:
                end_minutes += 24 * 60
            duration = (end_minutes - start_minutes) / 60
            return round(duration, 1)
        return None


class DemandCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for DemandCategory - read-only for all authenticated users."""

    queryset = DemandCategory.objects.filter(active=True).order_by('order', 'code')
    serializer_class = DemandCategorySerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]


class DemandDepartmentViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for DemandDepartment - read-only for all authenticated users."""

    queryset = DemandDepartment.objects.filter(active=True).order_by('order', 'code')
    serializer_class = DemandDepartmentSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]


class DemandRecordViewSet(viewsets.ModelViewSet):
    """
    ViewSet for DemandRecord with role-based access control.

    Permissions:
    - Admin/Manager: Full CRUD, view all, approve/reject
    - Dept User: Create demands, view own department's demands
    - Field Worker: View assigned demands (via work_order), update status
    """

    queryset = DemandRecord.objects.select_related(
        'zone', 'category', 'demand_department', 'submitter', 'approver'
    ).order_by('-date', '-id')
    serializer_class = DemandRecordSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]

    def get_queryset(self):
        """Filter queryset based on user role."""
        qs = super().get_queryset()
        user = self.request.user

        # Check admin status
        from .role_utils import is_admin as check_admin, is_dept_user as check_dept_user, get_worker_for_user
        is_admin_user = check_admin(user)

        # Admin/Manager: see all with filters
        if is_admin_user:
            date_from = self.request.query_params.get('date_from')
            date_to = self.request.query_params.get('date_to')
            zone_id = self.request.query_params.get('zone')
            category_id = self.request.query_params.get('category')
            department_id = self.request.query_params.get('department')
            status_val = self.request.query_params.get('status')
            is_global = self.request.query_params.get('is_global')

            if date_from:
                qs = qs.filter(date__gte=date_from)
            if date_to:
                qs = qs.filter(date__lte=date_to)
            if zone_id:
                qs = qs.filter(zone_id=zone_id)
            if category_id:
                qs = qs.filter(category_id=category_id)
            if department_id:
                qs = qs.filter(demand_department_id=department_id)
            if status_val:
                qs = qs.filter(status=status_val)
            if is_global:
                qs = qs.filter(is_global_event=is_global.lower() in ('true', '1', 'yes'))

            return qs

        # Dept User: see demands from own department + can create
        from .role_utils import get_django_user
        if isinstance(user, DepartmentUserProfile):
            dept_profile = user
        else:
            django_user = get_django_user(user)
            if django_user:
                try:
                    dept_profile = DepartmentUserProfile.objects.get(user=django_user, active=True)
                except DepartmentUserProfile.DoesNotExist:
                    dept_profile = None
            else:
                dept_profile = None

        if dept_profile:
            # Try to match department code to DemandDepartment
            dept_code = dept_profile.department
            demand_dept = DemandDepartment.objects.filter(code=dept_code).first()
            if demand_dept:
                return qs.filter(demand_department=demand_dept)
            return qs.filter(demand_department_text__icontains=dept_profile.get_department_display_name())

        # Field Worker: can view all demands (read-only)
        worker = get_worker_for_user(user)
        if worker:
            return qs

        return DemandRecord.objects.none()

    def perform_create(self, serializer):
        """Auto-set submitter for dept users."""
        user = self.request.user

        # Try to get department profile
        try:
            dept_profile = DepartmentUserProfile.objects.get(user=user, active=True)
            dept_code = dept_profile.department
            demand_dept = DemandDepartment.objects.filter(code=dept_code).first()

            serializer.save(
                submitter=dept_profile,
                demand_department=demand_dept,
                demand_department_text=dept_profile.get_department_display_name(),
                demand_contact=dept_profile.full_name,
            )
            return
        except DepartmentUserProfile.DoesNotExist:
            pass

        # Admin can also create
        try:
            manager = ManagerProfile.objects.get(user=user, active=True)
            serializer.save(submitter=manager)
            return
        except ManagerProfile.DoesNotExist:
            pass

        serializer.save()

    def perform_update(self, serializer):
        """Handle approval/rejection by admin."""
        user = self.request.user

        # Check if user is admin
        from .role_utils import is_admin as check_admin
        is_admin_user = check_admin(user)

        if is_admin_user:
            new_status = serializer.validated_data.get('status')

            if new_status in ['approved', 'rejected', 'in_progress', 'completed']:
                # Try to get approver - ManagerProfile first, then Worker, then User
                from .role_utils import get_manager_profile, get_worker_for_user
                approver = get_manager_profile(user) or get_worker_for_user(user)

                if approver:
                    serializer.save(
                        approver=approver,
                        processed_at=timezone.now()
                    )
                    return

        serializer.save()


@api_view(['GET'])
@permission_classes([IsAuthenticatedByTokenOrSession])
@authentication_classes([TokenAuthentication, authentication.SessionAuthentication])
def demand_stats(request):
    """
    Statistics API for DemandRecord.

    Query params:
    - start_date: YYYY-MM-DD
    - end_date: YYYY-MM-DD
    - group_by: day|week|month|year
    - dimension: zone|category|department|status

    Returns aggregated statistics for reports.
    """
    from django.db.models import Count
    from django.db.models.functions import TruncDay, TruncWeek, TruncMonth, TruncYear
    from collections import defaultdict
    from datetime import datetime

    user = request.user

    # Check admin status
    from .role_utils import is_admin as check_admin
    is_admin_user = check_admin(user)

    # Only admin can access stats
    if not is_admin_user:
        return Response({'error': '权限不足'}, status=403)

    start_date = request.query_params.get('start_date')
    end_date = request.query_params.get('end_date')
    group_by = request.query_params.get('group_by', 'day')
    dimension = request.query_params.get('dimension', 'zone')

    # Parse dates
    if not start_date:
        start_date = date.today() - timedelta(days=30)
    else:
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()

    if not end_date:
        end_date = date.today()
    else:
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

    # Base queryset
    qs = DemandRecord.objects.filter(date__gte=start_date, date__lte=end_date)

    # Truncation function
    trunc_map = {
        'day': TruncDay('date'),
        'week': TruncWeek('date'),
        'month': TruncMonth('date'),
        'year': TruncYear('date'),
    }
    trunc_func = trunc_map.get(group_by, TruncDay('date'))

    # Annotate with time period
    qs = qs.annotate(period=trunc_func)

    results = []

    if dimension == 'zone':
        zone_stats = qs.values('zone', 'zone_text', 'period').annotate(
            count=Count('id'),
        ).order_by('period', 'zone_text')

        period_data = defaultdict(list)
        for stat in zone_stats:
            period_key = stat['period'].strftime('%Y-%m-%d') if stat['period'] else 'Unknown'
            period_data[period_key].append({
                'zone_id': stat['zone'],
                'zone_name': stat['zone_text'] or '全局事件',
                'count': stat['count'],
            })

        results = [{'period': k, 'items': v} for k, v in sorted(period_data.items())]

    elif dimension == 'category':
        cat_stats = qs.values('category', 'category_text', 'period').annotate(
            count=Count('id'),
        ).order_by('period', 'category_text')

        period_data = defaultdict(list)
        for stat in cat_stats:
            period_key = stat['period'].strftime('%Y-%m-%d') if stat['period'] else 'Unknown'
            period_data[period_key].append({
                'category_id': stat['category'],
                'category_name': stat['category_text'] or '未知',
                'count': stat['count'],
            })

        results = [{'period': k, 'items': v} for k, v in sorted(period_data.items())]

    elif dimension == 'department':
        dept_stats = qs.values('demand_department', 'demand_department_text', 'period').annotate(
            count=Count('id'),
        ).order_by('period', 'demand_department_text')

        period_data = defaultdict(list)
        for stat in dept_stats:
            period_key = stat['period'].strftime('%Y-%m-%d') if stat['period'] else 'Unknown'
            period_data[period_key].append({
                'department_id': stat['demand_department'],
                'department_name': stat['demand_department_text'] or '未知',
                'count': stat['count'],
            })

        results = [{'period': k, 'items': v} for k, v in sorted(period_data.items())]

    elif dimension == 'status':
        status_stats = qs.values('status', 'period').annotate(
            count=Count('id'),
        ).order_by('period', 'status')

        period_data = defaultdict(list)
        for stat in status_stats:
            period_key = stat['period'].strftime('%Y-%m-%d') if stat['period'] else 'Unknown'
            status_display = dict(DemandRecord.STATUS_CHOICES).get(stat['status'], stat['status'])
            period_data[period_key].append({
                'status': stat['status'],
                'status_display': status_display,
                'count': stat['count'],
            })

        results = [{'period': k, 'items': v} for k, v in sorted(period_data.items())]

    # Summary stats
    total_count = qs.count()
    summary = {
        'total_records': total_count,
        'by_status': dict(qs.values('status').annotate(count=Count('id')).values_list('status', 'count')),
        'by_category': dict(qs.values('category_text').annotate(count=Count('id')).values_list('category_text', 'count')),
        'by_department': dict(qs.values('demand_department_text').annotate(count=Count('id')).values_list('demand_department_text', 'count')),
        'time_parsed_rate': qs.filter(time_parsed=True).count() * 100 / total_count if total_count > 0 else 0,
        'zone_matched_rate': qs.filter(zone__isnull=False).count() * 100 / total_count if total_count > 0 else 0,
    }

    return Response({
        'start_date': str(start_date),
        'end_date': str(end_date),
        'group_by': group_by,
        'dimension': dimension,
        'results': results,
        'summary': summary,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticatedByTokenOrSession])
@authentication_classes([TokenAuthentication, authentication.SessionAuthentication])
def demand_calendar(request):
    """
    Calendar view API for DemandRecord.

    Returns demands grouped by date for calendar display.
    """
    from collections import defaultdict

    user = request.user

    # Check admin status
    from .role_utils import is_admin as check_admin
    is_admin_user = check_admin(user)

    year = request.query_params.get('year')
    month = request.query_params.get('month')

    if not year or not month:
        today = date.today()
        year = today.year
        month = today.month

    # Base queryset
    qs = DemandRecord.objects.filter(date__year=int(year), date__month=int(month))

    # Role-based filter
    if not is_admin_user:
        if isinstance(user, DepartmentUserProfile):
            dept_profile = user
            dept_code = dept_profile.department
            demand_dept = DemandDepartment.objects.filter(code=dept_code).first()
            if demand_dept:
                qs = qs.filter(demand_department=demand_dept)
            else:
                qs = qs.filter(demand_department_text__icontains=dept_profile.get_department_display_name())
        else:
            try:
                dept_profile = DepartmentUserProfile.objects.get(user=user, active=True)
                dept_code = dept_profile.department
                demand_dept = DemandDepartment.objects.filter(code=dept_code).first()
                if demand_dept:
                    qs = qs.filter(demand_department=demand_dept)
                else:
                    qs = qs.filter(demand_department_text__icontains=dept_profile.get_department_display_name())
            except DepartmentUserProfile.DoesNotExist:
                qs = DemandRecord.objects.none()

    # Group by date
    calendar_data = defaultdict(list)

    for record in qs.select_related('zone', 'category'):
        date_key = str(record.date)
        calendar_data[date_key].append({
            'id': record.id,
            'zone_name': record.zone_text or '全局',
            'category_name': record.category_text or '未分类',
            'content': record.content[:50] + '...' if len(record.content) > 50 else record.content,
            'time_display': f"{record.start_time.strftime('%H:%M')}-{record.end_time.strftime('%H:%M')}" if record.start_time else None,
            'status': record.status,
            'status_display': record.get_status_display(),
            'is_global': record.is_global_event,
        })

    return Response({
        'year': year,
        'month': month,
        'calendar': dict(calendar_data),
        'total': qs.count(),
    })
