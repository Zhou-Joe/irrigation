"""Shared CCU filters, synchronization defaults and drawable heatmap scope."""
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory, override_settings
from core.models import DataImportRun, MaxicomRuntime, Patch, Zone
from core.views import _irrig_default_window, _irrig_window


@override_settings(TIME_ZONE='Asia/Shanghai')
class IrrigationDefaultWindowTests(TestCase):
    def test_every_sync_preset_uses_successful_sync_and_preserves_ccu(self):
        sync=datetime(2026,11,3,23,1,30,tzinfo=dt_timezone.utc)
        DataImportRun.objects.create(status='success',finished_at=sync)
        DataImportRun.objects.create(status='failed',finished_at=sync+timedelta(hours=1))
        user=User.objects.create_superuser('irrig-presets','','test-only');self.client.force_login(user)
        ccu,_=Patch.objects.get_or_create(code='CCU3',defaults={'name':'TL'})
        for days in (1,3,7,14,30):
            with self.subTest(days=days):
                params={'sync_days':days,'ccu':ccu.pk}
                response=self.client.get('/irrigation/',{**params,'format':'json'})
                self.assertEqual(response.status_code,200)
                data=response.json()
                self.assertEqual(data['date_to'],'20261104070130')
                self.assertEqual(datetime.strptime(data['date_to'],'%Y%m%d%H%M%S')-
                                 datetime.strptime(data['date_from'],'%Y%m%d%H%M%S'),timedelta(days=days))
                self.assertEqual(data['selected_ccu_code'],'CCU3')
                self.assertEqual(data['sync_days'],days)
                self.assertEqual(_irrig_window(RequestFactory().get('/api/irrigation/zone-heatmap/',params))[:2],
                                 (data['date_from'],data['date_to']))
        html=self.client.get('/irrigation/')
        for label in ('同步前24h','同步前3天','同步前7天','同步前14天','同步前30天'):
            self.assertContains(html,label)

    def test_preset_requeries_new_sync_and_explicit_dates_take_precedence(self):
        first=datetime(2026,11,3,23,1,30,tzinfo=dt_timezone.utc)
        DataImportRun.objects.create(status='success',finished_at=first)
        request=RequestFactory().get('/irrigation/',{'sync_days':'7'})
        old=_irrig_window(request)
        DataImportRun.objects.create(status='success',finished_at=first+timedelta(hours=2))
        self.assertNotEqual(_irrig_window(request),old)
        manual=RequestFactory().get('/irrigation/',{'sync_days':'30','from':'20260912070100','to':'20260912070159'})
        self.assertEqual(_irrig_window(manual)[:2],('20260912070100','20260912070159'))
        from django.core.exceptions import BadRequest
        for invalid in ('0','-3','31','3.5','bad'):
            with self.assertRaises(BadRequest):
                _irrig_window(RequestFactory().get('/irrigation/',{'sync_days':invalid}))

    def test_latest_success_anchors_24_hours_even_when_newer_import_failed(self):
        sync=datetime(2026,10,26,23,1,30,tzinfo=dt_timezone.utc)
        DataImportRun.objects.create(status='success',finished_at=sync)
        DataImportRun.objects.create(status='failed',finished_at=datetime(2026,10,27,0,0,tzinfo=dt_timezone.utc))
        self.assertEqual(_irrig_default_window(),('20261026070130','20261027070130'))
        request=RequestFactory().get('/irrigation/')
        self.assertEqual(_irrig_window(request),('20261026070130','20261027070130','20261025230130','20261026230130'))
        user=User.objects.create_superuser('irrig-default','','test-only');self.client.force_login(user)
        page=self.client.get('/irrigation/')
        self.assertEqual(page.context['default_window_dt'],('2026-10-26T07:01:30','2026-10-27T07:01:30'))

    def test_without_import_history_falls_back_to_latest_available_runtime(self):
        ccu,_=Patch.objects.get_or_create(code='CCU3',defaults={'name':'TL'})
        MaxicomRuntime.objects.create(site=ccu,station_id_raw=9999,timestamp='20260911230159',run_time=1)
        self.assertEqual(_irrig_default_window(),('20260911070159','20260912070159'))

    def test_empty_installation_and_explicit_windows(self):
        with patch('core.views.timezone.now',return_value=datetime(2026,10,27,0,0,tzinfo=dt_timezone.utc)):
            self.assertEqual(_irrig_default_window(),('20261026080000','20261027080000'))
        request=RequestFactory().get('/irrigation/',{'from':'20260912070100','to':'20260912070159'})
        self.assertEqual(_irrig_window(request)[:2],('20260912070100','20260912070159'))


@override_settings(TIME_ZONE='Asia/Shanghai')
class IrrigationHeatmapScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user=User.objects.create_superuser('irrig-map','','test-only')
        cls.ccu3,_=Patch.objects.get_or_create(code='CCU3',defaults={'name':'TL'})
        cls.ccu5,_=Patch.objects.get_or_create(code='CCU5',defaults={'name':'FL'})
        boundary=[{'lat':31.145,'lng':121.655},{'lat':31.146,'lng':121.655},{'lat':31.145,'lng':121.656}]
        for code,ccu,minutes,drawn in [('3-1-1',cls.ccu3,60,True),('3-1-2',cls.ccu3,60000,False),('5-1-1',cls.ccu5,120,True)]:
            station=Patch.objects.create(code='map-test-'+code,parent=ccu,name=code)
            MaxicomRuntime.objects.create(site=ccu,station=station,station_id_raw=station.pk,timestamp='20260911230100',run_time=minutes)
            Zone.objects.create(code=code,name=code,patch=ccu,maxicom_runtime=[station.pk],boundary_points=boundary if drawn else [],irrigation_intensity=10)

    def setUp(self):self.client.force_login(self.user)

    def test_unmapped_values_are_retained_without_setting_either_map_maximum(self):
        data=self.client.get('/api/irrigation/zone-heatmap/',{'from':'20260911220000','to':'20260912215959'}).json()
        self.assertEqual({z['code'] for z in data['zones']},{'3-1-1','5-1-1'})
        self.assertEqual(data['unmapped'][0]['runtime_minutes'],60000)
        self.assertEqual(data['unmapped'][0]['irrigation_depth_mm'],10000)
        self.assertEqual((data['max'],data['max_volume']),(120,20))

    def test_heatmap_honors_the_same_ccu_as_runtime_and_water(self):
        data=self.client.get('/api/irrigation/zone-heatmap/',{'ccu':self.ccu3.pk,'from':'20260911220000','to':'20260912215959'}).json()
        self.assertEqual([z['code'] for z in data['zones']],['3-1-1'])
        self.assertEqual([z['code'] for z in data['unmapped']],['3-1-2'])
        self.assertEqual((data['max'],data['max_volume']),(60,10))
