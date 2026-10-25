"""Independent flow records: source identity, overlapping zones and exact windows."""
import io
import json
import struct
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.flow_data import SAMPLE, encode_samples, flow_window, sample_offset_for_hour
from core.models import (MaxicomFlowDaily, MaxicomFlowReading, MaxicomFlowZone,
                         MaxicomRuntime, Patch)


@override_settings(TIME_ZONE='Asia/Shanghai')
class FlowImportTests(TestCase):
    module = 'core.management.commands.import_maxicom_mdb_linux'

    def setUp(self):
        self.ccu3, _ = Patch.objects.get_or_create(code='CCU3', defaults={'name': 'TL'})
        self.ccu5, _ = Patch.objects.get_or_create(code='CCU5', defaults={'name': 'FL'})
        self.ccu7, _ = Patch.objects.get_or_create(code='CCU7', defaults={'name': 'Adventure'})
        self.tables = {
            'SITE_CF': [
                {'IndexNumber': '3', 'SiteNumber': '999', 'IndexName': 'Old name', 'DateClose': '20200101'},
                {'IndexNumber': '3', 'SiteNumber': '5', 'IndexName': 'Fantasyland', 'DateOpen': '20200101'},
                {'IndexNumber': '5', 'SiteNumber': '3', 'IndexName': 'Tomorrowland'},
                {'IndexNumber': '4', 'SiteNumber': '7', 'IndexName': 'Adventure'},
                {'IndexNumber': '26', 'SiteNumber': '99', 'IndexName': 'Unmapped Site'}],
            'FLOZO_CF': [
                {'IndexNumber': '90101', 'FlowZoneSiteNumber': '3', 'IndexName': 'FS Low', 'FlowZoneJoinSite': 'Y', 'FlowZoneSiteCounter': '1'},
                {'IndexNumber': '90102', 'FlowZoneSiteNumber': '5', 'IndexName': 'Toilet FS', 'FlowZoneJoinSite': 'Y'},
                {'IndexNumber': '90103', 'FlowZoneSiteNumber': '4', 'IndexName': 'FS High', 'FlowZoneJoinSite': 'N'},
                {'IndexNumber': '90104', 'FlowZoneSiteNumber': '26', 'IndexName': 'WD FS', 'FlowZoneJoinSite': 'Y'}]}
        self.readings = (
            'XactStamp|XactIndex|FlowZoneValue|FlowZoneMultiplier|SiteID\n'
            '20260911135959|90101|7|1|3\n'  # Previous irrigation day.
            '20260911140000|90101|10|2|3\n'
            '20260911230100|90101|4|1|3\n'  # Shanghai September 12 07:01:00.
            '20260911230159|90101|5|1|3\n'
            '20260911230200|90101|100|1|3\n'
            '20260911230100|90102|11|1|5\n'
            '20260911230100|90103|12|1|4\n'
            '20260911230100|90104|13|1|26\n')

    def run_import(self, readings=None, exit_code=0):
        process = Mock()
        process.stdout = io.StringIO(self.readings if readings is None else readings)
        process.wait.return_value = exit_code
        with patch(self.module + '.os.path.exists', return_value=True), \
                patch(self.module + '._mdb_rows', side_effect=lambda _p, t: iter(self.tables[t])) as exported, \
                patch(self.module + '.subprocess.Popen', return_value=process):
            call_command('import_maxicom_mdb_linux', mdb='fixture.mdb', flow_only=True, stdout=io.StringIO())
        self.assertEqual({c.args[1] for c in exported.call_args_list}, {'SITE_CF', 'FLOZO_CF'})

    def test_source_foreign_key_is_resolved_through_display_number(self):
        self.run_import()
        a = MaxicomFlowZone.objects.get(mdb_index=90101)
        b = MaxicomFlowZone.objects.get(mdb_index=90102)
        self.assertEqual((a.source_site_index, a.source_site_number, a.site_id), (3, 5, self.ccu5.pk))
        self.assertEqual((b.source_site_index, b.source_site_number, b.site_id), (5, 3, self.ccu3.pk))
        self.assertEqual(a.source_site_name, 'Fantasyland')

    def test_real_site_without_matching_internal_ccu_and_unmapped_site_are_retained(self):
        self.run_import()
        self.assertEqual(MaxicomFlowZone.objects.get(mdb_index=90103).site_id, self.ccu7.pk)
        unmapped = MaxicomFlowZone.objects.get(mdb_index=90104)
        self.assertIsNone(unmapped.site_id)
        self.assertEqual(unmapped.daily.get().liters, 13)

    def test_flow_only_preserves_runtime_business_patches_and_legacy_reading_ids(self):
        runtime = MaxicomRuntime.objects.create(site=self.ccu3, station_id_raw=99901, timestamp='20260911230100', run_time=91)
        zone = MaxicomFlowZone.objects.create(site=self.ccu3, mdb_index=90101, name='Old')
        reading = MaxicomFlowReading.objects.create(flow_zone=zone, timestamp='20200101000000', value=9, multiplier=1)
        before = list(Patch.objects.values_list('id', 'code', 'name', 'parent_id'))
        self.run_import()
        self.run_import()
        self.assertEqual(MaxicomRuntime.objects.get(pk=runtime.pk).run_time, 91)
        self.assertEqual(list(Patch.objects.values_list('id', 'code', 'name', 'parent_id')), before)
        self.assertEqual(MaxicomFlowZone.objects.get(mdb_index=90101).pk, zone.pk)
        self.assertEqual(MaxicomFlowReading.objects.get(pk=reading.pk).flow_zone_id, zone.pk)
        self.assertEqual(MaxicomFlowZone.objects.filter(mdb_index=90101).count(), 1)

    def test_custom_window_keeps_both_second_boundaries_and_original_values(self):
        self.run_import()
        data = flow_window('20260912070100', '20260912070159')
        source = next(s for s in data['sites'] if s['number'] == 5)
        self.assertEqual(source['value'], 9)
        self.assertEqual(source['zones'][0]['value'], 9)
        self.assertEqual(data['notice'], '')
        complete = flow_window('202609112200', '202609122159')
        self.assertEqual(next(s['value'] for s in complete['sites'] if s['number'] == 5), 129)

    def test_failed_empty_or_inconsistent_export_preserves_previous_flow(self):
        self.run_import()
        before = list(MaxicomFlowDaily.objects.values_list('id', 'liters', 'samples'))
        bad = [self.readings.replace('|90104|13|1|26', '|90104|13|1|3'),
               self.readings.replace('20260911230159', '20260911236159'),
               self.readings.splitlines()[0] + '\n']
        for text in bad:
            with self.subTest(text=text[-60:]), self.assertRaises(CommandError):
                self.run_import(text)
            self.assertEqual(list(MaxicomFlowDaily.objects.values_list('id', 'liters', 'samples')), before)
        with self.assertRaises(CommandError):
            self.run_import(exit_code=1)
        self.assertEqual(list(MaxicomFlowDaily.objects.values_list('id', 'liters', 'samples')), before)


