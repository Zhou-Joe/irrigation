import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date


# Role constants
ROLE_SUPER_ADMIN = 'super_admin'
ROLE_MANAGER = 'manager'
ROLE_FIELD_WORKER = 'field_worker'
ROLE_DEPT_USER = 'dept_user'

ROLE_CHOICES = [
    (ROLE_SUPER_ADMIN, '超级管理员'),
    (ROLE_MANAGER, '管理员'),
    (ROLE_FIELD_WORKER, '灌溉一线'),
    (ROLE_DEPT_USER, '部门用户'),
]


class Region(models.Model):
    """大区 — highest-level geographic grouping above 片区."""

    name = models.CharField('名称', max_length=255, unique=True)
    description = models.TextField('描述', blank=True)
    order = models.PositiveIntegerField('排序', default=0)
    active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = '大区'
        verbose_name_plural = '大区'

    def __str__(self):
        return self.name


class Patch(models.Model):
    """Unified location/area hierarchy. 片区, 灌溉站, 位置/CCU, 需求区域 all live here."""

    region = models.ForeignKey('Region', on_delete=models.SET_NULL, null=True, blank=True, related_name='patches', verbose_name='所属大区')
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children', verbose_name='上级')
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField('描述', blank=True)
    order = models.PositiveIntegerField('排序', default=0)
    active = models.BooleanField('启用', default=True)

    # MaxicomSite fields
    mdb_index = models.IntegerField('Maxicom索引', null=True, blank=True, help_text='Original IndexNumber from MDB')
    site_number = models.IntegerField('站点编号', null=True, blank=True)
    time_zone = models.CharField(max_length=50, blank=True, default='China')
    water_pricing = models.FloatField(null=True, blank=True)
    ccu_version = models.CharField(max_length=50, blank=True)
    et_current = models.FloatField(null=True, blank=True, help_text='Current ET value')
    et_default = models.FloatField(null=True, blank=True)
    et_minimum = models.FloatField(null=True, blank=True)
    et_maximum = models.FloatField(null=True, blank=True)
    crop_coefficient = models.FloatField(null=True, blank=True)
    rain_shutdown = models.BooleanField(default=False)
    telephone = models.CharField(max_length=255, blank=True, help_text='CCU contact address')
    date_open = models.CharField(max_length=20, blank=True)
    date_close = models.CharField(max_length=20, blank=True)

    # MaxicomStation fields
    controller_number = models.IntegerField('所属控制器编号', null=True, blank=True,
        help_text='StationControllerNumber from MDB — IndexNumber of the satellite controller this valve belongs to')
    controller_channel = models.IntegerField('控制器通道', null=True, blank=True)
    precip_rate = models.FloatField(null=True, blank=True, help_text='Precipitation rate')
    flow_rate = models.FloatField(null=True, blank=True, help_text='Flow rate')
    microclimate_factor = models.IntegerField(null=True, blank=True)
    cycle_time = models.IntegerField(null=True, blank=True, help_text='Cycle time in minutes')
    soak_time = models.IntegerField(null=True, blank=True, help_text='Soak time in minutes')
    lockout = models.BooleanField(default=False)
    flow_manager_priority = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '区域'
        verbose_name_plural = '区域'
        ordering = ['code']

    @property
    def zones(self):
        return Zone.objects.filter(patch=self)

    def __str__(self):
        return f"{self.name} ({self.code})"


class Land(models.Model):
    """所属Land — a coarse location grouping that is the parent of a Zone's 通用名称."""

    name = models.CharField('名称', max_length=100, unique=True)
    order = models.PositiveIntegerField('排序', default=0)
    active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Land'
        verbose_name_plural = 'Lands'

    def __str__(self):
        return self.name


class Zone(models.Model):
    """Represents a work zone with boundary points and status tracking."""

    # 状态由当天工单决定，不再存储在数据库
    STATUS_UNARRANGED = 'unarranged'  # 未安排（当天无工单）
    STATUS_IN_PROGRESS = 'in_progress'  # 处理中（工单已提交待审批）
    STATUS_COMPLETED = 'completed'  # 已完成（工单已批准）
    STATUS_CANCELED = 'canceled'  # 已取消（工单已拒绝）
    STATUS_DELAYED = 'delayed'  # 已延期（需补充信息）

    STATUS_CHOICES = [
        (STATUS_UNARRANGED, '未安排'),
        (STATUS_IN_PROGRESS, '处理中'),
        (STATUS_COMPLETED, '已完成'),
        (STATUS_CANCELED, '已取消'),
        (STATUS_DELAYED, '已延期'),
    ]

    PRIORITY_CRITICAL = 'critical'
    PRIORITY_HIGH = 'high'
    PRIORITY_MEDIUM = 'medium'
    PRIORITY_LOW = 'low'
    PRIORITY_ABOLISHED = 'abolished'

    PRIORITY_CHOICES = [
        (PRIORITY_CRITICAL, '超级重点'),
        (PRIORITY_HIGH, '重点'),
        (PRIORITY_MEDIUM, '一般'),
        (PRIORITY_LOW, '次要'),
        (PRIORITY_ABOLISHED, '废除'),
    ]

    patch = models.ForeignKey(Patch, on_delete=models.SET_NULL, null=True, blank=True, related_name='zones', verbose_name='所属片区')
    land = models.ForeignKey(Land, on_delete=models.SET_NULL, null=True, blank=True, related_name='zones', verbose_name='所属Land')
    satellite = models.ForeignKey('Satellite', on_delete=models.SET_NULL, null=True, blank=True, related_name='zones', verbose_name='所属SAT')
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    boundary_points = models.JSONField(default=list)
    boundary_color = models.CharField(max_length=7, default='#52B788', help_text='边界颜色 (十六进制)')
    dxf_boundary_points = models.JSONField(default=list, blank=True, help_text='DXF导入的边界')
    dxf_boundary_source = models.CharField(max_length=255, blank=True, default='', help_text='DXF来源文件名')
    boundary_source = models.CharField(
        max_length=10,
        choices=[('manual', '手动绘制'), ('dxf', 'DXF导入')],
        default='manual',
        help_text='当前生效的边界来源',
    )
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM, verbose_name='优先级')
    current_status = models.CharField(max_length=50, blank=True, default='', verbose_name='当前状态')
    sprinkler_type = models.CharField(max_length=100, blank=True, default='', verbose_name='灌水器类型')
    irrigation_intensity = models.FloatField(null=True, blank=True, verbose_name='灌溉强度(mm/h)')
    solenoid_valve_size = models.FloatField(null=True, blank=True, verbose_name='电磁阀尺寸')
    landscape_coefficient = models.FloatField(null=True, blank=True, verbose_name='景观系数')
    plant_type = models.CharField(max_length=100, blank=True, default='', verbose_name='植物类型')
    irrigation_foreman = models.CharField(max_length=100, blank=True, default='', verbose_name='灌溉领班')
    greenery_zone = models.CharField(max_length=100, blank=True, default='', verbose_name='绿化分区')
    greenery_foreman = models.CharField(max_length=100, blank=True, default='', verbose_name='绿化领班')
    pest_control_zone = models.CharField(max_length=100, blank=True, default='', verbose_name='植保分区')
    pest_control_foreman = models.CharField(max_length=100, blank=True, default='', verbose_name='植保领班')
    terrain_feature = models.CharField(max_length=200, blank=True, default='', verbose_name='地形特点')
    plant_feature = models.CharField(max_length=200, blank=True, default='', verbose_name='植物特点')
    soil_moisture = models.CharField(max_length=50, blank=True, default='', verbose_name='土壤湿度')
    equipment_maintenance_notes = models.TextField(blank=True, default='', verbose_name='灌溉设备维护记录')
    irrigation_management_notes = models.TextField(blank=True, default='', verbose_name='灌溉管理记录')
    remarks = models.TextField(blank=True, default='', verbose_name='备注')
    confirmed_remarks = models.TextField(blank=True, default='', verbose_name='备注确认')
    label_lat = models.FloatField(null=True, blank=True, help_text='Custom label latitude override')
    label_lng = models.FloatField(null=True, blank=True, help_text='Custom label longitude override')
    label_scale = models.FloatField(default=1.0, help_text='Label font size multiplier')
    label_angle = models.IntegerField(default=0, help_text='Label rotation in degrees')
    smooth_override = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Per-zone boundary smooth override (null=follow global, 0-3=custom)')
    ring_display_modes = models.JSONField(default=dict, blank=True, help_text='Per-ring display mode: {"0":"sublabel"}. Missing keys default to "line".')
    area_sqm = models.FloatField(null=True, blank=True, help_text='Calculated area in square meters')
    drawn_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='drawn_zones', verbose_name='绘制人')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def active_boundary_points(self):
        """Return the boundary points from whichever source is currently active."""
        if self.boundary_source == 'dxf' and self.dxf_boundary_points:
            return self.dxf_boundary_points
        return self.boundary_points

    def save(self, *args, **kwargs):
        self._recalc_area()
        super().save(*args, **kwargs)

    def _recalc_area(self):
        import math
        pts = self.active_boundary_points
        if not pts:
            self.area_sqm = None
            return

        def to_latlng(p):
            if isinstance(p, dict):
                return p.get('lat', p.get('latitude', 0)), p.get('lng', p.get('longitude', 0))
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                return p[0], p[1]
            return 0, 0

        def is_point(p):
            """Check if p is a single point (dict with lat/lng or [lat, lng])."""
            if isinstance(p, dict):
                return 'lat' in p or 'latitude' in p
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                return isinstance(p[0], (int, float))
            return False

        def calc_ring_area(ring):
            if len(ring) < 3:
                return 0
            flat, flng = to_latlng(ring[0])
            m_lat = 111320.0
            m_lng = 111320.0 * math.cos(math.radians(flat))
            area = 0.0
            for i in range(len(ring)):
                j = (i + 1) % len(ring)
                pi_lat, pi_lng = to_latlng(ring[i])
                qj_lat, qj_lng = to_latlng(ring[j])
                xi = (pi_lng - flng) * m_lng
                yi = (pi_lat - flat) * m_lat
                xj = (qj_lng - flng) * m_lng
                yj = (qj_lat - flat) * m_lat
                area += xi * yj - xj * yi
            return abs(area) / 2.0

        first = pts[0]
        # Detect nested multi-group format: [[[{lat,lng},...], [{lat,lng},...]], ...]
        # pts[0] is a group = [ring1, ring2, ...], pts[0][0] is a ring = [{lat,lng}, ...]
        # pts[0][0][0] is a point => flat multi-ring
        # pts[0][0] is an array of points => need to check one more level
        is_multi_group = False
        if isinstance(first, list) and len(first) > 0:
            inner = first[0]
            if isinstance(inner, list) and len(inner) > 0:
                innermost = inner[0]
                if isinstance(innermost, (list, dict)) and not is_point(innermost):
                    # inner[0] is an array of points → this is a nested multi-group
                    is_multi_group = True

        total = 0.0
        if is_multi_group:
            # Multi-group: [[outer1, hole1a, ...], [outer2, hole2a, ...]]
            for group in pts:
                for ring_idx, ring in enumerate(group):
                    ring_area = calc_ring_area(ring)
                    if ring_idx == 0:
                        total += ring_area      # outer
                    else:
                        total -= ring_area      # hole
        else:
            # Flat multi-ring or single-ring: [outer, hole1, hole2, ...]
            if isinstance(first, list) and len(first) > 0 and isinstance(first[0], (list, dict)):
                rings = pts
            elif isinstance(first, (dict, list)):
                rings = [pts]
            else:
                self.area_sqm = None
                return
            for ring_idx, ring in enumerate(rings):
                ring_area = calc_ring_area(ring)
                if ring_idx == 0:
                    total += ring_area
                else:
                    total -= ring_area
        self.area_sqm = total if total > 0 else None

    # ── Maxicom linkage ─────────────────────────────────────────────
    # Zone code "A-B-C" maps onto the Maxicom hardware tree:
    #   A (site/CCU number) -> Patch (mdb_index)            [via self.patch]
    #   B (satellite)       -> MaxicomController.link_channel
    #   C (work zone)       -> no Maxicom equivalent (a landscape area, not a valve)
    # So a zone resolves to one CCU Patch + one satellite controller under it.

    @property
    def maxicom_satellite_number(self):
        """The satellite number parsed from the zone code's 2nd segment (B in A-B-C)."""
        try:
            return int(self.code.split('-')[1])
        except (IndexError, ValueError):
            return None

    @property
    def maxicom_controller(self):
        """The Maxicom satellite controller this zone belongs to, or None.

        Matched by parsing the code's 2nd segment (the satellite number) and
        finding the MaxicomController under this zone's CCU Patch whose
        link_channel equals it. Returns None when the patch is unset, the code
        has no 2nd segment, or no controller matches.
        """
        sat = self.maxicom_satellite_number
        if sat is None or self.patch_id is None:
            return None
        return (
            MaxicomController.objects
            .filter(site_id=self.patch_id, link_channel=sat)
            .exclude(name__icontains='CCU')   # skip the "Site CCU" hub row (link_channel=0)
            .first()
        )

    @property
    def area_display(self):
        if not self.area_sqm:
            return '—'
        if self.area_sqm < 10000:
            return f'{self.area_sqm:,.0f} m²'
        return f'{self.area_sqm / 10000:.2f} 公顷 ({self.area_sqm:,.0f} m²)'

    @property
    def status(self):
        """Property to get today's status for template compatibility."""
        return self.get_today_status()

    def get_today_status(self, target_date=None):
        """Return the zone's own status field directly."""
        return self.STATUS_UNARRANGED

    def get_status_display(self, target_date=None):
        """获取状态的中文显示。"""
        status = self.get_today_status(target_date)
        for code, display in self.STATUS_CHOICES:
            if code == status:
                return display
        return '未安排'

    def __str__(self):
        return f"{self.name} ({self.code})"


