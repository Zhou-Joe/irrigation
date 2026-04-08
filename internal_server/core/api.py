from rest_framework import serializers, viewsets, permissions, status, authentication
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.contrib.auth import authenticate, login
from django.utils import timezone
from datetime import timedelta, date
from .models import Zone, Plant, Worker, WorkOrder, Event, WorkLog, WeatherData, MaintenanceRequest, ProjectSupportRequest, WaterRequest, ManagerProfile, DepartmentUserProfile
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
        # Use user's token or generate one
        token = manager.api_token if hasattr(manager, 'api_token') else str(manager.id)
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
            token = str(dept_user.id)
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

    class Meta:
        model = Zone
        fields = [
            'id', 'name', 'code', 'description', 'boundary_points',
            'boundary_color', 'status', 'status_display',
            'pending_requests', 'center',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

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
        fields = ['id', 'zone', 'name', 'scientific_name', 'quantity', 'notes']


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


class PlantViewSet(viewsets.ModelViewSet):
    queryset = Plant.objects.all()
    serializer_class = PlantSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAdminOrReadOnly]


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
        user = self.request.user
        is_admin = user.is_superuser or user.is_staff
        if not is_admin:
            try:
                ManagerProfile.objects.get(user=user, active=True)
                is_admin = True
            except ManagerProfile.DoesNotExist:
                pass

        if is_admin:
            return WorkLog.objects.all()

        try:
            worker = Worker.objects.get(user=user, active=True)
            return WorkLog.objects.filter(worker=worker)
        except Worker.DoesNotExist:
            return WorkLog.objects.none()


class MaintenanceRequestViewSet(viewsets.ModelViewSet):
    """ViewSet for MaintenanceRequest - dept users cannot access."""
    queryset = MaintenanceRequest.objects.all().order_by('-created_at')
    serializer_class = MaintenanceRequestSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        is_admin = user.is_superuser or user.is_staff
        if not is_admin:
            try:
                ManagerProfile.objects.get(user=user, active=True)
                is_admin = True
            except ManagerProfile.DoesNotExist:
                pass

        # Check if dept user - deny access
        try:
            DepartmentUserProfile.objects.get(user=user, active=True)
            return MaintenanceRequest.objects.none()
        except DepartmentUserProfile.DoesNotExist:
            pass

        if is_admin:
            return MaintenanceRequest.objects.all().order_by('-created_at')

        try:
            worker = Worker.objects.get(user=user, active=True)
            return MaintenanceRequest.objects.filter(submitter=worker).order_by('-created_at')
        except Worker.DoesNotExist:
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
        user = self.request.user
        is_admin = user.is_superuser or user.is_staff
        if not is_admin:
            try:
                ManagerProfile.objects.get(user=user, active=True)
                is_admin = True
            except ManagerProfile.DoesNotExist:
                pass

        # Check if dept user - deny access
        try:
            DepartmentUserProfile.objects.get(user=user, active=True)
            return ProjectSupportRequest.objects.none()
        except DepartmentUserProfile.DoesNotExist:
            pass

        if is_admin:
            return ProjectSupportRequest.objects.all().order_by('-created_at')

        try:
            worker = Worker.objects.get(user=user, active=True)
            return ProjectSupportRequest.objects.filter(submitter=worker).order_by('-created_at')
        except Worker.DoesNotExist:
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
        user = self.request.user

        # Check if dept user - sees all water requests
        try:
            DepartmentUserProfile.objects.get(user=user, active=True)
            return WaterRequest.objects.all().order_by('-created_at')
        except DepartmentUserProfile.DoesNotExist:
            pass

        is_admin = user.is_superuser or user.is_staff
        if not is_admin:
            try:
                ManagerProfile.objects.get(user=user, active=True)
                is_admin = True
            except ManagerProfile.DoesNotExist:
                pass

        if is_admin:
            return WaterRequest.objects.all().order_by('-created_at')

        try:
            worker = Worker.objects.get(user=user, active=True)
            return WaterRequest.objects.filter(submitter=worker).order_by('-created_at')
        except Worker.DoesNotExist:
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

    # Determine user role
    if user.is_superuser or user.is_staff:
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

    now = timezone.now()
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
