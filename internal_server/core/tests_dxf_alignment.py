"""Public import workflow must independently verify a shape-preserving alignment."""
import json
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from . import dxf_pipeline_utils as utils
from .dxf_state import alignment_status, fit_snapshot
from .models import Pipeline, PipelineImportBatch, SiteCalibration
from .tests_dxf_integrity import ImportIntegrityTests, checks_for, drawing, translated


@override_settings(ALLOWED_HOSTS=['testserver'], CACHES={
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'dxf-alignment-default'},
    'dxffile': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'dxf-alignment-source'},
})
class AlignmentWorkflowTests(TestCase):
    setUp = ImportIntegrityTests.setUp
    import_preview = ImportIntegrityTests.import_preview

    def analyze_raw(self):
        response = self.client.post('/pipelines/dxf/analyze/', {
            'file': SimpleUploadedFile('drawing.dxf', drawing())})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def save(self, data, points=None, checks=None, method='sim'):
        points = translated(0) if points is None else points
        checks = checks_for(points) if checks is None else checks
        return self.client.post('/pipelines/dxf/calibration/save/', {
            'token': data['token'], 'pairs': json.dumps(points),
            'check_points': json.dumps(checks), 'method': method})

    def validated_preview(self):
        data = self.analyze_raw()
        saved = self.save(data)
        self.assertEqual(saved.status_code, 200, saved.content)
        refreshed = self.client.post('/pipelines/dxf/analyze/', {
            'token': data['token'], 'calibration_id': saved.json()['calibration']['id']})
        self.assertEqual(refreshed.status_code, 200, refreshed.content)
        return refreshed.json()

    def test_default_position_is_not_an_importable_map_preview(self):
        data = self.analyze_raw()
        self.assertFalse(data['alignment']['ready'])
        point = data['preview']['layers'][0]['paths'][0][0]
        self.assertEqual((point['dxf_x'], point['dxf_y']), (18100, -10100))
        self.assertNotIn('lat', point)
        self.assertNotIn('lng', point)
        self.assertEqual(self.import_preview(data).status_code, 400)
        self.assertEqual(Pipeline.objects.count(), 0)

    def test_only_shape_preserving_alignment_can_be_saved(self):
        data = self.analyze_raw()
        for method in ('tps', 'mls', 'exact2', 'auto', 'unknown'):
            with self.subTest(method=method):
                self.assertEqual(self.save(data, method=method).status_code, 400)
        self.assertEqual(SiteCalibration.objects.count(), 0)

    def test_requires_three_controls_and_an_independent_check(self):
        data = self.analyze_raw()
        cases = [
            (translated(0)[:2], checks_for(translated(0))),
            (translated(0), []),
            (translated(0), [translated(0)[0]]),
            (translated(0) + [translated(0)[0]], checks_for(translated(0))),
            (translated(0), checks_for(translated(0)) * 2),
        ]
        for points, checks in cases:
            with self.subTest(points=len(points), checks=len(checks)):
                self.assertEqual(self.save(data, points, checks).status_code, 400)
        self.assertEqual(SiteCalibration.objects.count(), 0)

    def test_collinear_controls_cannot_validate_a_drawing(self):
        fn, _ = fit_snapshot({'points': translated(0), 'method': 'sim'})
        points = []
        for x in (18100, 18120, 18140):
            lat, lng = fn(x, 10100)
            points.append({'dxf_x': x, 'dxf_y': -10100, 'lat': lat, 'lng': lng})
        self.assertEqual(self.save(self.analyze_raw(), points).status_code, 400)

    def test_wrong_check_point_rejects_a_perfect_fit_without_saving(self):
        data = self.analyze_raw()
        checks = checks_for(translated(0))
        checks[0]['lat'] += .0001  # More than 11 m, despite zero control residuals.
        response = self.save(data, checks=checks)
        self.assertEqual(response.status_code, 400)
        self.assertGreater(response.json()['alignment']['check_max_m'], 10)
        self.assertEqual(SiteCalibration.objects.count(), 0)

    def test_checks_are_excluded_from_fitting_and_frozen_with_preview(self):
        data = self.analyze_raw()
        checks = checks_for(translated(0))
        checks[0]['lat'] += .00001
        saved = self.save(data, checks=checks)
        self.assertEqual(saved.status_code, 200, saved.content)
        row = SiteCalibration.objects.get()
        self.assertEqual(row.points, translated(0))
        self.assertEqual(row.check_points, checks)
        self.assertAlmostEqual(saved.json()['calibration']['alignment']['check_max_m'], 1.1132, places=3)
        refreshed = self.client.post('/pipelines/dxf/analyze/', {'token': data['token']}).json()
        self.assertTrue(refreshed['alignment']['ready'])
        self.assertEqual(self.import_preview(refreshed).status_code, 200)
        pipe = Pipeline.objects.get()
        preview = refreshed['preview']['layers'][0]['paths'][0]
        self.assertEqual(pipe.line_points, [{k: p[k] for k in ('lat', 'lng')} for p in preview])
        self.assertEqual(pipe.import_batch.calibration_snapshot['check_points'], checks)

    def test_bad_control_is_rejected_even_if_checks_match_its_fit(self):
        points = translated(0)
        points[0]['lat'] += .002
        response = self.save(self.analyze_raw(), points)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SiteCalibration.objects.count(), 0)

    def test_free_drag_offsets_and_symbol_linework_cannot_be_imported(self):
        data = self.validated_preview()
        for extra in ({'offset_lat': '.0001'}, {'offset_lng': 'NaN'},
                      {'layers_json': json.dumps({'块·VALVE': {'include': True}})}):
            params = {'token': data['token'], 'preview_token': data['preview_token'],
                      'layers_json': json.dumps({'100': {'include': True}})}
            params.update(extra)
            self.assertEqual(self.client.post('/pipelines/dxf/import/', params).status_code, 400)
        self.assertEqual(PipelineImportBatch.objects.count(), 0)

    def test_legacy_warp_is_readable_but_cannot_be_activated(self):
        data = self.analyze_raw()
        row = SiteCalibration.objects.create(points=translated(0), method='mls',
                                            check_points=checks_for(translated(0)))
        self.assertFalse(alignment_status({'points': row.points, 'method': row.method,
                                          'check_points': row.check_points})['ready'])
        refreshed = self.client.post('/pipelines/dxf/analyze/', {'token': data['token']}).json()
        self.assertTrue(refreshed['preview']['layers'])
        self.assertFalse(refreshed['alignment']['ready'])
        response = self.client.post('/pipelines/dxf/calibration/apply/', {
            'confirm': '1', 'calibration_id': row.id, 'batch_ids': '[1]', 'force': '1'})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(SiteCalibration.objects.filter(pk=row.id).exists())

    def test_reposition_removes_old_drag_offset_and_preserves_manual_correction(self):
        data = self.analyze_raw()
        utils.import_dxf_pipelines({'100': {'include': True}}, {}, token=data['token'],
                                   offset=(.0004, -.0003), imported_by=self.user)
        pipe = Pipeline.objects.get()
        pipe.line_points[0]['lat'] += .00001
        pipe.save(update_fields=['line_points'])
        saved = self.save(data)
        self.assertEqual(saved.status_code, 200, saved.content)
        response = self.client.post('/pipelines/dxf/calibration/apply/', {
            'confirm': '1', 'calibration_id': saved.json()['calibration']['id'],
            'batch_ids': json.dumps([pipe.import_batch_id]), 'force': '1'})
        self.assertEqual(response.status_code, 200, response.content)
        pipe.refresh_from_db()
        fn, _ = fit_snapshot({'points': translated(0), 'method': 'sim'})
        lat, lng = fn(18100, 10100)
        self.assertAlmostEqual(pipe.line_points[0]['lat'], lat + .00001, places=7)
        self.assertAlmostEqual(pipe.line_points[0]['lng'], lng, places=7)
        self.assertAlmostEqual(pipe.source_map_points[0]['lat'], lat, places=7)
        self.assertEqual(pipe.import_batch.import_options['offset'], [0, 0])
        backup = json.loads((Path(settings.BASE_DIR) / 'pipeline_backups' / response.json()['backup']).read_text())
        self.assertEqual(backup['batches'][0]['import_options']['offset'], [.0004, -.0003])

    def test_existing_batch_exposes_original_cad_for_repositioning(self):
        data = self.validated_preview()
        self.assertEqual(self.import_preview(data).status_code, 200)
        batch = PipelineImportBatch.objects.get()
        response = self.client.get('/pipelines/edit/data/', {'batch_id': batch.id})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['cad_source'], batch.source_geometry)
        self.assertEqual(response.json()['cad_options'], batch.import_options)

    def test_large_reposition_requires_explicit_force_and_does_not_move_early(self):
        data = self.validated_preview()
        self.assertEqual(self.import_preview(data).status_code, 200)
        pipe = Pipeline.objects.get()
        before = pipe.line_points
        points = translated(0)
        anchor = points[0]
        scaled = [dict(p, lat=anchor['lat'] + 2*(p['lat']-anchor['lat']),
                       lng=anchor['lng'] + 2*(p['lng']-anchor['lng'])) for p in points]
        saved = self.save(data, scaled)
        self.assertEqual(saved.status_code, 200, saved.content)
        params = {'confirm': '1', 'calibration_id': saved.json()['calibration']['id'],
                  'batch_ids': json.dumps([pipe.import_batch_id])}
        response = self.client.post('/pipelines/dxf/calibration/apply/', params)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertTrue(response.json()['need_force'])
        pipe.refresh_from_db()
        self.assertEqual(pipe.line_points, before)
        response = self.client.post('/pipelines/dxf/calibration/apply/', dict(params, force='1'))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['backup'])
        pipe.refresh_from_db()
        self.assertNotEqual(pipe.line_points, before)

    def test_page_offers_guided_steps_without_legacy_positioning_controls(self):
        response = self.client.get('/pipelines/dxf/')
        self.assertEqual(response.status_code, 200)
        for text in ('独立检查点', '选择要导入的内容', '检查并导入', 'CAD 原图', 'pdxfReviewConfirmed'):
            self.assertContains(response, text)
        for text in ('dxf-tune.js', 'pdxfCalMethod', 'TPS', 'MLS', 'exact2', '拖动整体'):
            self.assertNotContains(response, text)

    def test_initial_overlay_and_alignment_share_one_main_map(self):
        response = self.client.get('/pipelines/dxf/')
        html = response.content.decode()
        workspace = html.split('<div class="pdxf-map-grid">', 1)[1].split('</section>', 1)[0]
        self.assertIn('id="pdxfMap"', workspace)
        self.assertNotIn('id="pdxfCadMap"', workspace)
        original_dialog = html.split('<dialog id="pdxfOriginalDialog"', 1)[1].split('</dialog>', 1)[0]
        self.assertIn('id="pdxfCadMap"', original_dialog)
        self.assertContains(response, 'dxf-placement.js')
        self.assertContains(response, '初步叠图用于辨认线条')
        self.assertContains(response, 'CAD 会临时隐藏')
