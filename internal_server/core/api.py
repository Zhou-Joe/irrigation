from rest_framework import serializers, viewsets, permissions
from .models import Zone, Plant, Worker, WorkOrder, Event, WorkLog


# Serializers
class ZoneSerializer(serializers.ModelSerializer):
    """Serializer for Zone model."""

    class Meta:
        model = Zone
        fields = [
            'id', 'name', 'code', 'description', 'boundary_points',
            'status', 'status_reason', 'scheduled_start', 'scheduled_end',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


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


# ViewSets
class ZoneViewSet(viewsets.ModelViewSet):
    """ViewSet for Zone CRUD operations."""

    queryset = Zone.objects.all()
    serializer_class = ZoneSerializer
    permission_classes = [permissions.IsAuthenticated]


class PlantViewSet(viewsets.ModelViewSet):
    """ViewSet for Plant CRUD operations."""

    queryset = Plant.objects.all()
    serializer_class = PlantSerializer
    permission_classes = [permissions.IsAuthenticated]


class WorkerViewSet(viewsets.ModelViewSet):
    """ViewSet for Worker CRUD operations."""

    queryset = Worker.objects.all()
    serializer_class = WorkerSerializer
    permission_classes = [permissions.IsAuthenticated]


class WorkOrderViewSet(viewsets.ModelViewSet):
    """ViewSet for WorkOrder CRUD operations."""

    queryset = WorkOrder.objects.all()
    serializer_class = WorkOrderSerializer
    permission_classes = [permissions.IsAuthenticated]


class EventViewSet(viewsets.ModelViewSet):
    """ViewSet for Event CRUD operations."""

    queryset = Event.objects.all()
    serializer_class = EventSerializer
    permission_classes = [permissions.IsAuthenticated]


class WorkLogViewSet(viewsets.ModelViewSet):
    """ViewSet for WorkLog CRUD operations."""

    queryset = WorkLog.objects.all()
    serializer_class = WorkLogSerializer
    permission_classes = [permissions.IsAuthenticated]
