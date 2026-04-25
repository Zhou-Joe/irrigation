from django.contrib import admin
from django.utils import timezone
from django.contrib.auth.models import User
from .models import (
    Zone, Plant, Worker, WorkOrder, Event, WorkLog, WeatherData,
    MaintenanceRequest, ProjectSupportRequest, WaterRequest,
    RegistrationRequest, ManagerProfile, DepartmentUserProfile,
    MaxicomController, MaxicomSchedule,
    MaxicomFlowZone, MaxicomWeatherStation, MaxicomWeatherLog,
    MaxicomEvent, MaxicomFlowReading, MaxicomSignalLog,
    MaxicomETCheckbook, MaxicomRuntime,
    EquipmentCatalog, ZoneEquipment,
    Pipeline, Patch,
    WorkCategory, InfoSource, FaultCategory, FaultSubType,
    WorkReport, WorkReportFault,
    DemandCategory, DemandDepartment, DemandRecord,
    SyncAgentHeartbeat,
)
from .role_utils import get_worker_profile


@admin.register(RegistrationRequest)
class RegistrationRequestAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'department_display', 'requested_role_display', 'status', 'created_at', 'processed_at')
    list_filter = ('status', 'requested_role', 'department', 'created_at')
    search_fields = ('full_name', 'phone', 'employee_id')
    readonly_fields = ('created_at', 'processed_at', 'processed_by', 'created_user', 'username')
    actions = ['approve_requests', 'reject_requests']
    fieldsets = (
        ('申请人信息', {
            'fields': ('full_name', 'phone', 'username', 'department', 'department_other', 'employee_id')
        }),
        ('角色申请', {
            'fields': ('requested_role', 'status_notes')
        }),
        ('审批状态', {
            'fields': ('status', 'processed_at', 'processed_by')
        }),
        ('创建记录', {
            'fields': ('created_user', 'created_at'),
            'classes': ('collapse',)
        }),
    )

    def department_display(self, obj):
        if obj.department == '其他' and obj.department_other:
            return obj.department_other
        return obj.get_department_display()
    department_display.short_description = '部门'

    def requested_role_display(self, obj):
        return obj.get_requested_role_display()
    requested_role_display.short_description = '申请角色'

    def approve_requests(self, request, queryset):
        from .models import ROLE_FIELD_WORKER, ROLE_MANAGER, ROLE_DEPT_USER

        for reg in queryset.filter(status='pending'):
            role = reg.requested_role

            # Use submitted username (generate employee_id for profile only)
            employee_id = f'{prefix}{next_num:03d}'
            username = reg.username

            # Create Django User with submitted credentials
            user = User.objects.create_user(
                username=username,
                password=reg.password,  # Already hashed during submission
                first_name=reg.full_name
            )

            # Create profile based on role
            if role == ROLE_MANAGER:
                profile = ManagerProfile.objects.create(
                    user=user,
                    employee_id=employee_id,
                    full_name=reg.full_name,
                    phone=reg.phone,
                    active=True
                )
            elif role == ROLE_DEPT_USER:
                profile = DepartmentUserProfile.objects.create(
                    user=user,
                    employee_id=employee_id,
                    full_name=reg.full_name,
                    phone=reg.phone,
                    department=reg.department,
                    department_other=reg.department_other,
                    active=True
                )
            else:
                profile = Worker.objects.create(
                    user=user,
                    employee_id=employee_id,
                    full_name=reg.full_name,
                    phone=reg.phone,
                    department=reg.department,
                    department_other=reg.department_other,
                    active=True
                )

            # Update registration request
            reg.status = 'approved'
            reg.employee_id = employee_id  # Store generated employee_id
            reg.processed_at = timezone.now()
            reg.processed_by = get_worker_profile(request.user)
            reg.created_user = user
            reg.save()

            self.message_user(request, f'已批准 {reg.full_name} 的注册申请，用户名：{username}，工号：{employee_id}')
    approve_requests.short_description = '批准选中的注册申请'

    def reject_requests(self, request, queryset):
        worker = get_worker_profile(request.user)
        queryset.filter(status='pending').update(
            status='rejected',
            processed_at=timezone.now(),
            processed_by=worker
        )
    reject_requests.short_description = '拒绝选中的注册申请'