class Landmark(models.Model):
    """地标 — general place name with drawn boundary for zone grouping."""

    name = models.CharField('名称', max_length=255, unique=True)
    boundary_points = models.JSONField('边界坐标', default=list)
    boundary_color = models.CharField('边界颜色', max_length=7, default='#E8590C')
    center = models.JSONField('中心点', null=True, blank=True)
    area_sqm = models.FloatField('面积(m²)', null=True, blank=True)
    order = models.PositiveIntegerField('排序', default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = '地标'
        verbose_name_plural = '地标'

    def __str__(self):
        return self.name


class ZoneLandmarkAssignment(models.Model):
    """Persisted zone↔landmark relationship (calculated on demand)."""

    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='landmark_assignments')
    landmark = models.ForeignKey(Landmark, on_delete=models.CASCADE, related_name='zone_assignments')
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('zone', 'landmark')

    def __str__(self):
        return f'{self.zone.code} → {self.landmark.name}'


class Pipeline(models.Model):
    """Represents a water pipeline (irrigation or flush)."""

    TYPE_IRRIGATION = 'irrigation'
    TYPE_FLUSH = 'flush'

    TYPE_CHOICES = [
        (TYPE_IRRIGATION, '灌溉水管'),
        (TYPE_FLUSH, '冲洗水管'),
    ]

    name = models.CharField(max_length=255, unique=True)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    pipeline_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_IRRIGATION,
        help_text='水管类型：灌溉水管或冲洗水管'
    )
    line_points = models.JSONField(
        default=list,
        help_text='Array of {lat, lng} points defining the pipeline polyline'
    )
    line_weight = models.IntegerField(default=3, help_text='Line thickness in pixels')
    zones = models.ManyToManyField(Zone, blank=True, related_name='pipelines')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def line_color(self):
        if self.pipeline_type == self.TYPE_IRRIGATION:
            return '#CC3333'
        return '#3366CC'

    def __str__(self):
        return f"{self.name} ({self.get_pipeline_type_display()})"


class Plant(models.Model):
    """Represents plants in a zone."""

    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='plants')
    name = models.CharField(max_length=255)
    scientific_name = models.CharField(max_length=255, blank=True)
    quantity = models.IntegerField(default=1)
    planting_date = models.DateField(null=True, blank=True, verbose_name='开始日期')
    end_date = models.DateField(null=True, blank=True, verbose_name='结束日期')
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = '植物'
        verbose_name_plural = '植物'

    def __str__(self):
        return f"{self.name} in {self.zone.name}"


class Worker(models.Model):
    """Represents a worker/employee."""

    DEPARTMENT_CHOICES = [
        ('FES', 'FES'),
        ('FAM', 'FAM'),
        ('ENT', 'ENT'),
        ('其他', '其他'),
    ]

    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='worker_profile')
    employee_id = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, blank=True)
    department = models.CharField(max_length=20, choices=DEPARTMENT_CHOICES, blank=True)
    department_other = models.CharField(max_length=50, blank=True, help_text='其他部门名称')
    api_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Django auth compatibility properties
    is_authenticated = True
    is_anonymous = False

    def regenerate_token(self):
        """Generate a new API token."""
        self.api_token = uuid.uuid4()
        self.save(update_fields=['api_token', 'updated_at'])

    def get_department_display_name(self):
        """Return department display name."""
        if self.department == '其他' and self.department_other:
            return self.department_other
        return self.get_department_display()

    def __str__(self):
        return f"{self.full_name} ({self.employee_id})"


