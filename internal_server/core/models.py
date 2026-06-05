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
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    boundary_points = models.JSONField(default=list)
    boundary_color = models.CharField(max_length=7, default='#52B788', help_text='边界颜色 (十六进制)')
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

    def save(self, *args, **kwargs):
        self._recalc_area()
        super().save(*args, **kwargs)

    def _recalc_area(self):
        import math
        pts = self.boundary_points
        if not pts:
            self.area_sqm = None
            return

        def to_latlng(p):
            if isinstance(p, dict):
                return p.get('lat', p.get('latitude', 0)), p.get('lng', p.get('longitude', 0))
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                return p[0], p[1]
            return 0, 0

        # Normalize to list of point-lists (multi-polygon support)
        first = pts[0]
        if isinstance(first, list) and len(first) > 0 and (isinstance(first[0], (list, dict))):
            rings = pts
        elif isinstance(first, (dict, list)):
            rings = [pts]
        else:
            self.area_sqm = None
            return

        total = 0.0
        for ring in rings:
            if len(ring) < 3:
                continue
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
            total += abs(area) / 2.0
        self.area_sqm = total if total > 0 else None

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


class WorkOrder(models.Model):
    """Represents a work order assigned to a zone."""

    STATUS_PENDING = 'pending'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELED = 'canceled'

    STATUS_CHOICES = [
        (STATUS_PENDING, '待处理'),
        (STATUS_IN_PROGRESS, '进行中'),
        (STATUS_COMPLETED, '已完成'),
        (STATUS_CANCELED, '已取消'),
    ]

    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='work_orders')
    assigned_to = models.ForeignKey(Worker, on_delete=models.SET_NULL, null=True, blank=True, related_name='work_orders')
    title = models.CharField(max_length=255)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    priority = models.IntegerField(default=0)
    scheduled_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.zone.name})"


class Event(models.Model):
    """Represents an event that may affect zones."""

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    affects_zones = models.ManyToManyField(Zone, related_name='events')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.start_date} to {self.end_date})"


class WorkLog(models.Model):
    """Represents a work log entry from a worker."""

    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='work_logs')
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name='work_logs')
    work_order = models.ForeignKey(WorkOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name='work_logs')
    work_type = models.CharField(max_length=100)
    notes = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    work_timestamp = models.DateTimeField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    relay_id = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return f"{self.work_type} by {self.worker.full_name} at {self.zone.name} ({self.work_timestamp})"


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

    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='%(class)s')
    submitter = models.ForeignKey(Worker, on_delete=models.CASCADE)
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


class MaintenanceRequest(RequestBase):
    """维护与维修 request."""

    submitter = models.ForeignKey(
        Worker, on_delete=models.CASCADE, related_name='maintenance_requests'
    )

    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    participants = models.CharField(max_length=255, help_text='参与人员，逗号分隔')
    work_content = models.TextField(help_text='工作内容')
    materials = models.TextField(blank=True, help_text='材料损耗')
    feedback = models.TextField(blank=True, help_text='问题反馈')
    photos = models.JSONField(default=list, help_text='照片URL列表')

    class Meta:
        db_table = 'maintenance_requests'

    def __str__(self):
        return f"维护维修 - {self.zone.name} ({self.date})"


class ProjectSupportRequest(RequestBase):
    """项目支持 request."""

    submitter = models.ForeignKey(
        Worker, on_delete=models.CASCADE, related_name='project_support_requests'
    )

    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    participants = models.CharField(max_length=255, help_text='参与人员，逗号分隔')
    work_content = models.TextField(help_text='工作内容')
    materials = models.TextField(blank=True, help_text='材料损耗')
    feedback = models.TextField(blank=True, help_text='问题反馈')
    photos = models.JSONField(default=list, help_text='照片URL列表')

    class Meta:
        db_table = 'project_support_requests'

    def __str__(self):
        return f"项目支持 - {self.zone.name} ({self.date})"


class WaterRequest(RequestBase):
    """浇水协调需求 request."""

    submitter = models.ForeignKey(
        Worker, on_delete=models.CASCADE, related_name='water_requests'
    )

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

    class Meta:
        db_table = 'water_requests'

    def __str__(self):
        return f"浇水协调 - {self.zone.name} ({self.request_type})"


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



