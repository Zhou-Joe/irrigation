from django.test import TestCase
from core.models import Zone, Worker, WorkLog


class ZoneModelTest(TestCase):
    """Test cases for the Zone model."""

    def test_zone_creation(self):
        """Test Zone creation with default values."""
        zone = Zone.objects.create(
            name='Test Zone',
            code='TZ001',
            boundary_points=[
                {'lat': 40.7128, 'lng': -74.0060},
                {'lat': 40.7138, 'lng': -74.0050},
                {'lat': 40.7148, 'lng': -74.0070},
            ]
        )

        # Verify name
        self.assertEqual(zone.name, 'Test Zone')
        # Verify code
        self.assertEqual(zone.code, 'TZ001')
        # Verify boundary_points default
        self.assertEqual(len(zone.boundary_points), 3)
        self.assertEqual(zone.boundary_points[0]['lat'], 40.7128)
        # Verify status default
        self.assertEqual(zone.status, Zone.STATUS_SCHEDULED)

    def test_zone_status_choices(self):
        """Test Zone status choices and display."""
        zone = Zone.objects.create(
            name='Status Test Zone',
            code='STZ001'
        )

        # Verify default status
        self.assertEqual(zone.status, Zone.STATUS_SCHEDULED)

        # Test all status choices
        status_choices = [
            Zone.STATUS_SCHEDULED,
            Zone.STATUS_WORKING,
            Zone.STATUS_DONE,
            Zone.STATUS_CANCELED,
            Zone.STATUS_DELAYED,
        ]

        for status in status_choices:
            zone.status = status
            zone.save()
            zone.refresh_from_db()
            self.assertEqual(zone.status, status)


class WorkerModelTest(TestCase):
    """Test cases for the Worker model."""

    def test_worker_creation(self):
        """Test Worker creation with default values."""
        worker = Worker.objects.create(
            employee_id='EMP001',
            full_name='John Doe'
        )

        # Verify employee_id
        self.assertEqual(worker.employee_id, 'EMP001')
        # Verify full_name
        self.assertEqual(worker.full_name, 'John Doe')
        # Verify active default
        self.assertTrue(worker.active)


class WorkLogModelTest(TestCase):
    """Test cases for the WorkLog model."""

    def setUp(self):
        """Set up test fixtures."""
        self.zone = Zone.objects.create(
            name='WorkLog Test Zone',
            code='WLTZ001'
        )
        self.worker = Worker.objects.create(
            employee_id='EMP002',
            full_name='Jane Smith'
        )

    def test_work_log_creation(self):
        """Test WorkLog creation with required fields."""
        from django.utils import timezone

        work_log = WorkLog.objects.create(
            zone=self.zone,
            worker=self.worker,
            work_type='planting',
            relay_id='relay-001',
            work_timestamp=timezone.now()
        )

        # Verify zone
        self.assertEqual(work_log.zone, self.zone)
        # Verify worker
        self.assertEqual(work_log.worker, self.worker)
        # Verify work_type
        self.assertEqual(work_log.work_type, 'planting')
        # Verify relay_id
        self.assertEqual(work_log.relay_id, 'relay-001')