# ============================================
# Maxicom2 Irrigation System Admin
# ============================================

class MaxicomControllerInline(admin.TabularInline):
    model = MaxicomController
    extra = 0
    fields = ('name', 'controller_type', 'site_number', 'link_number', 'link_channel', 'enabled')


class MaxicomScheduleInline(admin.TabularInline):
    model = MaxicomSchedule
    extra = 0
    fields = ('name', 'nominal_et', 'water_budget_factor', 'flo_manage', 'send_automatic')


@admin.register(MaxicomWeatherStation)
class MaxicomWeatherStationAdmin(admin.ModelAdmin):
    list_display = ('name', 'mdb_index', 'default_et', 'time_zone', 'id')
    search_fields = ('name',)


@admin.register(MaxicomWeatherLog)
class MaxicomWeatherLogAdmin(admin.ModelAdmin):
    list_display = ('weather_station', 'timestamp', 'temperature', 'max_temp', 'min_temp', 'humidity', 'rainfall', 'et', 'solar_radiation', 'wind_run', 'id')
    list_filter = ('weather_station', 'timestamp')
    search_fields = ('weather_station__name',)
    list_select_related = ('weather_station',)
    readonly_fields = ()
    ordering = ('-timestamp',)


@admin.register(MaxicomEvent)
class MaxicomEventAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'source', 'index', 'event_number', 'flag', 'text_truncated')
    list_filter = ('flag', 'source', 'timestamp')
    search_fields = ('text',)
    ordering = ('-timestamp',)
    readonly_fields = ()

    def text_truncated(self, obj):
        return obj.text[:100] + '...' if len(obj.text) > 100 else obj.text
    text_truncated.short_description = '事件内容'


@admin.register(MaxicomFlowReading)
class MaxicomFlowReadingAdmin(admin.ModelAdmin):
    list_display = ('flow_zone', 'timestamp', 'value', 'multiplier', 'site_id', 'id')
    list_filter = ('flow_zone', 'timestamp')
    list_select_related = ('flow_zone',)
    ordering = ('-timestamp',)


@admin.register(MaxicomSignalLog)
class MaxicomSignalLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'index', 'controller_channel', 'signal_index', 'signal_table', 'signal_type', 'signal_value', 'signal_multiplier', 'id')
    list_filter = ('signal_type', 'signal_table', 'timestamp')
    ordering = ('-timestamp',)


@admin.register(MaxicomETCheckbook)
class MaxicomETCheckbookAdmin(admin.ModelAdmin):
    list_display = ('site', 'timestamp', 'soil_moisture', 'rainfall', 'et', 'irrigation', 'soil_moisture_capacity', 'soil_refill_pct', 'id')
    list_filter = ('site', 'timestamp')
    search_fields = ('site__name',)
    list_select_related = ('site',)
    ordering = ('-timestamp',)


@admin.register(MaxicomRuntime)
class MaxicomRuntimeAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'site', 'station', 'station_id_raw', 'run_time', 'id')
    list_filter = ('site', 'timestamp')
    search_fields = ('site__name',)
    list_select_related = ('site', 'station')
    ordering = ('-timestamp',)


