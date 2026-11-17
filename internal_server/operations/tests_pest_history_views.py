import uuid
from datetime import date

from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import WorkReport, Worker
from . import tests as fixtures
from .models import (Location, PestHistoryImport, PestHistoryRecord, PestWorkData,
                     ReferenceCatalog, ReferenceNode)


@override_settings(MULTI_TEAM_ENABLED=True)
class HistoricalWorkorderViewTests(TestCase):
    def setUp(self):
        fixtures.WorkspaceTests.setUp(self)
        self.building = Location.objects.create(owner_team=self.pt, name='Building A', code='TEST-A', kind='building')
        self.room = Location.objects.create(owner_team=self.pt, name='Lobby', kind='room', parent=self.building)
        self.catalog = ReferenceCatalog.objects.create(business=self.pest, owner_team=self.pt,
            version='historical-view-fixture', name='Pest', source_name='fixture')
        self.pt.work_catalog = self.catalog
        self.pt.save(update_fields=['work_catalog'])
        self.leaf = ReferenceNode.objects.create(catalog=self.catalog, label='Collision observation',
            kind='node', source_line=1, order=1)
        worker = Worker.objects.create(employee_id='TEST-HISTORICAL', full_name='Historical source', active=False)
        self.report = WorkReport.all_businesses.create(business_team=self.pt, worker=worker,
            date=date(2021, 2, 20), team_size=0, team_hours=0, third_party_count=0,
            zone_names='Building A / Lobby', work_content='Collision observation', ticket_number='PPC-H-TEST')
        detail = PestWorkData.objects.create(report=self.report, catalog=self.catalog,
            selections=[{'node_id': self.leaf.pk, 'path': ['Collision observation'], 'kind': 'node'}])
        detail.locations.add(self.room)
        batch = PestHistoryImport.objects.create(team=self.pt, dataset='synthetic-birds',
            source_name='synthetic-register.xlsx', source_sha256='a' * 64, input_digest='b' * 64)
        PestHistoryRecord.objects.create(report=self.report, team=self.pt, batch=batch,
            dataset=batch.dataset, source_key='1', content_digest='c' * 64,
            source_sheet='Observations', source_row=4,
            observations={'object_name': 'Bird', 'observed_date': '2021-02-20', 'observed_time': '09:35', 'reported_by': 'Original observer'},
            original={'source_no': 1})

    def test_historical_filter_finds_old_records_and_building_includes_child_rooms(self):
        self.assertNotContains(self.client.get('/work-reports/'), 'PPC-H-TEST')
        response = self.client.get('/work-reports/', {'history': '1', 'location': str(self.building.pk)})
        self.assertContains(response, 'PPC-H-TEST')
        self.assertContains(response, '历史观测')
        self.assertContains(response, '人数与工时未记录')
        self.assertEqual(response.context['totals']['total'], 1)
        self.assertEqual(response.context['period'],'all')
        self.assertEqual(response.context['date_from'],'')
        self.assertNotContains(response, '查询时间范围应为')

    def test_detail_preserves_source_observer_and_discovery_time_without_fabricated_hours(self):
        response = self.client.get(f'/work-reports/{self.report.pk}/')
        for text in ('历史观测记录', 'synthetic-register.xlsx', 'Observations', '第 4 行',
                     'Original observer', '09:35', '未记录'):
            self.assertContains(response, text)
        self.assertNotContains(response, '0 人 / 0.0 小时')

    def test_editing_historical_unknowns_does_not_default_to_current_time_or_early_shift(self):
        html = self.client.get('/api/modal/workorder-data/', {'report_id': self.report.pk}).json()['form_html']
        self.assertIn('name="shift" value=""', html)
        self.assertIn('value="" selected>原表未记录</option>', html)
        response = self.client.post('/mobile/workorder/v2/', {
            'team': str(self.pt.pk), 'report_id': str(self.report.pk), 'catalog': str(self.catalog.pk),
            'nodes': [str(self.leaf.pk)], 'locations': [str(self.room.pk)], 'date': '2021-02-21',
            'team_size': '0', 'third_party_count': '0', 'shift': '', 'work_start_time': '',
            'work_end_time': '', 'submission_key': str(uuid.uuid4()),
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.report.refresh_from_db()
        self.assertEqual(self.report.team_size, 0)
        self.assertIsNone(self.report.work_start_time)
        self.assertIsNone(self.report.work_end_time)
        self.assertEqual(self.report.shift, '')
        self.assertEqual(self.report.history_source.observations['observed_time'], '09:35')
        self.assertEqual(self.report.date, date(2021, 2, 21))
        self.assertContains(self.client.get(f'/work-reports/{self.report.pk}/'), '2021-02-20 09:35')

    def test_history_permission_and_normal_work_requirements_remain_scoped(self):
        self.client.force_login(self.im)
        self.assertEqual(self.client.get(f'/work-reports/{self.report.pk}/').status_code, 404)
        self.client.force_login(self.pm)
        response = self.client.post('/mobile/workorder/v2/', {
            'team': str(self.pt.pk), 'catalog': str(self.catalog.pk), 'nodes': [str(self.leaf.pk)],
            'locations': [str(self.room.pk)], 'date': timezone.localdate().isoformat(),
            'team_size': '0', 'third_party_count': '0', 'submission_key': str(uuid.uuid4()),
        })
        self.assertEqual(response.status_code, 400)
