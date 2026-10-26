"""Regression against original October 2026 Actual Log records, not made-up sums."""
import io
import json
from pathlib import Path
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.irrig_time import runtime_window_bounds
from core.models import MaxicomFlowSensor, MaxicomSensorDaily, MaxicomRuntime, Patch
from core.sensor_flow import pulse_microliters, sensor_window

SIGNALS = json.loads((Path(__file__).parent / 'fixtures/maxicom_oct26_actual_signals.json').read_text())
HEAD = 'XactStamp|XactIndex|ControllerChannel|SignalIndex|SignalTable|SignalType|SignalValue|SignalMultiplier'


@override_settings(TIME_ZONE='Asia/Shanghai')
class PhysicalSensorTests(TestCase):
    def setUp(self):
        self.tables = {
            'SITE_CF': [{'IndexNumber': '5', 'SiteNumber': '3', 'IndexName': 'Tomorrowland'}],
            'DCODE_TP': [{'IndexNumber': '8', 'DecoderTypeFlowMeter': 'Y'},
                         {'IndexNumber': '7', 'DecoderTypeFlowMeter': 'N'}],
            'DCODE_CF': [dict(IndexNumber=str(idx), TableIndexNumber='8', DecoderSiteNumber='5',
                DecoderControllerNumber='18', DecoderControllerChannel=str(channel), DecoderEnabled='Y',
                IndexName=f'{channel}: Flow Sensor {name}', DecoderPulseValue='99999')
                for idx, channel, name in [(82,15,'Low'), (83,16,'High'), (84,17,'WP')]]}
        # Old configuration/current calibration must not override logged multipliers.
        self.tables['DCODE_CF'].insert(0, {**self.tables['DCODE_CF'][0], 'DateClose': '20200101', 'DecoderSiteNumber': '999'})
        self.tables['DCODE_CF'].append(dict(IndexNumber='999', TableIndexNumber='7', DecoderSiteNumber='5', IndexName='Wind'))
        self.rows = SIGNALS['sensors'] + SIGNALS['stations']

    def run_import(self, rows=None, status=0):
        rows = self.rows if rows is None else rows
        process = Mock()
        process.stdout = io.StringIO(HEAD + '\n' + '\n'.join('|'.join(str(r.get(k, '')) for k in HEAD.split('|')) for r in rows))
        process.wait.return_value = status
        module = 'core.management.commands.import_maxicom_mdb_linux'
        with patch(module + '.os.path.exists', return_value=True), \
                patch(module + '._mdb_rows', side_effect=lambda _, t: iter(self.tables[t])), \
                patch(module + '.subprocess.Popen', return_value=process):
            call_command('import_maxicom_mdb_linux', mdb='original-records.mdb', sensors_only=True, stdout=io.StringIO())

    def values(self, start='20261024153200', end='20261025153200'):
        result = sensor_window(start, end)
        self.assertFalse(result['notice'])
        return {s['channel']: s for site in result['sites'] for s in site['sensors']}

    def test_all_five_operator_figures_match_the_afternoon_not_morning_window(self):
        self.run_import()
        for start, end, expected in [('20261024153200','20261025153200', {15:'2,380',16:'0',17:'34,200'}),
                                      ('20261024033200','20261025033200', {15:'4,690',16:'0',17:'33,600'})]:
            with self.subTest(start=start):
                self.assertEqual({k:v['formatted'] for k,v in self.values(start,end).items()}, expected)
                lo, hi = runtime_window_bounds(start, end)
                actual = {idx: sum(int(r['SignalValue']) for r in SIGNALS['stations']
                    if r['XactIndex']==idx and lo<=r['XactStamp']<=hi and r['SignalType']=='M') for idx in ('1397','1467')}
                self.assertEqual(actual, {'1397':0,'1467':895} if '1532' in start else {'1397':87,'1467':881})

    def test_source_identity_channels_historical_multiplier_and_idempotency(self):
        self.run_import()
        ids = list(MaxicomFlowSensor.objects.values_list('pk', flat=True))
        self.run_import()
        self.assertEqual(list(MaxicomFlowSensor.objects.values_list('pk',flat=True)),ids)
        low = MaxicomFlowSensor.objects.get(mdb_index=82)
        self.assertEqual((low.source_site_index,low.source_site_number,low.channel),(5,3,15))
        self.assertEqual(MaxicomFlowSensor.objects.count(),3)
        self.assertEqual(self.values()[15]['formatted'],'2,380')
        self.assertEqual(pulse_microliters('34','18.494055'),2379999938)

    def test_coverage_and_disabled_sensor_do_not_invent_zeros(self):
        self.run_import()
        values = self.values('20261027153200','20261028153200')
        self.assertTrue(all(v['value'] is None and not v['complete'] for v in values.values()))
        MaxicomFlowSensor.objects.filter(mdb_index=83).update(is_enabled=False)
        self.assertIsNone(self.values()[16]['value'])

    def test_error_empty_invalid_multiplier_and_unknown_sensor_preserve_previous_records(self):
        self.run_import()
        before = list(MaxicomSensorDaily.objects.values_list('pk','microliters','samples'))
        bad = [{**self.rows[0], 'SignalMultiplier':'NaN'}, {**self.rows[0], 'XactIndex':'9999'},
               {**self.rows[0], 'XactStamp':'20260230000000'}]
        for rows, status in [([],0), (self.rows,1)] + [([r],0) for r in bad]:
            with self.subTest(rows=rows[:1],status=status), self.assertRaises(CommandError):
                self.run_import(rows,status)
            self.assertEqual(list(MaxicomSensorDaily.objects.values_list('pk','microliters','samples')),before)

    def test_sensor_import_preserves_runtime_and_ignores_configuration_and_other_signals(self):
        ccu,_ = Patch.objects.get_or_create(code='CCU3',defaults={'name':'TL'})
        rt = MaxicomRuntime.objects.create(site=ccu,timestamp='20261024000000',station_id_raw=1397,run_time=87)
        self.rows += [{**self.rows[0],'SignalType':'C','SignalValue':'999999'},
                      {**self.rows[0],'SignalTable':'C','SignalValue':'999999'}]
        self.run_import()
        self.assertEqual(MaxicomRuntime.objects.get(pk=rt.pk).run_time,87)
        self.assertEqual(self.values()[15]['formatted'],'2,380')

    def test_combined_flow_import_rolls_back_legacy_data_when_sensor_export_fails(self):
        from core.models import MaxicomFlowZone
        zone=MaxicomFlowZone.objects.create(mdb_index=99001,name='Before',source_site_index=5)
        def change_legacy(*args):
            MaxicomFlowZone.objects.filter(pk=zone.pk).update(name='After')
        module='core.management.commands.import_maxicom_mdb_linux'
        with patch(module+'.os.path.exists',return_value=True), \
                patch('core.flow_import.import_flow',side_effect=change_legacy), \
                patch('core.sensor_flow.import_sensor_flow',side_effect=CommandError('Source unavailable')):
            with self.assertRaises(CommandError):
                call_command('import_maxicom_mdb_linux',mdb='source.mdb',flow_only=True,stdout=io.StringIO())
        zone.refresh_from_db()
        self.assertEqual(zone.name,'Before')

    def test_second_boundaries_and_complete_day_cache_agree(self):
        self.run_import()
        row = next(r for r in SIGNALS['sensors'] if r['XactStamp']=='20261025063339' and r['XactIndex']=='82')
        self.assertEqual(row['SignalValue'],'1')
        self.assertEqual(self.values('20261025143339','20261025143339')[15]['formatted'],'70')
        self.assertEqual(self.values('20261025143340','20261025143340')[15]['formatted'],'0')
        # Equivalent full-day SQL total and sample-filtered second window.
        total = sensor_window('20261024220000','20261025215959')['sites'][0]['sensors']
        lo,hi=runtime_window_bounds('20261024220000','20261025215959')
        expected=sum(pulse_microliters(r['SignalValue'],r['SignalMultiplier']) for r in SIGNALS['sensors']
                     if r['XactIndex']=='82' and r['SignalType']=='F' and lo<=r['XactStamp']<=hi)
        self.assertEqual(next(s['value'] for s in total if s['channel']==15),round(expected/1_000_000,2))

    def test_page_ajax_and_ai_distinguish_physical_sensors_from_flow_watch(self):
        self.run_import()
        user=User.objects.create_superuser('sensor-review','','test-only')
        self.client.force_login(user)
        params={'from':'20261024153200','to':'20261025153200'}
        page=self.client.get('/irrigation/',params)
        self.assertContains(page,'实际传感器水量（升）')
        self.assertContains(page,'2,380')
        self.assertContains(page,'FLO WATCH 区域参考记录')
        data=self.client.get('/irrigation/',{**params,'format':'json'}).json()['sensor_data']
        self.assertEqual(data,sensor_window(params['from'],params['to']))
        from core.ai_agent import query_flow_daily
        ai=json.loads(query_flow_daily.invoke({'start_date':'2026-10-25','end_date':'2026-10-25'}))
        self.assertTrue(ai['单位已核准'])
        self.assertEqual(ai['来源'],'XA_LOG D/F 实际流量传感器')
        self.assertNotIn('站点汇总水量升',ai)
