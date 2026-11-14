"""Published numerical check, independent seasonal calibration and read-only APIs."""
import copy
import io
import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from openpyxl import load_workbook

from .et0_estimate import MODEL_VERSION, _reference_et, estimate_days, profile_for_station
from .maxicom_weather import weather_report_data
from .models import MaxicomWeatherLog, MaxicomWeatherStation


def cases():
    path = Path(__file__).parent / 'fixtures/et0_hourly_calibration.json'
    return json.loads(path.read_text(encoding='utf-8'))['cases']


class HourlyEstimateTests(SimpleTestCase):
    def test_published_fao56_example_19(self):
        # FAO-56 Chapter 4 Example 19: afternoon 0.63 mm/hour.
        value = _reference_et(38, 52, 3.3, 1.749, 0.0673 / 0.000665, soil_heat=0.175)
        self.assertAlmostEqual(value, 0.63, delta=0.005)

    def test_independent_winter_spring_summer_and_autumn_records(self):
        for case in cases():
            with self.subTest(day=case['day']):
                result = estimate_days(case['rows'], profile_for_station(31))[date.fromisoformat(case['day'])]
                self.assertAlmostEqual(result['et'], case['expected_et'], places=10)
                self.assertEqual(result['et_valid_hours'], 24)
                self.assertEqual(result['et_source'], 'estimated')

    def test_missing_or_invalid_hour_leaves_et_unavailable(self):
        case = cases()[1]
        for field, value in (('humidity', None), ('humidity', 101), ('humidity', float('nan')),
                             ('wind_run', -1), ('temperature', None), ('solar_radiation', float('inf'))):
            with self.subTest(field=field, value=value):
                rows = copy.deepcopy(case['rows'])
                rows[-1][field] = value
                result = estimate_days(rows, profile_for_station(31))[date.fromisoformat(case['day'])]
                self.assertIsNone(result['et'])
                self.assertEqual(result['et_source'], 'unavailable')
        result = estimate_days(case['rows'][:-1], profile_for_station(31))[date.fromisoformat(case['day'])]
        self.assertIsNone(result['et'])
        self.assertIn('未满24小时', result['et_note'])

    def test_duplicate_hour_and_missing_cloud_history_do_not_create_defaults(self):
        case = cases()[1]
        rows = case['rows'] + [case['rows'][-1]]
        result = estimate_days(rows, profile_for_station(31))[date.fromisoformat(case['day'])]
        self.assertIsNone(result['et'])
        self.assertIn('重复', result['et_note'])
        rows = case['rows'][-24:]
        result = estimate_days(rows, profile_for_station(31))[date.fromisoformat(case['day'])]
        self.assertIsNone(result['et'])
        self.assertIn('云量', result['et_note'])

    def test_rainfall_and_raw_et_are_not_subtracted_or_substituted(self):
        case = cases()[1]
        rows = copy.deepcopy(case['rows'])
        for row in rows:
            row.update(rainfall=999, et=999)
        result = estimate_days(rows, profile_for_station(31))[date.fromisoformat(case['day'])]
        self.assertAlmostEqual(result['et'], case['expected_et'], places=10)

    def test_profiles_are_explicit_finite_and_station_specific(self):
        self.assertIsNone(profile_for_station(29))
        with override_settings(MAXICOM_ET0_STATION_PROFILES={'31': {'latitude': float('nan')}}):
            self.assertIsNone(profile_for_station(31))
        with override_settings(MAXICOM_ET0_STATION_PROFILES=None):
            self.assertIsNone(profile_for_station(31))