class ManagerProfile(models.Model):
    """Profile for admin/manager users."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='manager_profile'
    )
    employee_id = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, blank=True)

    # Permission flags
    is_super_admin = models.BooleanField(default=False)
    can_approve_registrations = models.BooleanField(default=True)
    can_approve_work_orders = models.BooleanField(default=True)

    api_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    active = models.BooleanField(default=True)
    preferences = models.JSONField(default=dict, blank=True, help_text='User preferences JSON (card fields, etc.)')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Django auth compatibility
    is_authenticated = True
    is_anonymous = False

    class Meta:
        verbose_name = '管理员'
        verbose_name_plural = '管理员'

    def __str__(self):
        return f"{self.full_name} ({self.employee_id})"

    def regenerate_token(self):
        self.api_token = uuid.uuid4()
        self.save(update_fields=['api_token', 'updated_at'])


class DepartmentUserProfile(models.Model):
    """Profile for department users (FES, FAM, ENT)."""

    DEPARTMENT_CHOICES = [
        ('FES', 'FES'),
        ('FAM', 'FAM'),
        ('ENT', 'ENT'),
        ('其他', '其他'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='dept_profile'
    )
    employee_id = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, blank=True)
    department = models.CharField(max_length=20, choices=DEPARTMENT_CHOICES, default='ENT')
    department_other = models.CharField(max_length=50, blank=True)

    api_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Django auth compatibility
    is_authenticated = True
    is_anonymous = False

    class Meta:
        verbose_name = '部门用户'
        verbose_name_plural = '部门用户'

    def get_department_display_name(self):
        if self.department == '其他' and self.department_other:
            return self.department_other
        return self.get_department_display()

    def __str__(self):
        return f"{self.full_name} ({self.employee_id} - {self.get_department_display_name()})"


class RegistrationRequest(models.Model):
    """Registration request pending admin approval."""

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'

    STATUS_CHOICES = [
        (STATUS_PENDING, '待审批'),
        (STATUS_APPROVED, '已批准'),
        (STATUS_REJECTED, '已拒绝'),
    ]

    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    username = models.CharField(max_length=150, unique=True, blank=True, null=True, help_text='登录用户名')
    password = models.CharField(max_length=128, blank=True, help_text='登录密码（加密存储）')
    department = models.CharField(max_length=20, choices=Worker.DEPARTMENT_CHOICES, blank=True)
    department_other = models.CharField(max_length=50, blank=True, help_text='其他部门名称')
    requested_role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_FIELD_WORKER
    )
    employee_id = models.CharField(max_length=50, blank=True, help_text='工号，审批通过后自动生成')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    status_notes = models.TextField(blank=True, help_text='审批备注')
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(
        Worker, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='processed_registrations'
    )
    created_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='registration_request'
    )

    class Meta:
        verbose_name = '注册申请'
        verbose_name_plural = '注册申请'

    def __str__(self):
        return f"注册申请 - {self.full_name} ({self.get_requested_role_display()})"


# (removed: WorkOrder)
class WeatherData(models.Model):
    """Stores daily weather data with hourly forecasts in JSON format."""

    latitude = models.DecimalField(max_digits=8, decimal_places=5)
    longitude = models.DecimalField(max_digits=8, decimal_places=5)
    date = models.DateField(db_index=True)
    hourly_data = models.JSONField(default=list, help_text='Hourly weather data: [{hour, temp, humidity, precipitation, wind_speed, weather_code}]')
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['latitude', 'longitude', 'date']
        ordering = ['-date']

    def __str__(self):
        return f"Weather ({self.latitude}, {self.longitude}) - {self.date}"

    def get_weather_description(self, code):
        """Convert WMO weather code to description."""
        codes = {
            0: '晴朗',
            1: '基本晴朗', 2: '部分多云', 3: '阴天',
            45: '雾', 48: '冻雾',
            51: '微细雨', 53: '细雨', 55: '密细雨',
            56: '微冻细雨', 57: '密冻细雨',
            61: '小雨', 63: '中雨', 65: '大雨',
            66: '小冻雨', 67: '大冻雨',
            71: '小雪', 73: '中雪', 75: '大雪', 77: '雪粒',
            80: '小阵雨', 81: '中阵雨', 82: '大阵雨',
            85: '小阵雪', 86: '大阵雪',
            95: '雷暴', 96: '雷暴伴小冰雹', 99: '雷暴伴大冰雹',
        }
        return codes.get(code, '未知')


class RequestBase(models.Model):
    """Base model for all request types."""

    STATUS_SUBMITTED = 'submitted'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_INFO_NEEDED = 'info_needed'

    STATUS_CHOICES = [
        (STATUS_SUBMITTED, '已提交'),
        (STATUS_APPROVED, '已批准'),
        (STATUS_REJECTED, '已拒绝'),
        (STATUS_INFO_NEEDED, '需补充信息'),
    ]

    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='%(class)s',
                             null=True, blank=True, help_text='(Legacy) 主区域，新记录使用 zones M2M')
    # submitter is the legacy Worker FK (kept for irrigation-worker submissions).
    # Department users have no Worker row, so submitter_user holds their Django User.
    # Display should prefer submitter_user → submitter → username (see submitter_display).
    submitter = models.ForeignKey(Worker, on_delete=models.CASCADE, null=True, blank=True)
    submitter_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        help_text='提交需求的部门用户（Django User）。灌溉员提交走 submitter(Worker)。')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SUBMITTED)
    status_notes = models.TextField(blank=True, help_text='管理员处理备注')
    approver = models.ForeignKey(
        Worker, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='%(class)s_approved', help_text='审批人'
    )
    processed_at = models.DateTimeField(null=True, blank=True, help_text='审批时间')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# (removed: MaintenanceRequest)
class WaterRequest(RequestBase):
    """浇水协调需求 request.

    submitter 继承自 RequestBase（可空）：灌溉员提交时填 submitter(Worker)，
    部门用户提交时填 submitter_user(User)，二者至少一个有值。
    """

    USER_TYPE_CHOICES = [
        ('ENT', 'ENT'),
        ('FAM', 'FAM'),
        ('FES', 'FES'),
        ('其他', '其他'),
    ]

    REQUEST_TYPE_CHOICES = [
        ('停水需求', '停水需求'),
        ('新苗程序', '新苗程序'),
        ('减小水量', '减小水量'),
        ('加大水量', '加大水量'),
        ('其他需求', '其他需求'),
    ]

    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, default='ENT')
    user_type_other = models.CharField(max_length=50, blank=True, help_text='其他用户类型')
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPE_CHOICES, default='停水需求')
    request_type_other = models.CharField(max_length=50, blank=True, help_text='其他需求类别')
    start_datetime = models.DateTimeField(help_text='需求起始时间')
    end_datetime = models.DateTimeField(help_text='需求结束时间')
    photos = models.JSONField(default=list, help_text='照片URL列表')
    # Multi-zone support: one request can cover several zones (approved once for all).
    # `zone` (inherited FK) is kept for legacy single-zone data; new requests use `zones`.
    zones = models.ManyToManyField('Zone', related_name='water_requests', blank=True,
                                   verbose_name='区域', help_text='该需求涉及的多个区域')

    class Meta:
        db_table = 'water_requests'

    @property
    def all_zones(self):
        """All zones on this request (M2M first, fallback to the legacy FK)."""
        zs = list(self.zones.all())
        if not zs and self.zone_id:
            zs = [self.zone]
        return zs

    @property
    def submitter_display(self):
        """Display name for whoever submitted this request. Department users are
        stored on submitter_user (a Django User with no Worker row); irrigation
        workers on submitter. Prefer whichever is set, fall back to username."""
        if self.submitter_user_id:
            u = self.submitter_user
            return (u.get_full_name() or u.username) if u else '(未知用户)'
        if self.submitter_id and self.submitter:
            return self.submitter.full_name or self.submitter.employee_id or '(未知)'
        return '(未知)'

    def __str__(self):
        names = ', '.join(z.name for z in self.all_zones) or '未指定区域'
        return f"浇水协调 - {names} ({self.request_type})"


# ============================================
# Maxicom2 Irrigation System Models
# Data imported from Maxicom2.mdb (Rain Bird Central Control)
# ============================================


class MaxicomController(models.Model):
    """Controller (CCU/SAT) from Maxicom2 system."""
    site = models.ForeignKey(Patch, on_delete=models.CASCADE, related_name='controllers')
    mdb_index = models.IntegerField()
    name = models.CharField(max_length=255)
    controller_type = models.CharField(max_length=255, blank=True)
    site_number = models.IntegerField()
    link_number = models.IntegerField()
    link_channel = models.IntegerField()
    enabled = models.BooleanField(default=True)
    date_open = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ['site', 'link_number', 'link_channel']
        verbose_name = 'Maxicom控制器'
        verbose_name_plural = 'Maxicom控制器'

    def __str__(self):
        return f"{self.name} (Site {self.site_number})"



class MaxicomSchedule(models.Model):
    """Irrigation schedule from Maxicom2 system."""
    site = models.ForeignKey(Patch, on_delete=models.CASCADE, related_name='schedules')
    mdb_index = models.IntegerField()
    name = models.CharField(max_length=255)
    nominal_et = models.FloatField(null=True, blank=True)
    water_budget_factor = models.IntegerField(null=True, blank=True)
    flo_manage = models.BooleanField(default=False)
    send_automatic = models.BooleanField(default=False)
    send_protected = models.BooleanField(default=False)
    instruction_file = models.CharField(max_length=255, blank=True)
    sensitized_et = models.BooleanField(default=False)
    date_open = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = 'Maxicom计划'
        verbose_name_plural = 'Maxicom计划'

    def __str__(self):
        return f"{self.name} @ {self.site.name}"


class MaxicomFlowZone(models.Model):
    """Flow monitoring zone from Maxicom2 system."""
    site = models.ForeignKey(Patch, on_delete=models.CASCADE, related_name='flow_zones')
    mdb_index = models.IntegerField()
    name = models.CharField(max_length=255)
    join_site = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Maxicom流量区域'
        verbose_name_plural = 'Maxicom流量区域'

    def __str__(self):
        return f"{self.name} @ {self.site.name}"


class MaxicomWeatherStation(models.Model):
    """Weather station from Maxicom2 system."""
    mdb_index = models.IntegerField(unique=True)
    name = models.CharField(max_length=255)
    default_et = models.FloatField(null=True, blank=True)
    time_zone = models.CharField(max_length=50, blank=True)

    class Meta:
        verbose_name = 'Maxicom气象站'
        verbose_name_plural = 'Maxicom气象站'

    def __str__(self):
        return self.name


class MaxicomWeatherLog(models.Model):
    """Weather reading from Maxicom2 system."""
    weather_station = models.ForeignKey(MaxicomWeatherStation, on_delete=models.CASCADE, related_name='readings')
    timestamp = models.CharField(max_length=20, db_index=True)
    temperature = models.FloatField(null=True, blank=True)
    max_temp = models.FloatField(null=True, blank=True)
    min_temp = models.FloatField(null=True, blank=True)
    solar_radiation = models.FloatField(null=True, blank=True)
    rainfall = models.FloatField(null=True, blank=True)
    humidity = models.FloatField(null=True, blank=True)
    wind_run = models.FloatField(null=True, blank=True)
    et = models.FloatField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['weather_station', 'timestamp']),
        ]
        verbose_name = 'Maxicom气象数据'
        verbose_name_plural = 'Maxicom气象数据'

    def __str__(self):
        return f"{self.weather_station.name} @ {self.timestamp}"


class MaxicomEvent(models.Model):
    """System event from Maxicom2 system."""
    timestamp = models.CharField(max_length=20, db_index=True)
    source = models.CharField(max_length=5, blank=True, help_text='Event source (S=Site, W=Weather)')
    index = models.IntegerField(null=True, blank=True)
    event_number = models.IntegerField(null=True, blank=True)
    flag = models.CharField(max_length=5, blank=True, help_text='E=Error, W=Warning, I=Info')
    text = models.TextField(blank=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Maxicom事件'
        verbose_name_plural = 'Maxicom事件'

    def __str__(self):
        return f"[{self.flag}] {self.text[:80]}"


class MaxicomFlowReading(models.Model):
    """Flow zone reading from Maxicom2 system (time series)."""
    flow_zone = models.ForeignKey(MaxicomFlowZone, on_delete=models.CASCADE, related_name='readings')
    timestamp = models.CharField(max_length=20, db_index=True)
    value = models.IntegerField(null=True, blank=True)
    multiplier = models.IntegerField(null=True, blank=True)
    site_id = models.IntegerField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['flow_zone', 'timestamp']),
        ]
        verbose_name = 'Maxicom流量数据'
        verbose_name_plural = 'Maxicom流量数据'

    def __str__(self):
        return f"{self.flow_zone.name} @ {self.timestamp}: {self.value}"


class MaxicomSignalLog(models.Model):
    """Signal log from Maxicom2 system."""
    timestamp = models.CharField(max_length=20, db_index=True)
    index = models.IntegerField(null=True, blank=True)
    controller_channel = models.IntegerField(null=True, blank=True)
    signal_index = models.IntegerField(null=True, blank=True)
    signal_table = models.CharField(max_length=5, blank=True)
    signal_type = models.CharField(max_length=5, blank=True)
    signal_value = models.IntegerField(null=True, blank=True)
    signal_multiplier = models.FloatField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['timestamp']),
        ]
        verbose_name = 'Maxicom信号日志'
        verbose_name_plural = 'Maxicom信号日志'

    def __str__(self):
        return f"Signal @ {self.timestamp} ch{self.controller_channel}"


class MaxicomETCheckbook(models.Model):
    """ET checkbook (soil moisture balance) from Maxicom2 system."""
    timestamp = models.CharField(max_length=20, db_index=True)
    site = models.ForeignKey(Patch, on_delete=models.CASCADE, related_name='et_checkbooks')
    soil_moisture = models.FloatField(null=True, blank=True)
    rainfall = models.FloatField(null=True, blank=True)
    et = models.FloatField(null=True, blank=True)
    irrigation = models.FloatField(null=True, blank=True)
    soil_moisture_capacity = models.FloatField(null=True, blank=True)
    soil_refill_pct = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = 'Maxicom ET账本'
        verbose_name_plural = 'Maxicom ET账本'

    def __str__(self):
        return f"ET Checkbook {self.site.name} @ {self.timestamp}"


class SyncAgentHeartbeat(models.Model):
    """Tracks the last heartbeat from the Maxicom2 sync agent."""
    last_heartbeat = models.DateTimeField(auto_now=True)
    last_sync_counts = models.JSONField(default=dict, blank=True, help_text='Record counts from last sync')
    agent_version = models.CharField(max_length=50, blank=True, default='')

    class Meta:
        verbose_name = '同步代理心跳'
        verbose_name_plural = '同步代理心跳'

    def __str__(self):
        return f"Sync Agent Heartbeat: {self.last_heartbeat}"

    @classmethod
    def get_instance(cls):
        """Get or create the singleton heartbeat instance."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class MaxicomRuntime(models.Model):
    """Runtime data from Maxicom2 system."""
    timestamp = models.CharField(max_length=20, db_index=True)
    station = models.ForeignKey(Patch, on_delete=models.CASCADE, related_name='runtime_as_station', null=True, blank=True)
    site = models.ForeignKey(Patch, on_delete=models.CASCADE, related_name='runtime_as_site')
    station_id_raw = models.IntegerField(help_text='Original StationID from MDB')
    run_time = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = 'Maxicom运行时间'
        verbose_name_plural = 'Maxicom运行时间'
        # (site, timestamp) backs the dashboard/PDF/Excel pivot queries that filter
        # `site=<ccu> AND timestamp__gte/lte`; timestamp alone is already indexed.
        indexes = [models.Index(fields=['site', 'timestamp'])]

    def __str__(self):
        return f"Runtime {self.site.name} @ {self.timestamp}"