@override_settings(TIME_ZONE='Asia/Shanghai')
class FlowViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser('flow-review', '', 'test-only')
        cls.ccu, _ = Patch.objects.get_or_create(code='CCU2', defaults={'name': 'East'})
        cls.zones = []
        for idx, name, included in [(91003, 'Entire Site IRR', True),
                                     (91043, 'FS High <img src=x onerror=alert(1)>', False)]:
            zone = MaxicomFlowZone.objects.create(
                site=cls.ccu, mdb_index=idx, name=name, join_site=included,
                source_site_index=2, source_site_number=2, source_site_name='East Entrance')
            cls.zones.append(zone)
            MaxicomFlowDaily.objects.create(zone=zone, site=cls.ccu, flow_day='20260912', liters=2803,
                samples=encode_samples(SAMPLE.pack(9 * 3600 + 60, 2803)))
        # A large theoretical value must never leak into the independent flow total.
        MaxicomRuntime.objects.create(site=cls.ccu, station_id_raw=99902, timestamp='20260911230100', run_time=99999)

    def setUp(self):
        self.client.force_login(self.user)

    def test_site_sum_excludes_submeter_but_retains_its_detail(self):
        data = flow_window('202609112200', '202609122159')
        site = next(s for s in data['sites'] if s['key'] == '2')
        self.assertEqual(site['value'], 2803)
        self.assertEqual([z['value'] for z in site['zones']], [2803, 2803])
        self.assertEqual([z['included'] for z in site['zones']], [True, False])

    def test_custom_window_with_full_interior_day_does_not_double_count(self):
        data = flow_window('20260911230000', '20260913230000')
        self.assertEqual(next(s['value'] for s in data['sites'] if s['key'] == '2'), 2803)

    def test_old_daily_data_does_not_pretend_to_have_hourly_precision(self):
        MaxicomFlowDaily.objects.all().update(samples=None)
        data = flow_window('20260912070100', '20260912070159')
        self.assertTrue(data['notice'])
        self.assertEqual(data['sites'], [])
        self.assertFalse(flow_window('202609112200', '202609122159')['notice'])

    def test_corrupt_samples_do_not_return_a_partial_total(self):
        MaxicomFlowDaily.objects.filter(zone=self.zones[1]).update(samples=b'bad')
        data = flow_window('20260912070100', '20260912070159')
        self.assertTrue(data['notice'])
        self.assertEqual(data['sites'], [])

    def test_web_and_ajax_use_source_site_and_do_not_follow_runtime_ccu_paging(self):
        params = {'from': '202609112200', 'to': '202609122159'}
        a = self.client.get('/irrigation/', {**params, 'format': 'json'}).json()['flow_data']
        b = self.client.get('/irrigation/', {**params, 'ccu': self.ccu.pk, 'format': 'json'}).json()['flow_data']
        self.assertEqual(a, b)
        page = self.client.get('/irrigation/', params)
        self.assertContains(page, 'Site 2 · East Entrance')
        self.assertContains(page, '仅明细')
        self.assertContains(page, '&lt;img src=x onerror=alert(1)&gt;')
        self.assertNotContains(page, '<img src=x onerror=alert(1)>')
        self.assertNotContains(page, '参考合计')

    def test_ai_total_and_details_use_the_same_inclusion_flags(self):
        from core.ai_agent import query_flow_daily
        data = json.loads(query_flow_daily.invoke({'start_date': '2026-09-12', 'end_date': '2026-09-12'}))
        self.assertEqual(data['站点汇总水量升'], 2803)
        self.assertEqual(len(data['按流量区域分布']), 2)
        self.assertEqual({z['计入站点汇总'] for z in data['按流量区域分布']}, {True, False})