class WorkCategory(models.Model):
    """工作分类 - type of work performed."""

    name = models.CharField('名称', max_length=100)
    code = models.CharField('编号', max_length=50, unique=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='children', verbose_name='父级分类')
    order = models.PositiveIntegerField('排序', default=0)
    active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'code']
        verbose_name = '工作分类'
        verbose_name_plural = '工作分类'

    def __str__(self):
        return self.name


class InfoSource(models.Model):
    """信息来源 - how the issue was reported."""

    name = models.CharField('名称', max_length=100)
    code = models.CharField('编号', max_length=50, unique=True)
    order = models.PositiveIntegerField('排序', default=0)
    active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'code']
        verbose_name = '信息来源'
        verbose_name_plural = '信息来源'

    def __str__(self):
        return self.name


class FaultCategory(models.Model):
    """故障大类 - top-level fault classification."""

    name_zh = models.CharField('中文名称', max_length=200)
    name_en = models.CharField('英文名称', max_length=200, blank=True)
    order = models.PositiveIntegerField('排序', default=0)
    active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'id']
        verbose_name = '故障大类'
        verbose_name_plural = '故障大类'

    def __str__(self):
        return self.name_zh


class FaultSubType(models.Model):
    """故障子类型 - specific fault type under a category."""

    category = models.ForeignKey(FaultCategory, on_delete=models.CASCADE, related_name='sub_types', verbose_name='所属大类')
    name_zh = models.CharField('中文名称', max_length=200)
    name_en = models.CharField('英文名称', max_length=200, blank=True)
    code = models.CharField('编号', max_length=50, unique=True)
    order = models.PositiveIntegerField('排序', default=0)
    active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category__order', 'category__id', 'order', 'id']
        verbose_name = '故障子类型'
        verbose_name_plural = '故障子类型'

    def __str__(self):
        return f"{self.category.name_zh} → {self.name_zh}"


class WorkReport(models.Model):
    """维修工作日报 - daily maintenance work record."""

    SHIFT_CHOICES = [
        ('早班', '早班'),
        ('白班', '白班'),
        ('夜班', '夜班'),
    ]

    date = models.DateField('日期')
    weather = models.CharField('天气', max_length=50, blank=True)
    worker = models.ForeignKey(Worker, on_delete=models.PROTECT, related_name='work_reports', verbose_name='处理人')
    location = models.ForeignKey(Patch, on_delete=models.PROTECT, related_name='work_reports', verbose_name='位置/CCU')
    work_category = models.ForeignKey(WorkCategory, on_delete=models.PROTECT, related_name='work_reports', verbose_name='工作分类')
    zone_location = models.ForeignKey(Zone, on_delete=models.SET_NULL, null=True, blank=True, related_name='work_reports', verbose_name='故障/事件位置')
    remark = models.TextField('备注/工作内容', blank=True)
    info_source = models.ForeignKey(InfoSource, on_delete=models.SET_NULL, null=True, blank=True, related_name='work_reports', verbose_name='信息来源')
    is_difficult = models.BooleanField('疑难问题', default=False)
    is_difficult_resolved = models.BooleanField('疑难问题已处理', default=False)
    fault_subtypes = models.ManyToManyField(FaultSubType, through='WorkReportFault', blank=True, related_name='work_reports')
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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-id']
        verbose_name = '维修工作日报'
        verbose_name_plural = '维修工作日报'

    def __str__(self):
        return f"{self.date} | {self.worker} | {self.location}"


class WorkReportFault(models.Model):
    """故障计数 - how many of each fault subtype in a work report."""

    work_report = models.ForeignKey(WorkReport, on_delete=models.CASCADE, related_name='fault_entries')
    fault_subtype = models.ForeignKey(FaultSubType, on_delete=models.PROTECT, related_name='report_entries')
    count = models.PositiveIntegerField('数量', default=0)
    equipment = models.ForeignKey(
        ZoneEquipment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fault_entries',
        verbose_name='故障设备'
    )

    class Meta:
        unique_together = ('work_report', 'fault_subtype')
        verbose_name = '故障计数'
        verbose_name_plural = '故障计数'

    def __str__(self):
        return f"{self.work_report} → {self.fault_subtype.name_zh}: {self.count}"