class EquipmentCatalog(models.Model):
    """Catalog of equipment models that can be reused across zones."""

    EQUIPMENT_TYPE_CHOICES = [
        ('sprinkler', '灌水器类型'),
        ('solenoid_valve', '电磁阀'),
        ('isolation_valve', '隔离阀'),
        ('end_flush_valve', '末端冲洗阀'),
        ('surface_flush_valve', '地面冲洗阀'),
    ]

    equipment_type = models.CharField(max_length=50, choices=EQUIPMENT_TYPE_CHOICES)
    model_name = models.CharField(max_length=255, help_text='Equipment model name')
    manufacturer = models.CharField(max_length=255, blank=True, help_text='Manufacturer/brand')
    specifications = models.JSONField(default=dict, blank=True, help_text='Type-specific specifications (flow rate, pressure, size, etc.)')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['equipment_type', 'manufacturer', 'model_name']
        verbose_name = 'Equipment Catalog'
        verbose_name_plural = 'Equipment Catalog'

    def __str__(self):
        return f"{self.get_equipment_type_display()} - {self.manufacturer} {self.model_name}"


class ZoneEquipment(models.Model):
    """Equipment instance installed in a zone."""

    STATUS_CHOICES = [
        ('working', '正常工作'),
        ('needs_repair', '需要维修'),
        ('replaced', '已更换'),
        ('inactive', '未使用'),
    ]

    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='equipments')
    equipment = models.ForeignKey(EquipmentCatalog, on_delete=models.PROTECT, related_name='zone_installations')
    quantity = models.IntegerField(default=1, help_text='Number of this equipment in the zone')
    installation_date = models.DateField(null=True, blank=True, help_text='Installation date')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='working')
    location_in_zone = models.CharField(max_length=255, blank=True, help_text='Specific location within zone')
    notes = models.TextField(blank=True, help_text='Additional notes or maintenance history')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['equipment__equipment_type', 'id']
        verbose_name = 'Zone Equipment'
        verbose_name_plural = 'Zone Equipment'

    def __str__(self):
        return f"{self.equipment.model_name} x{self.quantity} in {self.zone.name}"


# ==========================================================================
# 维修工单系统 (Maintenance Work Report System)
# ==========================================================================