class EstimateReportTests(TestCase):
    def setUp(self):
        self.case = cases()[1]
        self.day = date.fromisoformat(self.case['day'])
        self.station = MaxicomWeatherStation.objects.create(mdb_index=31, name='WS BOH 615')
        MaxicomWeatherLog.objects.bulk_create([
            MaxicomWeatherLog(weather_station=self.station, **row) for row in self.case['rows']])
        self.user = User.objects.create_superuser('estimate-review', '', 'test-only')
        self.client.force_login(self.user)

    def test_single_day_range_and_duplicate_source_corrections_agree(self):
        single = weather_report_data(self.day, self.day)['stations'][0]['days'][self.day]
        wider = weather_report_data(date(2026, 3, 1), self.day)['stations'][0]['days'][self.day]
        self.assertAlmostEqual(single['et'], self.case['expected_et'], places=10)
        self.assertEqual(single['et'], wider['et'])
        # A legacy copy of the same timestamp remains one observation.
        MaxicomWeatherLog.objects.create(weather_station=self.station, **self.case['rows'][-1])
        duplicate = weather_report_data(self.day, self.day)['stations'][0]['days'][self.day]
        self.assertEqual(duplicate['et'], single['et'])
        self.assertEqual(duplicate['observed_hours'], 24)

    def test_page_json_and_xlsx_label_the_same_derived_value_without_writes(self):
        before = list(MaxicomWeatherLog.objects.order_by('pk').values())
        query = {'start': str(self.day), 'end': str(self.day)}
        page = self.client.get('/weather/daily/', query)
        self.assertContains(page, 'ET₀估算 mm')
        self.assertContains(page, '非 Maxicom 原厂值')
        self.assertContains(page, '待核对')
        response = self.client.get('/weather/daily/', query, HTTP_ACCEPT='application/json')
        payload = response.json()
        self.assertEqual(payload['et_method'], MODEL_VERSION)
        self.assertEqual(payload['rows'][0]['et_source'], 'estimated')
        self.assertAlmostEqual(payload['rows'][0]['et'], self.case['expected_et'], places=10)
        self.assertEqual(payload['et_parameters'][0]['profile']['latitude'], 40)
        download = self.client.get('/weather/daily/', {**query, 'format': 'xlsx'})
        book = load_workbook(io.BytesIO(b''.join(download.streaming_content)), data_only=True)
        sheet = book.active
        self.assertEqual(sheet['H2'].value, 'ET₀估算 (mm)')
        self.assertAlmostEqual(sheet['H4'].value, self.case['expected_et'], places=10)
        self.assertIn('估算值', sheet['I4'].value)
        self.assertTrue(any('纬度40°' in str(cell.value) for row in sheet for cell in row))
        book.close(); download.close()
        self.assertEqual(before, list(MaxicomWeatherLog.objects.order_by('pk').values()))

    def test_dashboard_trend_exposes_estimation_metadata(self):
        with patch('core.views.timezone.localdate', return_value=date(2026, 3, 13)):
            payload = self.client.get('/api/maxicom-dashboard').json()
        self.assertEqual(payload['et_method'], MODEL_VERSION)
        latest = payload['weather_summary'][0]
        self.assertAlmostEqual(latest['et'], self.case['expected_et'], places=10)
        self.assertEqual(latest['et_source'], 'estimated')
        trend = next(row for row in payload['et_trend'] if row['date'] == str(self.day))
        self.assertEqual(trend['et_source'], 'estimated')
        self.assertEqual(trend['total_et'], latest['et'])

    def test_unconfigured_station_and_incomplete_day_stay_blank(self):
        unknown = MaxicomWeatherStation.objects.create(mdb_index=29, name='Other source')
        MaxicomWeatherLog.objects.bulk_create([
            MaxicomWeatherLog(weather_station=unknown, **row) for row in self.case['rows']])
        MaxicomWeatherLog.objects.filter(weather_station=self.station, timestamp=self.case['rows'][-1]['timestamp']).delete()
        data = weather_report_data(self.day, self.day)
        for station in data['stations']:
            record = station['days'][self.day]
            self.assertIsNone(record['et'])
            self.assertEqual(record['et_source'], 'unavailable')
            self.assertIn('ET₀留空', record['notes'])