@admin.register(Patch)
class PatchAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'type', 'parent', 'mdb_index', 'order', 'active', 'created_at')
    list_filter = ('type', 'active', 'parent')
    search_fields = ('name', 'code', 'description')
    readonly_fields = ('created_at', 'updated_at')
    list_editable = ('order', 'active')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('parent')


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'patch', 'description', 'boundary_color', 'point_count', 'today_status', 'created_at', 'updated_at')
    list_filter = ('patch', 'created_at')
    search_fields = ('name', 'code', 'description')
    readonly_fields = ('created_at', 'updated_at', 'display_boundary_points', 'today_status_display')

    def point_count(self, obj):
        return len(obj.boundary_points) if obj.boundary_points else 0
    point_count.short_description = '坐标点数'

    def today_status(self, obj):
        return obj.get_status_display()
    today_status.short_description = '当天状态'

    def today_status_display(self, obj):
        from django.utils.html import format_html
        status = obj.get_today_status()
        display = obj.get_status_display()
        colors = {
            'unarranged': '#888888',
            'in_progress': '#CC7722',
            'completed': '#40916C',
            'canceled': '#9B2226',
            'delayed': '#7B5544',
        }
        color = colors.get(status, '#52B788')
        return format_html(
            '<span style="background: {}20; color: {}; padding: 4px 8px; border-radius: 12px;">{}</span>',
            color, color, display
        )
    today_status_display.short_description = '当天状态'

    def display_boundary_points(self, obj):
        if not obj.boundary_points:
            return '无坐标点'
        points = obj.boundary_points
        html = '<table style="border-collapse: collapse;"><thead><tr><th style="border: 1px solid #ddd; padding: 8px;">序号</th><th style="border: 1px solid #ddd; padding: 8px;">纬度</th><th style="border: 1px solid #ddd; padding: 8px;">经度</th></tr></thead><tbody>'
        for i, p in enumerate(points, 1):
            if isinstance(p, dict):
                lat = p.get('lat', '-')
                lng = p.get('lng', '-')
            else:
                lat, lng = p[0] if len(p) > 0 else '-', p[1] if len(p) > 1 else '-'
            html += f'<tr><td style="border: 1px solid #ddd; padding: 8px;">{i}</td><td style="border: 1px solid #ddd; padding: 8px;">{lat}</td><td style="border: 1px solid #ddd; padding: 8px;">{lng}</td></tr>'
        html += '</tbody></table>'
        from django.utils.safestring import mark_safe
        return mark_safe(html)
    display_boundary_points.short_description = '边界坐标点'


@admin.register(Plant)
class PlantAdmin(admin.ModelAdmin):
    list_display = ('name', 'scientific_name', 'zone', 'quantity', 'planting_date', 'end_date', 'notes')
    list_filter = ('zone',)
    search_fields = ('name', 'scientific_name', 'notes')
    readonly_fields = ()


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'employee_id', 'phone', 'department_display', 'department_other', 'api_token', 'active', 'created_at', 'updated_at')
    list_filter = ('active', 'department', 'created_at')
    search_fields = ('full_name', 'employee_id', 'phone')
    readonly_fields = ('created_at', 'updated_at')

    def department_display(self, obj):
        if obj.department == '其他' and obj.department_other:
            return obj.department_other
        return obj.get_department_display()
    department_display.short_description = '部门'


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = ('title', 'zone', 'assigned_to', 'status', 'priority', 'scheduled_date', 'due_date', 'created_at', 'updated_at')
    list_filter = ('status', 'priority', 'scheduled_date', 'due_date')
    search_fields = ('title', 'description')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'start_date', 'end_date', 'created_at')
    list_filter = ('start_date', 'end_date')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at',)
    filter_horizontal = ('affects_zones',)


@admin.register(WorkLog)
class WorkLogAdmin(admin.ModelAdmin):
    list_display = ('work_type', 'worker', 'zone', 'work_order', 'notes', 'latitude', 'longitude', 'work_timestamp', 'relay_id', 'uploaded_at')
    list_filter = ('work_type', 'work_timestamp', 'uploaded_at')
    search_fields = ('notes', 'relay_id')
    readonly_fields = ('uploaded_at',)


@admin.register(MaintenanceRequest)
class MaintenanceRequestAdmin(admin.ModelAdmin):
    list_display = ('zone', 'submitter', 'date', 'status', 'start_time', 'end_time', 'participants', 'work_content', 'materials', 'feedback', 'approver', 'processed_at', 'status_notes', 'created_at', 'updated_at')
    list_filter = ('status', 'date', 'created_at')
    search_fields = ('zone__name', 'submitter__full_name', 'work_content')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ProjectSupportRequest)