# (removed: WorkCategory)
class WorkReport(models.Model):
    """维修工作日报 - daily maintenance work record."""

    SHIFT_CHOICES = [
        ('早班', '早班'),
        ('白班', '白班'),
        ('夜班', '夜班'),
    ]

    date = models.DateField('日期', db_index=True)
    weather = models.CharField('天气', max_length=50, blank=True)
    worker = models.ForeignKey(Worker, on_delete=models.PROTECT, related_name='work_reports', verbose_name='处理人')
    location = models.ForeignKey(Patch, on_delete=models.PROTECT, null=True, blank=True, related_name='work_reports', verbose_name='位置/CCU',
                                 help_text='可选；留空时按所选区域的所属位置自动填充')
    zone_location = models.ForeignKey(Zone, on_delete=models.SET_NULL, null=True, blank=True, related_name='work_reports', verbose_name='故障/事件位置')
    remark = models.TextField('备注/工作内容', blank=True)
    is_pending_repair = models.BooleanField('待修', default=False)
    is_difficult = models.BooleanField('疑难问题', default=False)
    is_difficult_resolved = models.BooleanField('疑难问题已处理', default=False)
    resolved_by_pm = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='resolved_repairs', verbose_name='处理该待修的计划性维修工单',
        help_text='计划性维修工单处理本待修后自动回填；用于工单管理页展示闭环关系',
    )
    photos = models.JSONField(default=list, blank=True, verbose_name='照片列表', help_text='照片文件路径列表')

    # Mobile workorder fields
    shift = models.CharField('班次', max_length=10, choices=SHIFT_CHOICES, blank=True)
    work_start_time = models.TimeField('工作开始时间', null=True, blank=True)
    work_end_time = models.TimeField('工作完成时间', null=True, blank=True)
    team_size = models.PositiveIntegerField('灌溉组人数', default=1)
    third_party_count = models.PositiveIntegerField('第三方人数', default=0)
    team_hours = models.FloatField('灌溉组工时', default=0, help_text='Auto-calculated, precision 0.5h')
    third_party_hours = models.FloatField('第三方工时', default=0, help_text='Auto-calculated, precision 0.5h')
    zones = models.ManyToManyField(Zone, blank=True, related_name='workorder_records', verbose_name='区域')
    zone_names = models.TextField('通称位置', blank=True, help_text='Auto-filled from zone codes')
    work_content = models.TextField('工作内容', blank=True)
    # Human-readable ticket number. PM-dispatched work orders get "PM-{gwo_id}";
    # manually submitted ones stay blank and display as "#{id}".
    ticket_number = models.CharField('工单编号', max_length=30, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-id']
        verbose_name = '维修工作日报'
        verbose_name_plural = '维修工作日报'
        indexes = [
            # list/stats queries always pair a date window with worker or
            # zone_location; the single-column date index could serve only one
            # dimension. These composites cover both.
            models.Index(fields=['worker', '-date'], name='core_wr_worker_date'),
            models.Index(fields=['zone_location', '-date'],
                         name='core_wr_zone_date'),
        ]

    def __str__(self):
        return f"{self.date} | {self.worker} | {self.location or '(无位置)'}"

    @property
    def display_number(self):
        """User-facing ticket number. PM-dispatched orders show 'PM-xxx',
        regular submissions fall back to '#{id}'."""
        return self.ticket_number or f'#{self.id}'


class WorkReportComment(models.Model):
    """工单评论 - a comment left by any user on a posted WorkReport.

    Both 灌溉一线 (field workers) and manager/admin accounts can read and post
    comments on any workorder (mirroring the "everyone sees all workorders"
    visibility rule). The author is the Worker resolved from the commenter's
    account via role_utils.resolve_or_create_worker, so every comment is
    attributable to a real person regardless of account type.
    """

    work_report = models.ForeignKey(
        WorkReport, on_delete=models.CASCADE, related_name='comments',
        verbose_name='工单',
    )
    author = models.ForeignKey(
        Worker, on_delete=models.SET_NULL, null=True, related_name='workreport_comments',
        verbose_name='评论人',
    )
    body = models.TextField('评论内容')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = '工单评论'
        verbose_name_plural = '工单评论'

    def __str__(self):
        name = self.author.full_name if self.author else '(未知)'
        return f"{name} @ {self.created_at:%Y-%m-%d %H:%M}"


class WorkReportEditLog(models.Model):
    """编辑记录 - 每次有人编辑保存工单时自动写入一条。

    记录编辑人、编辑时间，一条工单可对应多条，按时间正序保留全部历史。
    编辑人通过 role_utils.resolve_or_create_worker 解析，任意账号类型都能
    正确归因（与 WorkReportComment.author 一致）。
    """

    work_report = models.ForeignKey(
        WorkReport, on_delete=models.CASCADE, related_name='edit_logs',
        verbose_name='工单',
    )
    editor = models.ForeignKey(
        Worker, on_delete=models.SET_NULL, null=True,
        related_name='workreport_edits', verbose_name='编辑人',
    )
    note = models.CharField('说明', max_length=200, blank=True, default='')
    created_at = models.DateTimeField('编辑时间', auto_now_add=True)

    class Meta:
        ordering = ['created_at']           # 时间正序，最旧→最新
        verbose_name = '编辑记录'
        verbose_name_plural = '编辑记录'

    def __str__(self):
        name = self.editor.full_name if self.editor else '(未知)'
        return f"{name} @ {self.created_at:%Y-%m-%d %H:%M}"


class Announcement(models.Model):
    """通知公告 - a global announcement published by a manager/admin.

    Active announcements that a user has not yet acknowledged pop up on the
    dashboard; the user must acknowledge each before it stops reappearing on
    login / dashboard navigation.
    """

    title = models.CharField('标题', max_length=200)
    body = models.TextField('内容')
    active = models.BooleanField('启用', default=True,
                                 help_text='取消勾选则不再向任何人弹出（已确认记录保留）')
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='announcements', verbose_name='发布人',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '通知公告'
        verbose_name_plural = '通知公告'

    def __str__(self):
        return f"{self.title} ({self.created_at:%Y-%m-%d %H:%M})"


class AnnouncementAcknowledgment(models.Model):
    """通知确认记录 - tracks that a user has acknowledged an Announcement.

    One row per (announcement, user). Its absence is what makes an announcement
    show up in the dashboard popup for that user.
    """

    announcement = models.ForeignKey(
        Announcement, on_delete=models.CASCADE, related_name='acknowledgments',
        verbose_name='通知',
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='announcement_acks',
        verbose_name='用户',
    )
    acknowledged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('announcement', 'user')
        verbose_name = '通知确认'
        verbose_name_plural = '通知确认'

    def __str__(self):
        return f"{self.user} ✓ {self.announcement}"


# (removed: WorkReportFault)
class WorkItem(models.Model):
    """工单「工作内容」模板树节点 - 自引用树，承载完整 现场作业记录 层级。

    首次由 seed_work_items 命令解析 工单记录格式.md 灌入；之后管理员可在后台增删改。
    叶子节点(value_type != group)才是可填报的；group 仅作容器。
    """

    SECTION_CHOICES = [
        ('routine_maint', '常规维护'),
        ('irrigation_project', '灌溉项目'),
        ('routine_support', '常规配合'),
        ('greenhouse_nursery', '温室和苗圃维护'),
        ('warehouse', '仓库整理'),
        ('meeting_training', '会议和培训'),
        ('repair_emergency', '报修应急'),
        ('other_project', '其他项目'),
        ('drainage_project', '排水项目'),
        ('typhoon_emergency', '台风应急'),
        ('safety_incident', '安全事件记录'),
        ('good_deed', '优秀事迹记录'),
    ]
    VALUE_TYPE_CHOICES = [
        ('group', '分组(无值)'),
        ('count', '计数'),
        ('status', '状态选择'),
        ('toggle', '勾选(无数量)'),
        ('text', '纯文本'),
        ('text_photo', '文本+照片'),
    ]

    code = models.CharField('编码', max_length=100, unique=True, help_text='文档点号路径，幂等灌入与外部引用键')
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE,
        related_name='children', verbose_name='父节点',
    )
    name_zh = models.CharField('中文名', max_length=255)
    name_en = models.CharField('英文名', max_length=255, blank=True)
    order = models.PositiveIntegerField('同级排序', default=0)
    level = models.PositiveIntegerField('层级深度', default=0)
    section = models.CharField('顶层章节', max_length=30, choices=SECTION_CHOICES, db_index=True)
    value_type = models.CharField('值类型', max_length=20, choices=VALUE_TYPE_CHOICES, default='count')
    status_options = models.JSONField('状态选项', default=list, blank=True, help_text='仅 status 型：可选状态列表')
    unit = models.CharField('单位', max_length=20, blank=True, help_text='仅 count 型，如 m / 个')
    is_project_scoped = models.BooleanField('需绑定项目', default=False, help_text='灌溉项目章节的节点填报时需选 Project')
    active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['section', 'order', 'code']
        verbose_name = '工作内容节点'
        verbose_name_plural = '工作内容节点'

    def __str__(self):
        return f"{self.code} {self.name_zh}"


class Project(models.Model):
    """灌溉项目实例 - 管理员预先创建(FAM/WDI/其它)；工单提交时下拉选择。

    对应文档「灌溉项目」下的 项目1/项目2/项目…。项目数量随管理员增减动态变化。
    设计/出图/报预算等 PM 阶段不在此表，而是 WorkItem 模板子树里的节点。
    """

    CATEGORY_CHOICES = [
        ('IRRIGATION', '灌溉项目'),
        ('DRAINAGE', '排水项目'),
        ('OTHER', '其他项目'),
    ]
    SUBCATEGORY_CHOICES = [
        ('FAM', 'FAM项目'),
        ('FES', 'FES项目'),
        ('WDI', 'WDI项目'),
        ('GREEN', '绿化项目'),
    ]

    name = models.CharField('项目名称', max_length=200)
    category = models.CharField('项目类别', max_length=20, choices=CATEGORY_CHOICES, default='IRRIGATION')
    subcategory = models.CharField('子类别', max_length=20, choices=SUBCATEGORY_CHOICES, blank=True,
                                   help_text='仅灌溉项目：FAM/FES/WDI/绿化')
    symbol = models.CharField('项目代号', max_length=50, blank=True)
    code = models.CharField('项目Code', max_length=100, blank=True)
    active = models.BooleanField('启用', default=True)
    is_completed = models.BooleanField('已完成', default=False,
                                        help_text='标记项目是否已完工')
    start_date = models.DateField('开工日期', null=True, blank=True)
    planned_end_date = models.DateField('计划完工日期', null=True, blank=True)
    notes = models.TextField('备注', blank=True)
    # 项目预算（经理按金额填写）。材料余额 = 材料预算 − Σ关联采购订单金额，在前端实时计算。
    # 已用工时仍由关联工单的 Σ team_hours / Σ third_party_hours 自动聚合展示。
    material_budget_amount = models.DecimalField(
        '材料预算金额', max_digits=14, decimal_places=2, null=True, blank=True,
        help_text='经理填写；材料余额 = 材料预算 − Σ关联采购订单金额')
    labor_budget_amount = models.DecimalField(
        '人工预算金额', max_digits=14, decimal_places=2, null=True, blank=True,
        help_text='经理填写')
    # 工时费率（每项目独立，元/小时）。人工余额 = 人工预算金额 −
    # (Σ灌溉组已用工时 × 灌溉组rate + Σ第三方已用工时 × 第三方rate)，已用工时由工单汇总。
    team_rate = models.DecimalField(
        '灌溉组工时费率', max_digits=14, decimal_places=2, null=True, blank=True,
        help_text='元/小时；人工余额 = 人工预算 − 已用工时 × 费率')
    third_party_rate = models.DecimalField(
        '第三方工时费率', max_digits=14, decimal_places=2, null=True, blank=True,
        help_text='元/小时；人工余额 = 人工预算 − 已用工时 × 费率')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'subcategory', 'name']
        verbose_name = '灌溉项目'
        verbose_name_plural = '灌溉项目'
        unique_together = ('category', 'subcategory', 'name')

    def __str__(self):
        sub = f"/{self.get_subcategory_display()}" if self.subcategory else ""
        return f"[{self.get_category_display()}{sub}] {self.name}"


