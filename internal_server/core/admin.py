from django.contrib import admin
from django.utils import timezone
from .models import Zone, Plant, Worker, WorkOrder, Event, WorkLog, WeatherData, MaintenanceRequest, ProjectSupportRequest, WaterRequest, RegistrationRequest


@admin.register(RegistrationRequest)
class RegistrationRequestAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'department_display', 'status', 'created_at', 'processed_at')
    list_filter = ('status', 'department', 'created_at')
    search_fields = ('full_name', 'phone')
    readonly_fields = ('created_at', 'processed_at', 'processed_by')
    actions = ['approve_requests', 'reject_requests']

    def department_display(self, obj):
        if obj.department == '其他' and obj.department_other:
            return obj.department_other
        return obj.get_department_display()
    department_display.short_description = '部门'

    def approve_requests(self, request, queryset):
        for reg in queryset.filter(status='pending'):
            # Generate employee ID
            last_worker = Worker.objects.order_by('-id').first()
            next_num = (int(last_worker.employee_id.replace('EMP', '')) + 1) if last_worker else 1
            employee_id = f'EMP{next_num:03d}'

            # Create Worker
            worker = Worker.objects.create(
                employee_id=employee_id,
                full_name=reg.full_name,
                phone=reg.phone,
                department=reg.department,
                department_other=reg.department_other,
                active=True
            )

            # Update registration request
            reg.status = 'approved'
            reg.processed_at = timezone.now()
            reg.processed_by = request.user.worker_profile if hasattr(request.user, 'worker_profile') else None
            reg.created_worker = worker
            reg.save()
    approve_requests.short_description = '批准选中的注册申请'

    def reject_requests(self, request, queryset):
        queryset.filter(status='pending').update(
            status='rejected',
            processed_at=timezone.now(),
            processed_by=request.user.worker_profile if hasattr(request.user, 'worker_profile') else None
        )
    reject_requests.short_description = '拒绝选中的注册申请'


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'boundary_color', 'point_count', 'today_status', 'created_at')
    list_filter = ('created_at',)
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
    list_display = ('name', 'scientific_name', 'zone', 'quantity')
    list_filter = ('zone',)
    search_fields = ('name', 'scientific_name', 'notes')
    readonly_fields = ()


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'employee_id', 'phone', 'department_display', 'active', 'created_at')
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
    list_display = ('title', 'zone', 'assigned_to', 'status', 'priority', 'scheduled_date', 'due_date')
    list_filter = ('status', 'priority', 'scheduled_date', 'due_date')
    search_fields = ('title', 'description')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_date', 'end_date', 'created_at')
    list_filter = ('start_date', 'end_date')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at',)
    filter_horizontal = ('affects_zones',)


@admin.register(WorkLog)
class WorkLogAdmin(admin.ModelAdmin):
    list_display = ('work_type', 'worker', 'zone', 'work_order', 'work_timestamp', 'uploaded_at')
    list_filter = ('work_type', 'work_timestamp', 'uploaded_at')
    search_fields = ('notes', 'relay_id')
    readonly_fields = ('uploaded_at',)


@admin.register(MaintenanceRequest)
class MaintenanceRequestAdmin(admin.ModelAdmin):
    list_display = ('zone', 'submitter', 'date', 'status', 'start_time', 'end_time', 'created_at')
    list_filter = ('status', 'date', 'created_at')
    search_fields = ('zone__name', 'submitter__full_name', 'work_content')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ProjectSupportRequest)
class ProjectSupportRequestAdmin(admin.ModelAdmin):
    list_display = ('zone', 'submitter', 'date', 'status', 'start_time', 'end_time', 'created_at')
    list_filter = ('status', 'date', 'created_at')
    search_fields = ('zone__name', 'submitter__full_name', 'work_content')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(WaterRequest)
class WaterRequestAdmin(admin.ModelAdmin):
    list_display = ('zone', 'submitter', 'user_type', 'request_type', 'status', 'start_datetime', 'end_datetime', 'created_at')
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
