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
    (ROLE_FIELD_WORKER, '现场工作人员'),
    (ROLE_DEPT_USER, '部门用户'),
]


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

    name = models.CharField(max_length=255, unique=True)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    boundary_points = models.JSONField(default=list)
    boundary_color = models.CharField(max_length=7, default='#52B788', help_text='边界颜色 (十六进制)')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def status(self):
        """Property to get today's status for template compatibility."""
        return self.get_today_status()

    def get_today_status(self, target_date=None):
        """根据当天工单获取状态。状态只代表当天，工作是周而复始的。"""
        if target_date is None:
            target_date = date.today()

        # 检查当天的维护维修请求
        maintenance = self.maintenancerequest.filter(date=target_date).first()
        if maintenance:
            return self._map_request_status(maintenance.status)

        # 检查当天的项目支持请求
        project_support = self.projectsupportrequest.filter(date=target_date).first()
        if project_support:
            return self._map_request_status(project_support.status)

        # 检查当天的浇水协调请求（按日期范围）
        water = self.waterrequest.filter(
            start_datetime__date__lte=target_date,
            end_datetime__date__gte=target_date
        ).first()
        if water:
            return self._map_request_status(water.status)

        # 当天无工单，返回未安排
        return self.STATUS_UNARRANGED

    def _map_request_status(self, request_status):
        """将请求状态映射到zone状态。"""
        mapping = {
            'submitted': self.STATUS_IN_PROGRESS,  # 已提交 → 处理中
            'approved': self.STATUS_COMPLETED,     # 已批准 → 已完成
            'rejected': self.STATUS_CANCELED,      # 已拒绝 → 已取消
            'info_needed': self.STATUS_DELAYED,    # 需补充信息 → 已延期
        }
        return mapping.get(request_status, self.STATUS_UNARRANGED)

    def get_status_display(self, target_date=None):
        """获取状态的中文显示。"""
        status = self.get_today_status(target_date)
        for code, display in self.STATUS_CHOICES:
            if code == status:
                return display
        return '未安排'

    def __str__(self):
        return f"{self.name} ({self.code})"


class Plant(models.Model):
    """Represents plants in a zone."""

    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='plants')
    name = models.CharField(max_length=255)
    scientific_name = models.CharField(max_length=255, blank=True)
    quantity = models.IntegerField(default=1)
    notes = models.TextField(blank=True)

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

    active = models.BooleanField(default=True)
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
            51: '小毛毛雨', 53: '中毛毛雨', 55: '大毛毛雨',
            61: '小雨', 63: '中雨', 65: '大雨',
            71: '小雪', 73: '中雪', 75: '大雪',
            80: '小阵雨', 81: '中阵雨', 82: '大阵雨',
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