class WorkReportEntry(models.Model):
    """工单填报明细 - 只为「填了的叶子」存一行。"""

    work_report = models.ForeignKey(
        WorkReport, on_delete=models.CASCADE, related_name='entries', verbose_name='工单',
    )
    work_item = models.ForeignKey(
        WorkItem, on_delete=models.PROTECT, related_name='entries', verbose_name='节点',
    )
    project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='entries', verbose_name='项目',
    )
    count = models.PositiveIntegerField('数量', default=0)
    status = models.CharField('状态值', max_length=100, blank=True)
    text_value = models.TextField('文本', blank=True)
    photos = models.JSONField('照片', default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('work_report', 'work_item', 'project')
        verbose_name = '工单明细'
        verbose_name_plural = '工单明细'

    def __str__(self):
        return f"{self.work_report} → {self.work_item.name_zh}"


# ==========================================================================
# 库存管理系统 (Inventory Management)
# ==========================================================================


class InventoryCategory(models.Model):
    """库存物料目录树 - 自引用树，承载 盘点.xlsx 的层级。

    由 seed_inventory_from_xlsx 命令从 盘点.xlsx 灌入；之后管理员可在后台增删改。
    叶子节点（无 children）才是可出入库的具体物料；中间节点为分类。
    current_stock 由经理在 /inventory/manage/ 页面设定/调整，每次出入库提交后自动增减。
    min_stock / is_main_material 同样由经理在该页面设定，便于库存预警与主材统计。
    """

    code = models.CharField('编码', max_length=200, unique=True, help_text='路径派生的稳定编码，幂等灌入键')
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE,
        related_name='children', verbose_name='父节点',
    )
    name_zh = models.CharField('中文名', max_length=255)
    order = models.PositiveIntegerField('同级排序', default=0)
    level = models.PositiveIntegerField('层级深度', default=0)
    current_stock = models.IntegerField(
        '现有库存数量', default=0,
        help_text='由经理设定初始值；每次出入库提交后自动增减',
    )
    min_stock = models.IntegerField(
        '最小库存量', default=0,
        help_text='由经理设定；低于此值视为库存不足，便于日后预警',
    )
    is_main_material = models.BooleanField(
        '是否主材', default=False,
        help_text='主材在日后管理中着重统计与分析',
    )
    # Unit for stock quantities (e.g. '个', 'm', '瓶'). Parsed from the 盘点
    # spreadsheet's 最小库存 column ("100个" → unit='个', "1000m" → unit='m').
    unit = models.CharField('单位', max_length=10, blank=True, default='',
                            help_text='库存计量单位，如 个/m/瓶')
    # Explicit node type so an empty directory (no children yet) is not mistaken
    # for a stockable part. 'category' = branch (holds sub-items), 'part' = leaf
    # (a concrete SKU with stock). Seeded from the markdown tree's structure;
    # manager-created nodes set this on creation.
    NODE_TYPE_CHOICES = [('category', '目录'), ('part', '部件')]
    node_type = models.CharField(
        '节点类型', max_length=10, choices=NODE_TYPE_CHOICES, default='part',
        help_text='目录=可含子项的分类；部件=可出入库的具体物料',
    )
    active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'code']
        verbose_name = '库存物料'
        verbose_name_plural = '库存物料'

    def __str__(self):
        return f"{self.code} {self.name_zh}"