class ProjectSupportRequestAdmin(admin.ModelAdmin):
    list_display = ('zone', 'submitter', 'date', 'status', 'start_time', 'end_time', 'participants', 'work_content', 'materials', 'feedback', 'approver', 'processed_at', 'status_notes', 'created_at', 'updated_at')
    list_filter = ('status', 'date', 'created_at')
    search_fields = ('zone__name', 'submitter__full_name', 'work_content')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(WaterRequest)
class WaterRequestAdmin(admin.ModelAdmin):
    list_display = ('zone', 'submitter', 'user_type', 'user_type_other', 'request_type', 'request_type_other', 'status', 'start_datetime', 'end_datetime', 'approver', 'processed_at', 'status_notes', 'created_at', 'updated_at')
    list_filter = ('status', 'user_type', 'request_type', 'created_at')
    search_fields = ('zone__name', 'submitter__full_name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(WeatherData)
class WeatherDataAdmin(admin.ModelAdmin):
    list_display = ('date', 'latitude', 'longitude', 'hour_count', 'fetched_at')
    list_filter = ('date', 'latitude', 'longitude')
    readonly_fields = ('fetched_at', 'display_hourly_data')
    ordering = ['-date']

    def hour_count(self, obj):
        return len(obj.hourly_data) if obj.hourly_data else 0
    hour_count.short_description = '小时数'

    def display_hourly_data(self, obj):
        if not obj.hourly_data:
            return '无数据'
        html = '<table style="border-collapse: collapse; font-size: 12px;"><thead><tr>'
        html += '<th style="border: 1px solid #ddd; padding: 4px;">时</th>'
        html += '<th style="border: 1px solid #ddd; padding: 4px;">温度</th>'
        html += '<th style="border: 1px solid #ddd; padding: 4px;">湿度%</th>'
        html += '<th style="border: 1px solid #ddd; padding: 4px;">降水</th>'
        html += '<th style="border: 1px solid #ddd; padding: 4px;">风速</th>'
        html += '<th style="border: 1px solid #ddd; padding: 4px;">天气</th>'
        html += '</tr></thead><tbody>'
        for h in obj.hourly_data:
            html += f'<tr>'
            html += f'<td style="border: 1px solid #ddd; padding: 4px;">{h.get("hour", "-")}</td>'
            html += f'<td style="border: 1px solid #ddd; padding: 4px;">{h.get("temp", "-")}°C</td>'
            html += f'<td style="border: 1px solid #ddd; padding: 4px;">{h.get("humidity", "-")}%</td>'
            html += f'<td style="border: 1px solid #ddd; padding: 4px;">{h.get("precip", "-")}mm</td>'
            html += f'<td style="border: 1px solid #ddd; padding: 4px;">{h.get("wind", "-")}km/h</td>'
            html += f'<td style="border: 1px solid #ddd; padding: 4px;">{obj.get_weather_description(h.get("code"))}</td>'
            html += '</tr>'
        html += '</tbody></table>'
        from django.utils.safestring import mark_safe
        return mark_safe(html)
    display_hourly_data.short_description = '逐时数据'


@admin.register(ManagerProfile)
class ManagerProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'employee_id', 'phone', 'is_super_admin', 'can_approve_registrations', 'can_approve_work_orders', 'active', 'created_at')
    list_filter = ('is_super_admin', 'can_approve_registrations', 'can_approve_work_orders', 'active', 'created_at')
    search_fields = ('full_name', 'employee_id', 'phone')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('基本信息', {
            'fields': ('user', 'employee_id', 'full_name', 'phone')
        }),
        ('权限设置', {
            'fields': ('is_super_admin', 'can_approve_registrations', 'can_approve_work_orders', 'active')
        }),
        ('时间记录', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(DepartmentUserProfile)
class DepartmentUserProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'employee_id', 'phone', 'department_display', 'active', 'created_at')
    list_filter = ('department', 'active', 'created_at')
    search_fields = ('full_name', 'employee_id', 'phone')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('基本信息', {
            'fields': ('user', 'employee_id', 'full_name', 'phone')
        }),
        ('部门信息', {
            'fields': ('department', 'department_other', 'active')
        }),
        ('时间记录', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def department_display(self, obj):
        if obj.department == '其他' and obj.department_other:
            return obj.department_other
        return obj.get_department_display()
    department_display.short_description = '部门'


@admin.register(EquipmentCatalog)
class EquipmentCatalogAdmin(admin.ModelAdmin):
    list_display = ('equipment_type', 'manufacturer', 'model_name', 'specifications', 'created_at', 'updated_at')
    list_filter = ('equipment_type', 'manufacturer')
    search_fields = ('model_name', 'manufacturer')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ZoneEquipment)
