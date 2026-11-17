"""Landscaping master records and the first maintenance workflow.

Supplier spreadsheets remain source evidence: registering a delivery never
silently imports it or certifies the quality of individual plants.
"""
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


class LandscapingSpecies(models.Model):
    CATEGORIES = [('tree', '乔木'), ('shrub', '灌木'), ('flower', '花卉'), ('herb', '草本 / 地被'),
                  ('lawn', '草坪草'), ('vine', '藤本'), ('bamboo', '竹类'), ('other', '其他')]
    IDENTIFICATIONS = [('pending', '待辨识'), ('confirmed', '已确认')]
    team = models.ForeignKey('operations.Team', on_delete=models.PROTECT, related_name='green_species')
    code = models.CharField('植物编号', max_length=100)
    name = models.CharField('中文名', max_length=150)
    scientific_name = models.CharField('拉丁学名', max_length=200, blank=True)
    family = models.CharField('科', max_length=100, blank=True)
    genus = models.CharField('属', max_length=100, blank=True)
    category = models.CharField('植物类型', max_length=20, choices=CATEGORIES, default='other')
    special = models.BooleanField('特别关注植物', default=False)
    identification = models.CharField('辨识状态', max_length=20, choices=IDENTIFICATIONS, default='pending')
    notes = models.TextField('备注', blank=True, max_length=5000)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'pk']
        constraints = [models.UniqueConstraint(fields=['team', 'code'], name='ops_green_species_code')]

    def __str__(self):
        return f'{self.name} · {self.code}'


class LandscapingAsset(models.Model):
    KINDS = [('tree', '树木'), ('shrub', '灌木区块'), ('groundcover', '地被区块'),
             ('flowerbed', '花坛'), ('lawn', '草坪')]
    RISKS = [('unassessed', '未评估'), ('low', '低'), ('medium', '中'), ('high', '高')]
    METHODS = [('unmeasured', '未测量'), ('entered', '录入坐标（待复测）'), ('rtk', 'RTK 实测'), ('survey', '其他实测')]
    team = models.ForeignKey('operations.Team', on_delete=models.PROTECT, related_name='green_assets')
    code = models.CharField('档案编号', max_length=100)
    name = models.CharField('档案名称', max_length=150)
    kind = models.CharField('档案类型', max_length=20, choices=KINDS, default='tree')
    location = models.ForeignKey('operations.Location', on_delete=models.PROTECT, null=True, blank=True, related_name='green_assets')
    species = models.ManyToManyField(LandscapingSpecies, blank=True, related_name='assets', verbose_name='植物种类')
    description = models.CharField('具体位置说明', max_length=500, blank=True)
    latitude = models.DecimalField('纬度', max_digits=10, decimal_places=7, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.DecimalField('经度', max_digits=11, decimal_places=7, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)])
    measurement_method = models.CharField('定位来源', max_length=20, choices=METHODS, default='unmeasured')
    height_m = models.DecimalField('树高（米）', max_digits=7, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    dbh_cm = models.DecimalField('胸径（厘米）', max_digits=7, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    crown_m = models.DecimalField('冠幅（米）', max_digits=7, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    area_m2 = models.DecimalField('区块面积（平方米）', max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    risk = models.CharField('人工风险分级', max_length=20, choices=RISKS, default='unassessed')
    next_care_date = models.DateField('下次养护日期', null=True, blank=True)
    notes = models.TextField('备注', blank=True, max_length=5000)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code', 'pk']
        constraints = [models.UniqueConstraint(fields=['team', 'code'], name='ops_green_asset_code')]
        indexes = [models.Index(fields=['team', 'kind'], name='ops_green_asset_kind')]

    def __str__(self):
        return f'{self.code} · {self.name}'


class LandscapingWorkOrder(models.Model):
    KINDS = [('inspection', '树木巡检'), ('risk', '风险整改'), ('pruning', '修剪'), ('planting', '种植 / 补植'),
             ('flowers', '花坛换花'), ('lawn', '草坪养护'), ('pest', '病虫害处置'), ('other', '其他养护')]
    STATUSES = [('pending', '待处理'), ('in_progress', '处理中'), ('pending_review', '待复核'),
                ('completed', '已完成'), ('cancelled', '已取消')]
    team = models.ForeignKey('operations.Team', on_delete=models.PROTECT, related_name='green_workorders')
    title = models.CharField('工单标题', max_length=150)
    kind = models.CharField('养护类型', max_length=20, choices=KINDS, default='inspection')
    location = models.ForeignKey('operations.Location', on_delete=models.PROTECT, null=True, blank=True, related_name='green_workorders')
    assets = models.ManyToManyField(LandscapingAsset, blank=True, related_name='workorders', verbose_name='关联树木 / 绿地')
    scheduled_date = models.DateField('计划日期')
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='green_workorders')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_green_workorders')
    status = models.CharField('状态', max_length=20, choices=STATUSES, default='pending')
    instructions = models.TextField('工作要求', max_length=5000)
    completion_notes = models.TextField('处理结果', blank=True, max_length=5000)
    weather = models.CharField(max_length=100, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['team', 'status', 'scheduled_date'], name='ops_green_work_queue')]

    @property
    def display_number(self):
        return f'LH-{self.pk:06d}'


class LandscapingDelivery(models.Model):
    KINDS = [('trees', '树木实测与风险资料'), ('green', '四类绿地图层'), ('species', '植物辨识数据库'),
             ('templates', '字段、词表与记录模板'), ('pest_report', '草坪病虫害探查报告'), ('monthly', '驻场月报')]
    STATUSES = [('expected', '待接收'), ('received', '待验收'), ('rework', '待整改'), ('accepted', '已验收')]
    team = models.ForeignKey('operations.Team', on_delete=models.PROTECT, related_name='green_deliveries')
    name = models.CharField('交付批次名称', max_length=150)
    supplier = models.CharField('供应商 / 团队', max_length=150)
    kind = models.CharField('交付类型', max_length=20, choices=KINDS)
    region = models.CharField('交付区域 / 范围', max_length=200)
    expected_date = models.DateField('预计交付日期', null=True, blank=True)
    record_count = models.PositiveIntegerField('申报记录数', default=0)
    status = models.CharField('台账状态', max_length=20, choices=STATUSES, default='expected')
    notes = models.TextField('材料索引、验收依据及整改说明', blank=True, max_length=5000)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-pk']
