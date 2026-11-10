"""Neutral identities and explicit team grants; legacy geometry stays authoritative."""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class BusinessArea(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Team(models.Model):
    business = models.ForeignKey(BusinessArea, on_delete=models.PROTECT, related_name='teams')
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)
    legacy_irrigation_access = models.BooleanField(default=False)
    work_catalog = models.ForeignKey('ReferenceCatalog', null=True, blank=True,
        on_delete=models.PROTECT, related_name='+')

    def __str__(self):
        return self.name


class Membership(models.Model):
    ROLES = [('field', '一线人员'), ('manager', '团队经理'), ('viewer', '只读成员'), ('requester', '需求提交人')]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='team_memberships')
    team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name='memberships')
    role = models.CharField(max_length=20, choices=ROLES, default='field')
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'team'], name='ops_one_membership_per_team')]


class Location(models.Model):
    KINDS = [('zone', '室外区域'), ('building', '建筑'), ('floor', '楼层'), ('room', '房间'),
             ('monitoring', '监测点'), ('other', '其他地点')]
    MAP_DISPLAYS = [('auto', '自动（边界优先，无边界用图钉）'), ('pin', '图钉标注（无需精确边界）')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name='owned_locations')
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=100, blank=True)
    kind = models.CharField(max_length=20, choices=KINDS, default='zone')
    map_display = models.CharField(max_length=12, choices=MAP_DISPLAYS, default='auto')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='children')
    description = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=7, null=True, blank=True)
    legacy_zone = models.OneToOneField('core.Zone', on_delete=models.PROTECT, null=True, blank=True,
                                     related_name='shared_location')
    registry_generated = models.BooleanField(default=False,db_default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'id']
        constraints = [models.UniqueConstraint(fields=['owner_team', 'code'], condition=~Q(code=''),
                                              name='ops_location_code_in_team')]

    def clean(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError('纬度和经度需要同时填写。')
        if self.latitude is not None and not -90 <= self.latitude <= 90:
            raise ValidationError('纬度应在 -90 到 90 之间。')
        if self.longitude is not None and not -180 <= self.longitude <= 180:
            raise ValidationError('经度应在 -180 到 180 之间。')
        if self.parent_id:
            ancestor = self.parent
            visited = {self.pk}
            while ancestor:
                if ancestor.pk in visited:
                    raise ValidationError('地点层级不能形成循环。')
                visited.add(ancestor.pk)
                ancestor = ancestor.parent

    @property
    def boundary(self):
        return self.legacy_zone.active_boundary_points if self.legacy_zone_id else []

    @property
    def boundary_source(self):
        if self.legacy_zone_id:
            z = self.legacy_zone
            if z.boundary_source == 'dxf' and z.dxf_boundary_points:
                return 'DXF 导入'
            if z.boundary_points:
                return '手动绘制'
        return '定位点' if self.latitude is not None else '未设置边界'


class LocationGrant(models.Model):
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='grants')
    team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name='location_grants')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['location', 'team'], name='ops_location_team_grant')]


class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    team = models.ForeignKey(Team, on_delete=models.PROTECT)
    action = models.CharField(max_length=60)
    object_ref = models.CharField(max_length=100)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def action_label(self):
        return {
            'workspace.switch':'切换业务视图','membership.save':'保存团队成员','membership.disable':'停用团队身份',
            'location.save':'保存地点','location.link_irrigation':'引入灌溉区域','location.grant':'共享地点',
            'location.revoke':'取消地点共享','location.batch_create':'批量创建地点','location.batch_grant':'批量共享地点',
            'location.batch_revoke':'批量取消共享','catalog.add':'新增工作条目','catalog.edit':'编辑工作条目',
            'location.team_visibility.add':'加入本团队区域','location.team_visibility.remove':'移出本团队区域',
            'catalog.delete':'删除工作条目','catalog.activate':'切换目录版本','pest.plan.save':'保存周期计划',
            'pest.plan.toggle':'调整计划启用状态','pest.plan.dispatch':'派发周期任务','pest.task.assign':'调整任务负责人员',
            'pest.task.skip':'跳过任务','pest.workorder.submit':'提交植保工单','pest.workorder.edit':'编辑植保工单',
            'pest.report.comment':'添加跟进说明','pest.report.pending':'标记待跟进','pest.report.resolve':'完成跟进',
            'pest.report.difficult':'标记疑难问题','pest.report.resolve_difficult':'解决疑难问题',
            'account.details':'更新账号资料','account.password':'更新密码',
        }.get(self.action,'更新业务记录')