class InventoryTransaction(models.Model):
    """库存流水单 - 一次提交（一个 cart），含一种操作类型 + 多个物料行。

    operation 决定库存增减方向：入库（含采购/借用归还/拆回利旧）→ +，
    出库（含日常维护/项目/借用）→ -。
    """

    OPERATION_CHOICES = [
        ('入库', '入库'),
        ('出库', '出库'),
    ]
    # 入库子类型: 采购(填订单号) / 借用归还 / 拆回利旧
    INBOUND_SUBTYPES = [('采购', '采购'), ('借用归还', '借用归还'), ('拆回利旧', '拆回利旧')]
    # 出库去向: 日常维护 / 项目 / 借用
    OUTBOUND_DESTINATIONS = [('日常维护', '日常维护'), ('项目', '项目'), ('借用', '借用')]
    # 出库-项目时可选预估/实际消耗。预估消耗提交后不扣库存、不计入项目实际
    # 消耗，待在库存管理页确认（可调整实际数量）后才扣库存并计入项目。
    CONSUMPTION_MODE_CHOICES = [('actual', '实际'), ('estimated', '预估')]
    date = models.DateField('日期', default=date.today)
    worker = models.ForeignKey(
        Worker, on_delete=models.PROTECT, related_name='inventory_transactions',
        verbose_name='提交人',
    )
    operation = models.CharField('操作类型', max_length=10, choices=OPERATION_CHOICES)
    # 入库时的来源类型(采购/借用归还/拆回利旧) 或 出库时的去向类型(日常维护/项目/借用)。
    entry_subtype = models.CharField('来源/去向类型', max_length=20, blank=True)
    order_no = models.CharField('订单号', max_length=100, blank=True, help_text='入库-采购时填写')
    # 命中某张采购订单时建立关联（入库-采购）。保留 order_no 文本以兼容历史/自由输入。
    purchase_order = models.ForeignKey(
        'PurchaseOrder', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transactions', verbose_name='采购订单',
        help_text='入库-采购且订单号命中采购订单时自动关联',
    )
    counterparty = models.CharField('借用方', max_length=200, blank=True,
                                    help_text='出库-借用时填写（历史去重 + 可自填）')
    related_project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='inventory_transactions', verbose_name='关联项目',
        help_text='出库-项目时选择',
    )
    zone = models.ForeignKey(
        Zone, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='inventory_transactions', verbose_name='关联区域',
        help_text='可选；与具体区域关联',
    )
    # 工单内登记的材料消耗会生成一张关联此工单的出库单。SET_NULL 使得
    # 删除工单不会连带删除库存流水（保留库存账可追溯）。
    work_report = models.ForeignKey(
        'WorkReport', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='material_consumptions', verbose_name='关联工单',
        help_text='工单内登记的材料消耗会生成此关联的出库单',
    )
    consumption_mode = models.CharField(
        '消耗类型', max_length=10, choices=CONSUMPTION_MODE_CHOICES, default='actual',
        help_text='出库-项目时可选预估消耗，确认前不扣库存、不计入项目实际消耗',
    )
    remark = models.TextField('备注', blank=True)
    photos = models.JSONField('照片', default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-id']
        verbose_name = '库存流水'
        verbose_name_plural = '库存流水'
        indexes = [
            # Default ordering + the date-range filter on every ledger query.
            # `date` had no index at all before — every filter(date__gte=…,
            # date__lte=…) was a full scan.
            models.Index(fields=['-date', '-id'], name='core_invtxn_date_id'),
            # 出库-项目 consumption rollup (_project_budget_data) filters on
            # related_project + operation together.
            models.Index(fields=['related_project', 'operation'],
                         name='core_invtxn_proj_op'),
        ]

    def __str__(self):
        return f"{self.date} | {self.operation}-{self.entry_subtype} | {self.worker}"

    @property
    def latest_edit_log(self):
        """Newest edit-log entry (edit_logs is ordered oldest→newest).

        Django's ``|last`` template filter cannot negative-index a queryset
        (raises ValueError on Django 5+), so this property gives the template a
        safe way to read the most recent editor without the filter.
        """
        logs = list(self.edit_logs.all())   # prefetched → no extra query
        return logs[-1] if logs else None


class InventoryTransactionLine(models.Model):
    """库存流水明细 - cart 中每个物料一行。"""

    transaction = models.ForeignKey(
        InventoryTransaction, on_delete=models.CASCADE, related_name='lines',
        verbose_name='流水单',
    )
    category = models.ForeignKey(
        InventoryCategory, on_delete=models.PROTECT, related_name='transaction_lines',
        verbose_name='物料',
    )
    quantity = models.PositiveIntegerField('数量', default=1)
    unit = models.CharField('单位', max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('transaction', 'category')
        verbose_name = '库存明细'
        verbose_name_plural = '库存明细'
        indexes = [
            # Per-category history query (filter(category=cat).order_by(...)) —
            # unique_together covers (transaction, category), not this order.
            models.Index(fields=['category'], name='core_invline_cat'),
        ]

    def __str__(self):
        return f"{self.category.name_zh} × {self.quantity}"


class InventoryTransactionEditLog(models.Model):
    """库存流水编辑记录 - 每次有人编辑保存一条出入库记录时自动写入一条。

    记录编辑人、编辑时间，一条流水可对应多条，按时间正序保留全部历史。
    与 WorkReportEditLog 结构一致，供「XX 于 XX 时间编辑」展示。
    """

    transaction = models.ForeignKey(
        InventoryTransaction, on_delete=models.CASCADE, related_name='edit_logs',
        verbose_name='库存流水',
    )
    editor = models.ForeignKey(
        Worker, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='invtxn_edits', verbose_name='编辑人',
    )
    note = models.CharField('说明', max_length=200, blank=True, default='')
    created_at = models.DateTimeField('编辑时间', auto_now_add=True)

    class Meta:
        ordering = ['created_at']           # 时间正序，最旧→最新
        verbose_name = '库存编辑记录'
        verbose_name_plural = '库存编辑记录'

    def __str__(self):
        name = self.editor.full_name if self.editor else '(未知)'
        return f"{name} @ {self.created_at:%Y-%m-%d %H:%M}"


class PurchaseOrder(models.Model):
    """采购订单 (Purchase Order).

    灌溉订单编号 (order_number) 是必填且唯一的标识，用于在入库-采购表单的
    订单号下拉中匹配。入库-采购流水通过 ``InventoryTransaction.purchase_order``
    反向关联本订单；订单上“已入库物料”由这些流水的明细行聚合得出，不在本表存储。
    """

    order_number = models.CharField('灌溉订单编号', max_length=100, unique=True,
                                    help_text='必填且唯一；入库-采购时据此匹配订单')
    po_number = models.CharField('PO号', max_length=100, blank=True)
    po_amount_untaxed = models.DecimalField(
        'PO未税金额', max_digits=14, decimal_places=2, null=True, blank=True)
    project_name = models.CharField('项目名称', max_length=200, blank=True)
    project_code = models.CharField('项目code', max_length=100, blank=True)
    received_date = models.DateField('收货日期', null=True, blank=True,
                                      help_text='采购订单的收货/到货日期')
    is_completed = models.BooleanField('已完成', default=False,
                                        help_text='计划采购与已入库物料完全匹配后可标记完成；完成的订单仍可被项目引用')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '采购订单'
        verbose_name_plural = '采购订单'
        indexes = [
            # Every list view orders by -created_at; was an in-memory sort.
            models.Index(fields=['-created_at'], name='core_po_created'),
        ]

    def __str__(self):
        return self.order_number


class PurchaseOrderLine(models.Model):
    """采购订单计划明细 - 用户在订单上规划的待采购物料。

    与 InventoryTransactionLine（出入库流水明细）结构一致：每个物料一行，
    PROTECT 防止删除尚被订单引用的目录节点，CASCADE 使订单删除时连带清除明细。
    ``quantity`` 是计划采购量；实际入库量由关联的 入库-采购 流水聚合得出。
    """

    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name='planned_lines',
        verbose_name='采购订单',
    )
    category = models.ForeignKey(
        InventoryCategory, on_delete=models.PROTECT, related_name='po_lines',
        verbose_name='物料',
    )
    quantity = models.PositiveIntegerField('计划数量', default=1)
    unit = models.CharField('单位', max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('purchase_order', 'category')
        verbose_name = '计划采购明细'
        verbose_name_plural = '计划采购明细'

    def __str__(self):
        return f"{self.category.name_zh} × {self.quantity}"


class ProjectPurchaseOrder(models.Model):
    """项目-采购订单轻量关联。

    一个采购订单可能服务于多个项目或日常维护；本表仅表达"这单与这个项目有关"，
    不分摊数量。材料消耗始终走出库-项目自动汇总，与本表无关。
    """

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name='po_links',
        verbose_name='项目',
    )
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name='project_links',
        verbose_name='采购订单',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('project', 'purchase_order')
        verbose_name = '项目-采购订单'
        verbose_name_plural = '项目-采购订单'

    def __str__(self):
        return f"{self.project} ↔ {self.purchase_order}"


# (removed: DemandCategory)
class MapStyleSettings(models.Model):
    """Single-row table storing global map display style preferences."""
    style = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True
    )

    class Meta:
        verbose_name = verbose_name_plural = '地图样式'

    def __str__(self):
        return '地图样式设置'

    @classmethod
    def get_style(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={'style': {}})
        return obj.style

    @classmethod
    def save_style(cls, style_data, user=None):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={'style': {}})
        obj.style = style_data
        obj.updated_by = user
        obj.save()


class AISettings(models.Model):
    """Single-row table storing AI data-analyst configuration.

    Configured by an admin in /admin/: OpenAI-compatible base_url + api_key +
    model name. Read at request time by core.ai_agent to build a LangChain agent.
    """

    enabled = models.BooleanField('启用', default=False)
    api_base_url = models.CharField(
        'API 地址', max_length=255, blank=True, default='',
        help_text='OpenAI 兼容接口地址，如 https://api.deepseek.com/v1',
    )
    api_key = models.CharField(
        'API Key', max_length=255, blank=True, default='',
        help_text='服务商提供的密钥（明文存储，请确保数据库访问受控）',
    )
    model_name = models.CharField(
        '模型名称', max_length=100, blank=True, default='',
        help_text='如 deepseek-chat、gpt-4o-mini、qwen-plus 等',
    )
    temperature = models.FloatField(
        '温度', default=0.3,
        help_text='0=严谨确定，1=发散，数据分析建议 0.2~0.4',
    )
    system_prompt = models.TextField(
        '系统提示词', blank=True, default='',
        help_text='留空则使用默认提示词',
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ai_settings_edits',
    )

    DEFAULT_SYSTEM_PROMPT = (
        '你是一个灌溉管理系统的数据分析助手。'
        '用户会询问工单、浇水需求、设备、灌溉数据等相关问题。'
        '请通过调用提供的工具获取真实数据，然后基于数据进行分析和回答。\n'
        '重要规则：\n'
        '1. 必须基于工具返回的真实数据回答，严禁编造任何数据或编号。\n'
        '2. 如果工具返回空或无数据，如实告知用户，不要臆测。\n'
        '3. 回答用中文，数据用表格或清单呈现更清晰。\n'
        '4. 涉及分析时给出简明结论和可执行建议。\n'
        '\n'
        '## 可用工具（按场景选用）\n'
        '\n'
        '### 查询工具（直接返回结构化数据）\n'
        '- **get_today_date**：获取服务器当前日期/时间。需要确定"今天/最近N天"的日期范围时先调它。\n'
        '- **query_irrigation_overview**：灌溉系统总览（片区数/控制器/站点/气象站/事件数）。用户问"系统概况/有多少站点"时用。\n'
'- **query_work_reports**(start_date, end_date, limit)：查维修工单明细列表（日期/处理人/位置/班次/章节/工时/待修/内容）。用户问"最近有哪些工单/某天的工单"时用。\n'
'- **query_work_report_stats**(start_date, end_date)：工单统计汇总（总数/总工时/按班次·章节·处理人分布、待修数）。用户问"工单统计/工时趋势/谁干的最多"时用这个，不要用 query_work_reports 自己算。\n'
'- **query_zones**(zone_code, limit)：查区域信息（编号/通用名称/片区/面积/优先级/灌水器）。支持按编号或名称模糊查找。用户问"某区域的信息/有多少区域"时用。\n'
'- **query_weather**(days)：查最近若干天天气（每日最高/最低温、降水、主要天气）。\n'
'\n'
'### 代码执行工具（复杂分析、出文件）\n'
'- **run_python_code**(code, description)：运行 Python/pandas 代码。工作目录已预置 CSV：\n'
'    - work_reports.csv（最近90天工单：日期/处理人/位置/班次/章节/工时/待修/内容）\n'
'    - work_entries.csv（最近90天工单明细：日期/章节/节点/数量/状态/文本）\n'
'    - zones.csv（全部区域）\n'
'  用 `import pandas as pd; pd.read_csv("work_reports.csv")` 加载。'
        '生成文件用相对路径（如 df.to_excel("报表.xlsx", index=False) 或 df.to_csv("结果.csv")），'
        '文件会自动提供给用户下载。仅允许 .xlsx/.csv/.json/.txt。\n'
        '\n'
        '### 选工具的原则\n'
        '- 简单查询（"今天多少工单"）→ 用对应的查询工具，快且准。\n'
        '- 统计聚合（"按类别统计工时"）→ 优先 query_work_report_stats；它没有的维度再用 run_python_code。\n'
        '- 用户要求导出文件/Excel/CSV → 必须用 run_python_code 生成文件。\n'
        '- 跨表关联、自定义计算、查询工具无法表达的分析 → 用 run_python_code + pandas。\n'
        '- 不确定今天是几号 → 先 get_today_date。\n'
        '\n'
        '用 run_python_code 生成文件后，回答中要说明文件已生成并列出关键发现。'
    )

    class Meta:
        verbose_name = verbose_name_plural = 'AI 助手设置'

    def __str__(self):
        return 'AI 助手设置'

    @classmethod
    def get_settings(cls):
        """Return the singleton config row, creating it with defaults if absent."""
        obj, _ = cls.objects.get_or_create(pk=1, defaults={
            'system_prompt': cls.DEFAULT_SYSTEM_PROMPT,
        })
        return obj

    def get_system_prompt(self):
        """Use the configured prompt, or fall back to the default."""
        return self.system_prompt.strip() or self.DEFAULT_SYSTEM_PROMPT


