"""134–138：真实端点、回滚、采购来源与自然日边界回归。"""
import io
import json
import tempfile
from datetime import date, datetime, timedelta, timezone as utc
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import caches
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from .models import (InventoryCategory, InventoryPriceRecord, MaxicomWeatherLog,
                     MaxicomWeatherStation, PipeValve, Pipeline, PipelineImportBatch,
                     PurchaseOrder, PurchaseOrderLine)
from .maxicom_weather import weather_report_data


class FeedbackTests(TestCase):
    def setUp(self):
        for cache in caches.all():
            cache.clear()
        self.user = User.objects.create_superuser('feedback-admin', '', 'test-only')
        self.client.force_login(self.user)


class PipelineFeedbackTests(FeedbackTests):
    def setUp(self):
        super().setUp()
        self.batch = PipelineImportBatch.objects.create(name='Zone.dxf',
            source_geometry={'layers': ['original']}, calibration_snapshot={'kind': 'original'})
        self.pipe = Pipeline.objects.create(name='First pipe', code='PIPE-1', import_batch=self.batch,
            pipeline_type='irrigation', line_points=[{'lat': 31, 'lng': 121}, {'lat': 31.001, 'lng': 121}],
            source_points=[[1, 2], [3, 4]], source_map_points=[{'lat': 31, 'lng': 121}])
        self.valve = PipeValve.objects.create(pipeline=self.pipe, source_point=[1, 2],
            source_attributes={'label': 'source'}, point=[{'lat': 31, 'lng': 121}])

    def test_batch_deletion_backs_up_original_and_corrected_geometry_without_touching_other_batches(self):
        other = Pipeline.objects.create(name='Other pipe', code='PIPE-2')
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as folder, override_settings(PIPELINE_BACKUP_ROOT=folder):
            result = self.client.post(reverse('core:pipeline_batch_delete', args=[self.batch.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(result.status_code, 200, result.content)
            backup = json.loads((Path(folder) / result.json()['backup']).read_text(encoding='utf-8'))
        self.assertEqual(result.json()['pipelines'], 1)
        self.assertEqual(result.json()['valves'], 1)
        self.assertEqual(backup['batch']['source_geometry'], self.batch.source_geometry)
        self.assertEqual(backup['pipelines'][0]['source_points'], self.pipe.source_points)
        self.assertEqual(backup['pipelines'][0]['line_points'], self.pipe.line_points)
        self.assertEqual(backup['pipelines'][0]['valves'][0]['id'], self.valve.pk)
        self.assertEqual(backup['pipelines'][0]['valves'][0]['source_point'], self.valve.source_point)
        self.assertIn('station_id', backup['pipelines'][0]['valves'][0])
        self.assertFalse(PipelineImportBatch.objects.filter(pk=self.batch.pk).exists())
        self.assertFalse(PipeValve.objects.filter(pk=self.valve.pk).exists())
        self.assertTrue(Pipeline.objects.filter(pk=other.pk).exists())

    def test_failed_backup_returns_json_and_deletes_nothing(self):
        with patch('core.pipeline_management.Path.open', side_effect=PermissionError('read-only backup folder')), \
             self.assertLogs('core.pipeline_management', level='ERROR'):
            result = self.client.post(reverse('core:pipeline_batch_delete', args=[self.batch.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(result.status_code, 500)
        self.assertIn('备份失败', result.json()['error'])
        self.assertTrue(Pipeline.objects.filter(pk=self.pipe.pk).exists())
        self.assertTrue(PipeValve.objects.filter(pk=self.valve.pk).exists())
        self.assertTrue(PipelineImportBatch.objects.filter(pk=self.batch.pk).exists())

    def test_database_failure_rolls_back_and_returns_json(self):
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as folder, override_settings(PIPELINE_BACKUP_ROOT=folder), \
             patch('django.db.models.query.QuerySet.delete', side_effect=RuntimeError('delete failed')), \
             self.assertLogs('core.pipeline_management', level='ERROR'):
            result = self.client.post(reverse('core:pipeline_batch_delete', args=[self.batch.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(result.status_code, 500)
        self.assertIn('回滚', result.json()['error'])
        self.assertTrue(Pipeline.objects.filter(pk=self.pipe.pk).exists())

    def test_custom_type_and_type_wide_style_edit_preserve_geometry_and_import_identity(self):
        other = Pipeline.objects.create(name='Flush pipe', code='FLUSH-1', pipeline_type='flush')
        result = self.client.post(reverse('core:pipeline_type_save'), {'name': '再生水管', 'color': '#123abc'})
        self.assertEqual(result.status_code, 200, result.content)
        code = next(item['code'] for item in result.json()['types'] if item['name'] == '再生水管')
        result = self.client.post(reverse('core:pipeline_bulk_update'),
            {'scope_type': 'irrigation', 'pipeline_type': code, 'color': '#456789', 'line_weight': '7'})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()['count'], 1)
        old_geometry, batch_id = self.pipe.line_points, self.pipe.import_batch_id
        self.pipe.refresh_from_db(); other.refresh_from_db()
        self.assertEqual(self.pipe.pipeline_type, code)
        self.assertEqual(self.pipe.get_pipeline_type_display(), '再生水管')
        self.assertEqual(self.pipe.line_color, '#456789')
        self.assertEqual(self.pipe.line_weight, 7)
        self.assertTrue(self.pipe.line_weight_custom)
        self.assertEqual(self.pipe.line_points, old_geometry)
        self.assertEqual(self.pipe.import_batch_id, batch_id)
        self.assertEqual(other.pipeline_type, 'flush')
        self.assertEqual(other.line_weight, 3)
        for path in [reverse('core:pipeline_edit', args=[self.pipe.pk]), reverse('core:pipeline_dxf_import')]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, response.content[:500])
            self.assertIn('再生水管', [kind['name'] for kind in response.context['pipeline_types']])

    def test_invalid_or_unscoped_bulk_edits_never_change_pipelines(self):
        for params in ({'line_weight': '4'}, {'ids': json.dumps([self.pipe.pk]), 'line_weight': '11'},
                       {'ids': json.dumps([self.pipe.pk, 999999]), 'color': '#123456'},
                       {'scope_type': 'irrigation', 'color': 'red;"<>'},
                       {'scope_type': 'irrigation', 'pipeline_type': 'unregistered'}):
            response = self.client.post(reverse('core:pipeline_bulk_update'), params)
            self.assertEqual(response.status_code, 400, response.content)
            self.pipe.refresh_from_db()
            self.assertEqual(self.pipe.line_weight, 3)
            self.assertEqual(self.pipe.color, '')

    def test_first_settings_visit_issues_csrf_cookie_for_real_browser_actions(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        page = browser.get(reverse('core:settings'))
        self.assertEqual(page.status_code, 200)
        self.assertIn('csrftoken', browser.cookies)
        token = browser.cookies['csrftoken'].value
        response = browser.post(reverse('core:pipeline_type_save'), {'name': '临时管道', 'color': '#abcdef'},
            HTTP_X_CSRFTOKEN=token, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200, response.content)
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as folder, override_settings(PIPELINE_BACKUP_ROOT=folder):
            response = browser.post(reverse('core:pipeline_batch_delete', args=[self.batch.pk]),
                HTTP_X_CSRFTOKEN=token, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200, response.content)

    def test_expired_session_returns_json_instead_of_a_login_page(self):
        self.client.logout()
        response = self.client.post(reverse('core:pipeline_batch_delete', args=[self.batch.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json()['success'])
        self.assertTrue(Pipeline.objects.filter(pk=self.pipe.pk).exists())


class PurchaseFeedbackTests(FeedbackTests):
    def setUp(self):
        super().setUp()
        self.part = InventoryCategory.objects.create(name_zh='喷芯加长杆', code='EXTENDER', node_type='part', unit='个', current_stock=3)

    def upload(self, rows):
        book = Workbook(); sheet = book.active
        for row in rows: sheet.append(row)
        buffer = io.BytesIO(); book.save(buffer)
        return SimpleUploadedFile('PO.xlsx', buffer.getvalue())

    def test_po_preview_matches_real_catalog_and_keeps_suppliers_without_writing(self):
        response = self.client.post(reverse('core:purchase_order_import_preview'), {'file': self.upload([
            ['物料名称', '数量', '未税单价', '供应商', '单位', 'PO号'],
            ['喷芯加长杆', 1500, 15.31, '测试供应商', '个', 'PO-330']])})
        self.assertEqual(response.status_code, 200, response.content)
        row = response.json()['rows'][0]
        self.assertEqual(row['category_id'], self.part.pk)
        self.assertEqual(row['quantity'], 1500)
        self.assertEqual(row['unit_price'], '15.31')
        self.assertEqual(row['supplier'], '测试供应商')
        self.assertEqual(row['errors'], [])
        self.assertFalse(PurchaseOrder.objects.exists())
        self.assertFalse(InventoryPriceRecord.objects.exists())

    def test_field_mapping_can_be_corrected_and_ambiguous_names_are_not_auto_selected(self):
        InventoryCategory.objects.create(name_zh=self.part.name_zh, code='OTHER', node_type='part')
        result = self.client.post(reverse('core:purchase_order_import_preview'), {'file': self.upload([
            ['字段A', '字段B', '字段C', '字段D'], [self.part.name_zh, 2, 0, '供应商甲']])}).json()
        response = self.client.post(reverse('core:purchase_order_import_preview'), {'token': result['token'],
            'mapping': json.dumps({'name': 0, 'quantity': 1, 'unit_price': 2, 'supplier': 3})})
        self.assertEqual(response.status_code, 200, response.content)
        row = response.json()['rows'][0]
        self.assertIsNone(row['category_id'])
        self.assertEqual(len(row['candidates']), 2)
        self.assertEqual(row['unit_price'], '0.00')
        self.assertEqual(row['supplier'], '供应商甲')

    def test_saved_supplier_is_retained_on_order_price_history_and_unchanged_edits(self):
        lines = json.dumps([{'category': self.part.pk, 'quantity': 1500, 'unit': '个', 'unit_price': '15.31', 'supplier': '供应商甲'}])
        response = self.client.post('/purchase-orders/create/', {'order_number': '330b', 'lines': lines})
        self.assertEqual(response.status_code, 200, response.content)
        order = PurchaseOrder.objects.get()
        self.assertEqual(order.planned_lines.get().supplier, '供应商甲')
        self.assertEqual(InventoryPriceRecord.objects.get(is_current=True).supplier, '供应商甲')
        self.assertEqual(response.json()['node']['planned_lines'][0]['supplier'], '供应商甲')
        response = self.client.post(f'/purchase-orders/{order.pk}/edit/', {'order_number': '330b', 'lines': lines})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(InventoryPriceRecord.objects.count(), 1)
        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, 3)

    def test_invalid_supplier_rolls_back_order_and_catalog_price(self):
        response = self.client.post('/purchase-orders/create/', {'order_number': 'invalid', 'lines': json.dumps([
            {'category': self.part.pk, 'quantity': 1, 'unit_price': '10', 'supplier': 'x' * 201}])})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PurchaseOrder.objects.exists())
        self.assertFalse(InventoryPriceRecord.objects.exists())

    def test_preview_rejects_foreign_tokens_and_oversized_worksheets(self):
        response = self.client.post(reverse('core:purchase_order_import_preview'), {'file': self.upload([
            ['物料名称', '数量', '未税单价'], [self.part.name_zh, 1, 2]])})
        token = response.json()['token']
        second = User.objects.create_superuser('other-importer', '', 'test')
        self.client.force_login(second)
        result = self.client.post(reverse('core:purchase_order_import_preview'), {'token': token, 'mapping': '{}'})
        self.assertEqual(result.status_code, 400)
        result = self.client.post(reverse('core:purchase_order_import_preview'), {'file': self.upload(
            [['物料名称', '数量', '未税单价']] + [[self.part.name_zh, 1, 2]] * 532)})
        self.assertEqual(result.status_code, 400)


class WeatherFeedbackTests(FeedbackTests):
    def test_local_day_boundary_station_separation_missing_hours_and_unverified_et0(self):
        first = MaxicomWeatherStation.objects.create(mdb_index=1, name='气象站一')
        second = MaxicomWeatherStation.objects.create(mdb_index=2, name='气象站二')
        start = datetime(2026, 11, 12, 16, tzinfo=utc.utc)  # 上海11月13日00:00
        for hour in range(24):
            MaxicomWeatherLog.objects.create(weather_station=first, timestamp=(start + timedelta(hours=hour)).strftime('%Y%m%d%H%M%S'),
                temperature=20, min_temp=10, max_temp=30, humidity=50, solar_radiation=1, wind_run=2, rainfall=0, et=0)
        MaxicomWeatherLog.objects.create(weather_station=second, timestamp='20261113000000',
            min_temp=11, max_temp=31, humidity=60, solar_radiation=5, wind_run=4, rainfall=7, et=9)
        # An observation at the next local midnight belongs to the following day.
        MaxicomWeatherLog.objects.create(weather_station=first, timestamp='20261113160000', rainfall=99)
        data = weather_report_data(date(2026, 11, 13), date(2026, 11, 14))
        daily = data['stations'][0]['days'][date(2026, 11, 13)]
        self.assertEqual(daily['observed_hours'], 24)
        self.assertEqual(daily['rainfall'], 0)
        self.assertEqual(daily['wind_run'], 48)
        self.assertEqual(daily['humidity'], 50)
        self.assertTrue(daily['complete'])
        self.assertIsNone(daily['et'])
        with patch('core.views.timezone.localdate', return_value=date(2026, 11, 14)):
            summary = self.client.get('/api/maxicom-dashboard')
        self.assertEqual(summary.status_code, 200, summary.content[:300])
        self.assertEqual(summary.json()['weather_period'], 'day')
        self.assertIsNone(summary.json()['weather_summary'][0]['et'])
        self.assertIsNone(summary.json()['et_trend'][0]['total_et'])
        self.assertEqual(data['stations'][1]['days'][date(2026, 11, 13)]['rainfall'], 7)
        response = self.client.get(reverse('core:weather_daily'), {'start': '2026-11-13', 'end': '2026-11-14'}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()['rows']
        missing = next(row for row in rows if row['date'] == '2026-11-14' and row['station'] == '气象站二')
        self.assertNotIn('rainfall', missing)
        self.assertIn('缺测', missing['notes'])
        page = self.client.get(reverse('core:weather_daily'), {'start': '2026-11-13', 'end': '2026-11-14'})
        self.assertContains(page, 'ET₀')
        self.assertContains(page, '24/24')
        self.assertContains(page, '没有可核实的 ET0')
        download = self.client.get(reverse('core:weather_daily'), {'start': '2026-11-13', 'end': '2026-11-14', 'format': 'xlsx'})
        self.assertEqual(download.status_code, 200)
        self.assertTrue(download.streaming)
        download.close()

    def test_invalid_dates_do_not_silently_expand_the_query(self):
        response = self.client.get(reverse('core:weather_daily'), {'start': '2026-11-30', 'end': '2026-11-01'})
        self.assertEqual(response.status_code, 400)
