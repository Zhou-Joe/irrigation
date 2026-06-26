from rest_framework import serializers, viewsets, permissions, status, authentication
from rest_framework.decorators import api_view, permission_classes, authentication_classes, action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.contrib.auth import authenticate, login
from django.utils import timezone
from django.db import models
from datetime import timedelta, date
from .models import Zone, Plant, Worker, WeatherData, WaterRequest, ManagerProfile, DepartmentUserProfile, EquipmentCatalog, ZoneEquipment, Pipeline, Patch, Region, WorkReport
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
    active_boundary_points = serializers.SerializerMethodField()
    # Patch info for grouping
    patch_id = serializers.SerializerMethodField()
    patch_name = serializers.SerializerMethodField()
    patch_code = serializers.SerializerMethodField()
    # Region info (via patch)
    region_id = serializers.SerializerMethodField()
    region_name = serializers.SerializerMethodField()

    class Meta:
        model = Zone
        fields = [
            'id', 'name', 'code', 'description', 'boundary_points',
            'dxf_boundary_points', 'dxf_boundary_source', 'boundary_source',
            'boundary_color', 'status', 'status_display',
            'pending_requests', 'center', 'active_boundary_points',
            'priority',
            'current_status', 'sprinkler_type', 'irrigation_intensity',
            'solenoid_valve_size', 'landscape_coefficient', 'plant_type',
            'irrigation_foreman', 'greenery_zone', 'greenery_foreman',
            'pest_control_zone', 'pest_control_foreman',
            'terrain_feature', 'plant_feature', 'soil_moisture',
            'equipment_maintenance_notes', 'irrigation_management_notes',
            'patch_id', 'patch_name', 'patch_code',
            'region_id', 'region_name',
            'area_sqm', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_patch_id(self, obj):
        return obj.patch.id if obj.patch else None

    def get_patch_name(self, obj):
        return obj.patch.name if obj.patch else None

    def get_patch_code(self, obj):
        return obj.patch.code if obj.patch else None

    def get_region_id(self, obj):
        if obj.patch and obj.patch.region:
            return obj.patch.region.id
        return None

    def get_region_name(self, obj):
        if obj.patch and obj.patch.region:
            return obj.patch.region.name
        return None

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
            zones=obj,
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
        return get_zone_center(obj.active_boundary_points)

    def get_active_boundary_points(self, obj):
        """返回当前生效的边界数据。"""
        return obj.active_boundary_points


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


# (removed: WorkOrderSerializer)
# (removed: EventSerializer)
# (removed: WorkLogSerializer)
# (removed: MaintenanceRequestSerializer)
# (removed: ProjectSupportRequestSerializer)
class WaterRequestSerializer(serializers.ModelSerializer):
    """Serializer for WaterRequest model."""

    zone_names = serializers.SerializerMethodField()
    submitter_name = serializers.CharField(source='submitter.full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    user_type_display = serializers.CharField(source='get_user_type_display', read_only=True)
    request_type_display = serializers.CharField(source='get_request_type_display', read_only=True)
    approver_name = serializers.CharField(source='approver.full_name', read_only=True)

    def get_zone_names(self, obj):
        return ', '.join(z.name for z in obj.all_zones)

    class Meta:
        model = WaterRequest
        fields = [
            'id', 'zones', 'zone_names', 'submitter', 'submitter_name',
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

        return Response({
            'id': zone.id,
            'name': zone.name,
            'code': zone.code,
            'description': zone.description or '',
            'status': zone.get_today_status(),
            'status_display': zone.get_status_display(),
            'boundary_color': zone.boundary_color,
            'priority': zone.priority,
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
            'plants': PlantSerializer(plants, many=True).data,
            'equipment': ZoneEquipmentSerializer(equipment, many=True).data,
            'plant_count': plants.count(),
            'equipment_count': equipment.count(),
            'work_report_count': work_report_count,
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


# (removed: WorkOrderViewSet)
# (removed: EventViewSet)
# (removed: WorkLogViewSet)
# (removed: MaintenanceRequestViewSet)
# (removed: ProjectSupportRequestViewSet)
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

    # Water requests - all roles can see (dept users see all, others filtered)
    water_qs = WaterRequest.objects.all()
    if role == 'field_worker' and profile:
        water_qs = water_qs.filter(submitter=profile)

    for req in water_qs:
        results.append({
            'id': req.id,
            'type': '浇水协调需求',
            'type_code': 'water',
            'zone': ', '.join(z.name for z in req.all_zones),
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

    # Try exact coordinate match first, fallback to any today's data
    queryset = WeatherData.objects.filter(date=today)
    if lat and lon:
        queryset = queryset.filter(
            latitude=round(float(lat), 5),
            longitude=round(float(lon), 5)
        )

    weather_record = queryset.first()

    # Fallback: if no exact coordinate match, get any record for today
    if not weather_record:
        weather_record = WeatherData.objects.filter(date=today).first()

    if not weather_record:
        return Response({'current_hour': current_hour, 'date': str(today), 'count': 0, 'data': []})

    # Filter hourly data: 1 hour before to 4 hours after
    hourly_data = weather_record.hourly_data or []
    filtered_data = []

    # For late hours (>= 22), also check tomorrow's data for hours 24-27
    tomorrow_record = None
    if current_hour >= 22:
        tomorrow = today + timedelta(days=1)
        tomorrow_record = WeatherData.objects.filter(date=tomorrow).first()

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

    # Add tomorrow's hours 0-3 as hours 24-27 for late night
    if tomorrow_record and current_hour >= 22:
        tomorrow_hourly = tomorrow_record.hourly_data or []
        for h in tomorrow_hourly:
            hour = h.get('hour')
            if hour is not None and hour <= 3:
                # Represent as hour 24, 25, 26, 27
                adjusted_hour = 24 + hour
                if current_hour - 1 <= adjusted_hour <= current_hour + 4:
                    filtered_data.append({
                        'hour': adjusted_hour,
                        'temperature': h.get('temp'),
                        'humidity': h.get('humidity'),
                        'precipitation': h.get('precip'),
                        'wind_speed': h.get('wind'),
                        'weather_code': h.get('code'),
                        'weather_description': tomorrow_record.get_weather_description(h.get('code')),
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


# (removed: WorkCategorySerializer)
# (removed: InfoSourceSerializer)
# (removed: FaultSubTypeSerializer)
# (removed: FaultCategorySerializer)
# (removed: WorkReportFaultSerializer)
class WorkReportSerializer(serializers.ModelSerializer):
    worker_name = serializers.CharField(source='worker.full_name', read_only=True)
    patch = serializers.IntegerField(write_only=True, required=True, source='location_id')
    location = serializers.IntegerField(source='location_id', read_only=True, allow_null=True)
    location_name = serializers.CharField(source='location.name', read_only=True, default=None)
    zone_location_code = serializers.CharField(write_only=True, required=False, allow_null=True, allow_blank=True)
    zone_location_display = serializers.SerializerMethodField()
    photo_urls = serializers.SerializerMethodField()

    class Meta:
        model = WorkReport
        fields = [
            'id', 'date', 'weather', 'worker', 'worker_name',
            'patch', 'location', 'location_name',
            'zone_location', 'zone_location_code', 'zone_location_display',
            'remark',
            'is_difficult', 'is_difficult_resolved',
            'photos', 'photo_urls',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']
        extra_kwargs = {
            'zone_location': {'required': False, 'allow_null': True},
            'worker': {'required': False},
        }

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
        zone = validated_data.pop('zone_location_code', None)
        if zone:
            validated_data['zone_location'] = zone
        return WorkReport.objects.create(**validated_data)

    def update(self, instance, validated_data):
        zone = validated_data.pop('zone_location_code', None)
        if zone:
            validated_data['zone_location'] = zone
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class PatchSerializer(serializers.ModelSerializer):
    region_id = serializers.SerializerMethodField()
    region_name = serializers.SerializerMethodField()

    class Meta:
        model = Patch
        fields = ['id', 'name', 'code', 'order', 'active', 'region_id', 'region_name']

    def get_region_id(self, obj):
        return obj.region.id if obj.region else None

    def get_region_name(self, obj):
        return obj.region.name if obj.region else None


class PatchViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Patch.objects.filter(active=True).order_by('order', 'code')
    serializer_class = PatchSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]


class RegionSerializer(serializers.ModelSerializer):
    patch_count = serializers.SerializerMethodField()

    class Meta:
        model = Region
        fields = ['id', 'name', 'order', 'active', 'patch_count']

    def get_patch_count(self, obj):
        return obj.patches.filter(active=True).count()


class RegionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Region.objects.filter(active=True).order_by('order', 'name')
    serializer_class = RegionSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]


class LocationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Patch.objects.filter(active=True).order_by('order', 'code')
    serializer_class = LocationSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]


# (removed: WorkCategoryViewSet)
# (removed: InfoSourceViewSet)
# (removed: FaultCategoryViewSet)
# (removed: FaultSubTypeViewSet)
class WorkReportViewSet(viewsets.ModelViewSet):
    serializer_class = WorkReportSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAuthenticatedByTokenOrSession]

    def get_queryset(self):
        qs = WorkReport.objects.select_related(
            'worker', 'location', 'work_category', 'info_source'
        ).prefetch_related('fault_entries__fault_subtype__category').order_by('-date', '-id')

        from .role_utils import is_admin, get_worker_for_user, is_field_worker
        # Both 灌溉一线 (field workers) and managers/admins see ALL workorders.
        if not is_admin(self.request.user) and not is_field_worker(self.request.user):
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


# (removed: DemandCategorySerializer)
# (removed: DemandDepartmentSerializer)
# (removed: DemandRecordSerializer)
# (removed: DemandCategoryViewSet)
# (removed: DemandDepartmentViewSet)
# (removed: DemandRecordViewSet)
# (removed func: demand_stats)
# (removed func: demand_calendar)