# ==========================================================================
# 需求周报系统 (Demand Record System - Other departments' requests)
# ==========================================================================


class DemandCategory(models.Model):
    """需求类别 - 区别于工单的WorkCategory"""

    CATEGORY_TYPE_CHOICES = [
        ('global_event', '全局事件'),
        ('zone_demand', '区域需求'),
        ('work_category', '工作类别'),
    ]

    name = models.CharField('名称', max_length=100)
    code = models.CharField('编号', max_length=50, unique=True)
    category_type = models.CharField('类别类型', max_length=20, choices=CATEGORY_TYPE_CHOICES)
    order = models.PositiveIntegerField('排序', default=0)
    active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'code']
        verbose_name = '需求类别'
        verbose_name_plural = '需求类别'

    def __str__(self):
        return f"{self.name} ({self.category_type})"


class DemandDepartment(models.Model):
    """提出需求的部门"""

    name = models.CharField('部门名称', max_length=50)
    code = models.CharField('部门编号', max_length=20, unique=True)
    order = models.PositiveIntegerField('排序', default=0)
    active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'code']
        verbose_name = '需求部门'
        verbose_name_plural = '需求部门'

    def __str__(self):
        return self.name


class DemandRecord(models.Model):
    """需求记录 - 其他部门提出的灌溉相关需求"""

    STATUS_SUBMITTED = 'submitted'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_COMPLETED = 'completed'
    STATUS_INFO_NEEDED = 'info_needed'

    STATUS_CHOICES = [
        (STATUS_SUBMITTED, '已提交'),
        (STATUS_APPROVED, '已批准'),
        (STATUS_REJECTED, '已拒绝'),
        (STATUS_IN_PROGRESS, '进行中'),
        (STATUS_COMPLETED, '已完成'),
        (STATUS_INFO_NEEDED, '需补充信息'),
    ]

    # 基本信息
    date = models.DateField('需求日期', db_index=True)
    content = models.TextField('需求内容/备注')
    original_text = models.TextField('原始文本', blank=True, help_text='Excel原始单元格内容')

    # 需求方信息
    demand_department = models.ForeignKey(
        DemandDepartment, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='demand_records',
        verbose_name='提出部门'
    )
    demand_department_text = models.CharField('提出部门(文本)', max_length=50, blank=True)
    demand_contact = models.CharField('联系人', max_length=100, blank=True)

    # 区域信息
    zone = models.ForeignKey(
        Zone, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='demand_records',
        verbose_name='关联区域'
    )
    zone_text = models.CharField('区域(文本)', max_length=100, blank=True, null=True, help_text='Excel行标签')

    # 全局事件标记
    is_global_event = models.BooleanField('全局事件', default=False)
    affected_zones = models.ManyToManyField(
        Zone, blank=True, related_name='affected_by_demands',
        verbose_name='影响区域'
    )

    # 类别信息
    category = models.ForeignKey(
        DemandCategory, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='demand_records',
        verbose_name='需求类别'
    )
    category_text = models.CharField('类别(文本)', max_length=100, blank=True, null=True)

    # 时间段（解析后的结构化数据）
    start_time = models.TimeField('开始时间', null=True, blank=True)
    end_time = models.TimeField('结束时间', null=True, blank=True)
    crosses_midnight = models.BooleanField('跨天', default=False, help_text='结束时间是否跨过午夜')
    time_parsed = models.BooleanField('时间已解析', default=False)

    # 审批流程
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default=STATUS_APPROVED)
    submitter = models.ForeignKey(
        Worker, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='submitted_demands',
        verbose_name='提交人'
    )
    approver = models.ForeignKey(
        Worker, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='approved_demands',
        verbose_name='审批人'
    )
    processed_at = models.DateTimeField('处理时间', null=True, blank=True)
    status_notes = models.TextField('审批备注', blank=True)

    # 关联工单
    work_order = models.ForeignKey(
        WorkOrder, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='linked_demand',
        verbose_name='关联工单'
    )

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-id']
        indexes = [
            models.Index(fields=['date', 'zone']),
            models.Index(fields=['date', 'category']),
        ]
        verbose_name = '需求记录'
        verbose_name_plural = '需求记录'

    def __str__(self):
        return f"{self.date} | {self.zone_text or '全局'} | {self.content[:30]}"


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