class Notification(models.Model):
    """Per-user in-app notification (popup in the top nav, all pages).

    Each row is one recipient + one event. Recipient is a Django ``User``
    (not Worker) because department users — the majority of water-request
    submitters — have no Worker row; keying on User covers every account type.

    Lifecycle: created unread (read_at IS NULL) → the base.html popup shows it
    on the recipient's next page load → 我已知晓 sets read_at → it stops popping
    up but the row is retained as a lightweight inbox history.
    """

    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='notifications',
        verbose_name='接收人',
    )
    verb = models.CharField('类型', max_length=40,
                            help_text='事件类型: comment / request_approved / request_rejected / '
                                      'request_info_needed / request_resubmitted')
    title = models.CharField('标题', max_length=200)
    body = models.TextField('内容', blank=True)
    link = models.CharField('跳转链接', max_length=500, blank=True,
                            help_text='转到按钮的绝对路径，如 /work-reports/42/')
    read_at = models.DateTimeField('已读时间', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '通知'
        verbose_name_plural = '通知'
        indexes = [
            # The popup queries "unread notifications for this user, newest-first"
            # on every authenticated page load — index the recipient + read flag.
            models.Index(fields=['recipient', '-read_at'], name='core_notif_unread'),
        ]

    def __str__(self):
        return f'{self.verb} → {self.recipient.username}: {self.title}'


# ==========================================================================
# 作业计划-定期维护工单系统 (PM / Preventive Maintenance)
# ==========================================================================


class Satellite(models.Model):
    """SAT 卫星控制器 — 对应 zone.code 的前两段（CCU号-控制器号）。

    一个 SAT 下挂多个 Zone。POC 取水点本质上是同一层（某些 SAT 同时是
    POC）。从 zone.code 自动生成，无需手动维护。
    """

    code = models.CharField('SAT编号', max_length=20, unique=True, help_text='如 "35-2"')
    name = models.CharField('名称', max_length=255, blank=True, help_text='如 "探索路"')
    patch = models.ForeignKey(
        Patch, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='satellites', verbose_name='所属CCU',
    )
    active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']
        verbose_name = 'SAT卫星控制器'
        verbose_name_plural = 'SAT卫星控制器'

    def __str__(self):
        return f'{self.code} {self.name}'.strip()


class Crew(models.Model):
    """班组 — 一组工人负责一片区域。

    PM 计划关联到班组，派发时由班组组长(worker)接收工单。
    """

    name = models.CharField('班组名称', max_length=100)
    leader = models.ForeignKey(
        Worker, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='led_crews', verbose_name='组长',
    )
    members = models.ManyToManyField(Worker, blank=True, related_name='crews', verbose_name='成员')
    lands = models.ManyToManyField(Land, blank=True, related_name='crews', verbose_name='负责区域(Land)')
    active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = '班组'
        verbose_name_plural = '班组'

    def __str__(self):
        return self.name


class JobPlanTemplate(models.Model):
    """作业计划模板（JobPlan）— 一类定期维护任务的标准定义。

    对应 Maximo 的 JobPlan，如「超级重点区目检」「主阀检查」等。
    每类 JobPlan 对应一种 asset_level（资产粒度）。
    """

    ASSET_LEVEL_CHOICES = [
        ('ccu', 'CCU级（每CCU一个工单）'),
        ('sat', 'SAT级（每SAT一个工单）'),
        ('zone_group', 'Zone组级（按通用位置分组）'),
    ]

    name = models.CharField('JobPlan名称', max_length=100, unique=True)
    description = models.TextField('描述', blank=True)
    asset_level = models.CharField('资产粒度', max_length=20, choices=ASSET_LEVEL_CHOICES, default='zone_group')
    active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = '作业计划模板'
        verbose_name_plural = '作业计划模板'

    def __str__(self):
        return self.name


class MaintenancePlan(models.Model):
    """PM 预防性维护计划 — 资产 + JobPlan + 频率 = 唯一PM编号。

    对应 Maximo 的 PM。按频率周期性自动生成工单（WorkReport）。
    资产关联三选一，由 job_plan.asset_level 决定使用哪个字段。
    """

    FREQ_UNIT_CHOICES = [
        ('days', '天'),
        ('weeks', '周'),
        ('months', '月'),
    ]

    pm_number = models.CharField('PM编号', max_length=50, unique=True, help_text='Maximo PM编号，如 "703605MJ1D"')
    job_plan = models.ForeignKey(
        JobPlanTemplate, on_delete=models.PROTECT, related_name='plans', verbose_name='作业计划',
    )
    crew = models.ForeignKey(
        Crew, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pm_plans', verbose_name='负责班组',
    )
    # 频率
    frequency_value = models.PositiveIntegerField('频率值', default=1, help_text='如 每2周 → 值=2')
    frequency_unit = models.CharField('频率单位', max_length=10, choices=FREQ_UNIT_CHOICES, default='weeks')
    # 派发控制
    start_date = models.DateField('启动日期', help_text='基准日期（上次执行日），首次到期日从此开始算')
    lead_days = models.PositiveIntegerField('提前生成天数', default=1, help_text='提前N天生成工单')
    active = models.BooleanField('启用', default=True)
    last_generated_date = models.DateField('上次生成日期', null=True, blank=True)
    # 资产关联（三选一）
    patch = models.ForeignKey(Patch, on_delete=models.SET_NULL, null=True, blank=True, related_name='pm_plans', verbose_name='关联CCU')
    satellite = models.ForeignKey(Satellite, on_delete=models.SET_NULL, null=True, blank=True, related_name='pm_plans', verbose_name='关联SAT')
    zones = models.ManyToManyField(Zone, blank=True, related_name='pm_plans', verbose_name='关联Zone组')
    # 工单模板
    remark_template = models.CharField('工配备注模板', max_length=255, blank=True, help_text='生成工单时填入备注')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['pm_number']
        verbose_name = 'PM维护计划'
        verbose_name_plural = 'PM维护计划'

    def __str__(self):
        return f'{self.pm_number} ({self.job_plan.name})'


class GeneratedWorkOrder(models.Model):
    """PM 派发记录 — 防重复生成 + 审计。

    每次派发命令为一条 PM + 一个到期日创建一条记录。
    同一 plan + scheduled_date 只允许一条（防重复）。
    """

    STATUS_CHOICES = [
        ('pending', '待执行'),
        ('dispatched', '已派发'),
        ('completed', '已完成'),
        ('overdue', '逾期'),
        ('skipped', '跳过'),
    ]

    plan = models.ForeignKey(MaintenancePlan, on_delete=models.CASCADE, related_name='generated_orders')
    work_report = models.OneToOneField(
        WorkReport, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pm_generation', verbose_name='生成的工单',
    )
    # Snapshot of plan.crew at dispatch time so a worker's "today's PM tasks"
    # query can match against GeneratedWorkOrder.crew (entire crew visible)
    # without joining back through plan → crew.
    crew = models.ForeignKey(
        Crew, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='generated_orders', verbose_name='派发班组',
    )
    scheduled_date = models.DateField('计划执行日期')
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='dispatched')
    generated_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField('完成时间', null=True, blank=True)

    class Meta:
        unique_together = ('plan', 'scheduled_date')
        ordering = ['-scheduled_date']
        verbose_name = 'PM派发记录'
        verbose_name_plural = 'PM派发记录'

    def __str__(self):
        return f'{self.plan.pm_number} → {self.scheduled_date}'


class ExtensionRequest(models.Model):
    """PM 工单延期申请 — 一线提交，经理审批。

    批准后：旧 GWO 标 skipped，plan.start_date 更新为 requested_date，
    下次 cron 派发按新日期算到期日。
    """
    REQ_STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已批准'),
        ('rejected', '已拒绝'),
    ]
    gwo = models.ForeignKey(
        GeneratedWorkOrder, on_delete=models.CASCADE,
        related_name='extension_requests', verbose_name='关联工单',
    )
    requester = models.ForeignKey(
        Worker, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pm_extension_requests', verbose_name='申请人',
    )
    reason = models.TextField('延期理由')
    requested_date = models.DateField('期望延期到')
    status = models.CharField('审批状态', max_length=20, choices=REQ_STATUS_CHOICES, default='pending')
    reviewed_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_pm_extensions', verbose_name='审批人',
    )
    reviewed_at = models.DateTimeField('审批时间', null=True, blank=True)
    review_note = models.TextField('审批备注', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '延期申请'
        verbose_name_plural = '延期申请'

    def __str__(self):
        return f'{self.gwo.plan.pm_number} → {self.requested_date} ({self.status})'
