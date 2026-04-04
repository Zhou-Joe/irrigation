from django.contrib import admin
from .models import Zone, Plant, Worker, WorkOrder, Event, WorkLog


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'status', 'scheduled_start', 'scheduled_end', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('name', 'code', 'description')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Plant)
class PlantAdmin(admin.ModelAdmin):
    list_display = ('name', 'scientific_name', 'zone', 'quantity')
    list_filter = ('zone',)
    search_fields = ('name', 'scientific_name', 'notes')
    readonly_fields = ()


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'employee_id', 'phone', 'active', 'created_at')
    list_filter = ('active', 'created_at')
    search_fields = ('full_name', 'employee_id', 'phone')
    readonly_fields = ('created_at', 'updated_at')


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