class ReferenceCatalog(models.Model):
    business = models.ForeignKey(BusinessArea, on_delete=models.PROTECT)
    owner_team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name='work_catalog_versions')
    name = models.CharField(max_length=150)
    version = models.CharField(max_length=64)
    source_name = models.CharField(max_length=255)
    imported_at = models.DateTimeField(auto_now_add=True)
    # Versioned hierarchy for work-content selection; does not schedule PM automatically.

    class Meta:
        constraints = [models.UniqueConstraint(fields=['business', 'version'], name='ops_catalog_business_version')]


class ReferenceNode(models.Model):
    catalog = models.ForeignKey(ReferenceCatalog, on_delete=models.CASCADE, related_name='nodes')
    parent = models.ForeignKey('self', null=True, on_delete=models.CASCADE, related_name='children')
    label = models.CharField(max_length=255)
    kind = models.CharField(max_length=12, choices=[('node', '目录节点'), ('note', '附属步骤')])
    source_line = models.PositiveIntegerField()
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ['order']
        constraints = [models.UniqueConstraint(fields=['catalog', 'source_line'], name='ops_catalog_source_line')]


class PestWorkData(models.Model):
    report = models.OneToOneField('core.WorkReport', on_delete=models.CASCADE, related_name='pest_data')
    catalog = models.ForeignKey(ReferenceCatalog, on_delete=models.PROTECT)
    locations = models.ManyToManyField(Location, related_name='pest_records')
    # Issued catalogue wording and place names remain stable when reference data changes.
    selections = models.JSONField(default=list)
    location_labels = models.JSONField(default=list)


class PestMaintenancePlan(models.Model):
    FREQUENCIES = [('days', '天'), ('weeks', '周'), ('months', '月'), ('years', '年')]
    team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name='pest_plans')
    name = models.CharField(max_length=150)
    catalog = models.ForeignKey(ReferenceCatalog, on_delete=models.PROTECT)
    selections = models.JSONField(default=list)
    locations = models.ManyToManyField(Location, related_name='pest_plans')
    assignees = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='pest_plans')
    frequency_value = models.PositiveSmallIntegerField(default=1)
    frequency_unit = models.CharField(max_length=12, choices=FREQUENCIES, default='months')
    anchor_date = models.DateField()
    next_cycle = models.DateField()
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'pk']


class PestTask(models.Model):
    STATUSES = [('pending', '待完成'), ('completed', '已完成'), ('skipped', '已跳过')]
    team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name='pest_tasks')
    plan = models.ForeignKey(PestMaintenancePlan, on_delete=models.PROTECT, related_name='tasks')
    title = models.CharField(max_length=150)
    catalog = models.ForeignKey(ReferenceCatalog, on_delete=models.PROTECT)
    selections = models.JSONField(default=list)
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name='pest_tasks')
    location_label = models.CharField(max_length=255)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='pest_tasks')
    cycle_start = models.DateField()
    scheduled_date = models.DateField()
    deadline = models.DateField()
    status = models.CharField(max_length=12, choices=STATUSES, default='pending')
    report = models.OneToOneField('core.WorkReport', null=True, blank=True,
        on_delete=models.PROTECT, related_name='pest_task')
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['deadline', 'scheduled_date', 'pk']
        constraints = [models.UniqueConstraint(fields=['plan', 'location', 'cycle_start'], name='ops_pest_task_cycle')]
        indexes = [models.Index(fields=['team', 'status', 'deadline'], name='ops_pest_task_queue')]
