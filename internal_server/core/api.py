from rest_framework import serializers, viewsets, permissions, status, authentication
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.contrib.auth import authenticate, login
from django.utils import timezone
from datetime import timedelta, date
from .models import Zone, Plant, Worker, WorkOrder, Event, WorkLog, WeatherData, MaintenanceRequest, ProjectSupportRequest, WaterRequest
from .authentication import TokenAuthentication


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
    Authenticate a worker by employee_id and phone number.
    Returns the worker's API token on success.
    """
    employee_id = request.data.get('employee_id')
    phone = request.data.get('phone')

    if not employee_id or not phone:
        return Response(
            {'error': 'employee_id and phone are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        worker = Worker.objects.get(employee_id=employee_id, phone=phone, active=True)
    except Worker.DoesNotExist:
        return Response(
            {'error': 'Invalid credentials or inactive worker'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    return Response({
        'token': str(worker.api_token),
        'worker': {
            'id': worker.id,
            'employee_id': worker.employee_id,
            'full_name': worker.full_name,
            'phone': worker.phone,
        }
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
    """ViewSet for Zone CRUD operations."""

    queryset = Zone.objects.all()
    serializer_class = ZoneSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]


class PlantViewSet(viewsets.ModelViewSet):
    """ViewSet for Plant CRUD operations."""

    queryset = Plant.objects.all()
    serializer_class = PlantSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]


class WorkerViewSet(viewsets.ModelViewSet):
    """ViewSet for Worker CRUD operations."""

    queryset = Worker.objects.all()
    serializer_class = WorkerSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]


class WorkOrderViewSet(viewsets.ModelViewSet):
    """ViewSet for WorkOrder CRUD operations."""

    queryset = WorkOrder.objects.all()
    serializer_class = WorkOrderSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]


class EventViewSet(viewsets.ModelViewSet):
    """ViewSet for Event CRUD operations."""

    queryset = Event.objects.all()
    serializer_class = EventSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]


class WorkLogViewSet(viewsets.ModelViewSet):
    """ViewSet for WorkLog CRUD operations."""

    queryset = WorkLog.objects.all()
    serializer_class = WorkLogSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]


class MaintenanceRequestViewSet(viewsets.ModelViewSet):
    """ViewSet for MaintenanceRequest CRUD operations."""

    queryset = MaintenanceRequest.objects.all().order_by('-created_at')
    serializer_class = MaintenanceRequestSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]

    def perform_create(self, serializer):
        # request.user is Worker when using token auth, or User when using session auth
        if isinstance(self.request.user, Worker):
            serializer.save(submitter=self.request.user)
        else:
            serializer.save(submitter=self.request.user.worker_profile)


class ProjectSupportRequestViewSet(viewsets.ModelViewSet):
    """ViewSet for ProjectSupportRequest CRUD operations."""

    queryset = ProjectSupportRequest.objects.all().order_by('-created_at')
    serializer_class = ProjectSupportRequestSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]

    def perform_create(self, serializer):
        if isinstance(self.request.user, Worker):
            serializer.save(submitter=self.request.user)
        else:
            serializer.save(submitter=self.request.user.worker_profile)


class WaterRequestViewSet(viewsets.ModelViewSet):
    """ViewSet for WaterRequest CRUD operations."""

    queryset = WaterRequest.objects.all().order_by('-created_at')
    serializer_class = WaterRequestSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]

    def perform_create(self, serializer):
        if isinstance(self.request.user, Worker):
            serializer.save(submitter=self.request.user)
        else:
            serializer.save(submitter=self.request.user.worker_profile)


@api_view(['GET'])
@permission_classes([AllowAny])
@authentication_classes([TokenAuthentication, authentication.SessionAuthentication])
def get_all_requests(request):
    """Get all requests combined for the status list."""
    # request.user is Worker when using token auth, or User when using session auth
    if isinstance(request.user, Worker):
        worker = request.user
    elif hasattr(request.user, 'worker_profile'):
        worker = request.user.worker_profile
    else:
        worker = None

    # For non-admin users, only show their own requests
    # For admin users, show all requests
    is_admin = worker and worker.employee_id.startswith('ADM')

    results = []

    # Maintenance requests
    maintenance_qs = MaintenanceRequest.objects.all()
    if not is_admin and worker:
        maintenance_qs = maintenance_qs.filter(submitter=worker)

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

    # Project support requests
    project_qs = ProjectSupportRequest.objects.all()
    if not is_admin and worker:
        project_qs = project_qs.filter(submitter=worker)

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

    # Water requests
    water_qs = WaterRequest.objects.all()
    if not is_admin and worker:
        water_qs = water_qs.filter(submitter=worker)

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