class ZoneEquipmentAdmin(admin.ModelAdmin):
    list_display = ('zone', 'equipment', 'quantity', 'status', 'installation_date', 'location_in_zone', 'notes', 'created_at', 'updated_at')
    list_filter = ('status', 'equipment__equipment_type', 'installation_date')
    search_fields = ('zone__name', 'equipment__model_name', 'location_in_zone')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Pipeline)
class PipelineAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'pipeline_type', 'line_color_display', 'point_count', 'zone_count', 'created_at')
    list_filter = ('pipeline_type', 'created_at')
    search_fields = ('name', 'code', 'description')
    readonly_fields = ('created_at', 'updated_at', 'display_line_points')
    filter_horizontal = ('zones',)

    def point_count(self, obj):
        return len(obj.line_points) if obj.line_points else 0
    point_count.short_description = '坐标点数'

    def zone_count(self, obj):
        return obj.zones.count()
    zone_count.short_description = '关联区域数'

    def line_color_display(self, obj):
        from django.utils.html import format_html
        color = obj.line_color
        return format_html(
            '<span style="background: {}; color: white; padding: 4px 8px; border-radius: 12px;">{}</span>',
            color, obj.get_pipeline_type_display()
        )
    line_color_display.short_description = '类型/颜色'

    def display_line_points(self, obj):
        if not obj.line_points:
            return '无坐标点'
        html = '<table style="border-collapse: collapse;"><thead><tr><th style="border: 1px solid #ddd; padding: 8px;">序号</th><th style="border: 1px solid #ddd; padding: 8px;">纬度</th><th style="border: 1px solid #ddd; padding: 8px;">经度</th></tr></thead><tbody>'
        for i, p in enumerate(obj.line_points, 1):
            if isinstance(p, dict):
                lat = p.get('lat', '-')
                lng = p.get('lng', '-')
            else:
                lat, lng = p[0], p[1]
            html += f'<tr><td style="border: 1px solid #ddd; padding: 8px;">{i}</td><td style="border: 1px solid #ddd; padding: 8px;">{lat}</td><td style="border: 1px solid #ddd; padding: 8px;">{lng}</td></tr>'
        html += '</tbody></table>'
        from django.utils.safestring import mark_safe
        return mark_safe(html)
    display_line_points.short_description = '管线坐标点'


# ==========================================================================
# 维修工单系统 Admin
# ==========================================================================


class FaultSubTypeInline(admin.TabularInline):
    model = FaultSubType
    extra = 0


@admin.register(WorkCategory)
class WorkCategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'order', 'active', 'created_at', 'updated_at')
    list_editable = ('order', 'active')
    search_fields = ('name', 'code')
    ordering = ('order', 'code')


@admin.register(InfoSource)
class InfoSourceAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'order', 'active', 'created_at', 'updated_at')
    list_editable = ('order', 'active')
    search_fields = ('name', 'code')
    ordering = ('order', 'code')


@admin.register(FaultCategory)
class FaultCategoryAdmin(admin.ModelAdmin):
    list_display = ('name_zh', 'name_en', 'order', 'active', 'sub_type_count', 'created_at', 'updated_at')
    list_editable = ('order', 'active')
    search_fields = ('name_zh', 'name_en')
    ordering = ('order', 'id')
    inlines = [FaultSubTypeInline]

    def sub_type_count(self, obj):
        return obj.sub_types.count()
    sub_type_count.short_description = '子类型数'


