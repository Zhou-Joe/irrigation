from django.db import models
from django.contrib.auth.models import User


class Zone(models.Model):
    """Represents a work zone with boundary points and status tracking."""

    STATUS_SCHEDULED = 'scheduled'
    STATUS_WORKING = 'working'
    STATUS_DONE = 'done'
    STATUS_CANCELED = 'canceled'
    STATUS_DELAYED = 'delayed'

    STATUS_CHOICES = [
        (STATUS_SCHEDULED, 'Scheduled'),
        (STATUS_WORKING, 'Working'),
        (STATUS_DONE, 'Done'),
        (STATUS_CANCELED, 'Canceled'),
        (STATUS_DELAYED, 'Delayed'),
    ]

    name = models.CharField(max_length=255, unique=True)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    boundary_points = models.JSONField(default=list)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SCHEDULED)
    status_reason = models.CharField(max_length=255, blank=True)
    scheduled_start = models.DateTimeField(null=True, blank=True)
    scheduled_end = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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

    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='worker_profile')
    employee_id = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.full_name} ({self.employee_id})"


class WorkOrder(models.Model):
    """Represents a work order assigned to a zone."""

    STATUS_PENDING = 'pending'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELED = 'canceled'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELED, 'Canceled'),
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