@admin.register(FaultSubType)
class FaultSubTypeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name_zh', 'name_en', 'category', 'order', 'active', 'created_at', 'updated_at')
    list_filter = ('category', 'active')
    list_editable = ('order', 'active')
    search_fields = ('name_zh', 'name_en', 'code')
    ordering = ('category__order', 'order', 'id')


class WorkReportFaultInline(admin.TabularInline):
    model = WorkReportFault
    extra = 0
    autocomplete_fields = ('fault_subtype',)
    readonly_fields = ()


@admin.register(WorkReport)
class WorkReportAdmin(admin.ModelAdmin):
    list_display = ('date', 'weather', 'worker', 'location', 'work_category', 'zone_location', 'remark', 'info_source', 'is_difficult', 'is_difficult_resolved', 'created_at', 'updated_at')
    list_filter = ('date', 'work_category', 'location', 'is_difficult', 'weather')
    search_fields = ('remark', 'zone_location', 'worker__full_name')
    date_hierarchy = 'date'
    inlines = [WorkReportFaultInline]
    raw_id_fields = ('worker',)
    ordering = ('-date', '-id')


# ==========================================================================
# 需求周报系统 Admin
# ==========================================================================


@admin.register(DemandCategory)
class DemandCategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'category_type', 'order', 'active', 'created_at', 'updated_at')
    list_filter = ('category_type', 'active')
    list_editable = ('order', 'active')
    search_fields = ('name', 'code')
    ordering = ('order', 'code')


@admin.register(DemandDepartment)
class DemandDepartmentAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'order', 'active', 'created_at')
    list_editable = ('order', 'active')
    search_fields = ('name', 'code')
    ordering = ('order', 'code')


@admin.register(DemandRecord)
class DemandRecordAdmin(admin.ModelAdmin):
    list_display = ('date', 'zone_text', 'category_text', 'content_preview', 'time_display', 'status', 'is_global_event')
    list_filter = ('date', 'category', 'status', 'is_global_event', 'time_parsed', 'zone')
    search_fields = ('content', 'original_text', 'zone_text', 'category_text', 'demand_contact')
    date_hierarchy = 'date'
    readonly_fields = ('created_at', 'updated_at', 'time_parsed', 'crosses_midnight')
    raw_id_fields = ('zone', 'submitter', 'approver', 'work_order')
    filter_horizontal = ('affected_zones',)
    ordering = ('-date', '-id')

    fieldsets = (
        ('基本信息', {
            'fields': ('date', 'content', 'original_text', 'status')
        }),
        ('区域信息', {
            'fields': ('zone', 'zone_text', 'is_global_event', 'affected_zones')
        }),
        ('类别信息', {
            'fields': ('category', 'category_text')
        }),
        ('时间段', {
            'fields': ('start_time', 'end_time', 'time_parsed', 'crosses_midnight')
        }),
        ('需求方信息', {
            'fields': ('demand_department', 'demand_department_text', 'demand_contact')
        }),
        ('审批流程', {
            'fields': ('submitter', 'approver', 'processed_at', 'status_notes')
        }),
        ('关联工单', {
            'fields': ('work_order',)
        }),
        ('时间记录', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_preview.short_description = '内容'

    def time_display(self, obj):
        if obj.start_time and obj.end_time:
            return f"{obj.start_time.strftime('%H:%M')} - {obj.end_time.strftime('%H:%M')}"
        return '-'
    time_display.short_description = '时间段'


# ==========================================================================
# 同步代理 Admin
# ==========================================================================


@admin.register(SyncAgentHeartbeat)
class SyncAgentHeartbeatAdmin(admin.ModelAdmin):
    list_display = ('id', 'last_heartbeat', 'agent_version', 'last_sync_counts')
    readonly_fields = ('last_heartbeat', 'last_sync_counts', 'agent_version')
