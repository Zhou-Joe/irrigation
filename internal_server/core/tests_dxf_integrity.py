"""CAD completeness and preview/commit/recalibration integrity regressions."""
import io
import importlib
import json
import math
from unittest.mock import patch

import ezdxf
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings

from . import dxf_pipeline_utils as utils, dxf_views
from .calibration import SITE_CALIBRATION_POINTS
from .dxf_state import calibration_snapshot, fit_snapshot
from .models import Pipeline, PipelineImportBatch, SiteCalibration


def drawing(build=None):
    doc = ezdxf.new()
    if build:
        build(doc)
    else:
        doc.modelspace().add_line((18100, -10100), (18120, -10120),
                                 dxfattribs={'layer': '100'})
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode()


def translated(delta):
    fn,_=fit_snapshot({'points': SITE_CALIBRATION_POINTS, 'method':'sim'})
    la,ln=fn(18100,10000)
    points=SITE_CALIBRATION_POINTS+[{'dxf_x':18100,'dxf_y':-10000,'lat':la,'lng':ln}]
    return [dict(p, lat=p['lat'] + delta) for p in points]

def checks_for(points, method='sim'):
    fn,_=fit_snapshot({'points':points,'method':method})
    la,ln=fn(18105,10010)
    return [{'dxf_x':18105,'dxf_y':-10010,'lat':la,'lng':ln}]


class GeometryIntegrityTests(SimpleTestCase):
    def test_plain_text_insert_is_supported(self):
        doc = ezdxf.new()
        doc.modelspace().add_text('Valve 1', dxfattribs={'insert': (100, 200)})
        labels = utils._collect_geometry(doc.modelspace())[2]
        self.assertEqual((labels[0]['x'], labels[0]['y']), (100, 200))

    def test_open_curve_preserves_its_last_endpoint(self):
        doc = ezdxf.new()
        curve = doc.modelspace().add_ellipse((0, 0), (10000, 0), .5,
                                             start_param=0, end_param=math.pi)
        points, closed = utils._flatten_curve(curve)
        self.assertFalse(closed)
        self.assertEqual(points[0], (10000, 0))
        self.assertAlmostEqual(points[-1][0], -10000, places=3)
        self.assertNotEqual(points[0], points[-1])

    def test_ocs_polyline_is_converted_to_wcs(self):
        doc = ezdxf.new()
        line = doc.modelspace().add_lwpolyline([(10, 20), (30, 40)],
                                              dxfattribs={'extrusion': (0, 0, -1)})
        points, _ = utils._entity_polyline(line)
        self.assertEqual(points, [(-10, 20), (-30, 40)])

    def test_multi_insert_and_nested_notes_are_kept(self):
        doc = ezdxf.new()
        block = doc.blocks.new('VALVE')
        block.add_line((0, 0), (5, 0))
        block.add_mtext('Full valve note', dxfattribs={'insert': (2, 1)})
        doc.modelspace().add_blockref('VALVE', (0, 0),
                                     dxfattribs={'column_count': 3, 'column_spacing': 10})
        layers, valves, labels = utils._collect_geometry(doc.modelspace())
        self.assertEqual(len(layers['块·VALVE']['polys']), 3)
        self.assertEqual(len(valves), 3)
        self.assertEqual(len(labels), 3)
        self.assertEqual([v['x'] for v in valves], [0, 10, 20])


@override_settings(ALLOWED_HOSTS=['testserver'], CACHES={
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'dxf-integrity-default'},
    'dxffile': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'dxf-integrity-source'},
})
class ImportIntegrityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('cad_integrity', 'cad@example.test', 'x')
        self.client.force_login(self.user)
        from django.core.cache import cache
        cache.clear()
        utils._bust_calibration_cache()
        self.addCleanup(utils._bust_calibration_cache)
        self.zones = patch.object(utils, '_load_zone_data', return_value=([], {}))
        self.zones.start()
        self.addCleanup(self.zones.stop)

    def analyze(self, content=None):
        response = self.client.post('/pipelines/dxf/analyze/', {
            'file': SimpleUploadedFile('drawing.dxf', content or drawing())})
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertTrue(data['success'], data)
        # These integrity tests exercise validated imports; independent controls
        # are generated from a known fixture transform, never from UI inverse fits.
        info=data['calibration']
        if not info['alignment']['ready']:
            row=SiteCalibration.objects.filter(pk=info.get('id')).first()
            if row is None:
                row=SiteCalibration.objects.create(points=translated(0),method='sim',drawing_token=data['token'])
            row.check_points=checks_for(row.points,row.method);row.save(update_fields=['check_points'])
            data=self.client.post('/pipelines/dxf/analyze/',{'token':data['token']}).json()
        return data

    def import_preview(self, data):
        return self.client.post('/pipelines/dxf/import/', {
            'token': data['token'], 'preview_token': data['preview_token'],
            'layers_json': json.dumps({'100': {'include': True}}),
            'blocks_json': '{}', 'label_layers': '[]'})

    def apply(self, calibration_id, batch_id=None):
        params = {'confirm': '1', 'calibration_id': calibration_id, 'force': '1'}
        row=SiteCalibration.objects.get(pk=calibration_id)
        if row.method!='sim' or not batch_id:
            from .dxf_reproject import apply_calibration
            from django.http import JsonResponse
            return JsonResponse(apply_calibration(calibration_id,[batch_id] if batch_id else None,True))
        row.check_points=checks_for(row.points);row.save(update_fields=['check_points'])
        if batch_id:
            params['batch_ids'] = json.dumps([batch_id])
        return self.client.post('/pipelines/dxf/calibration/apply/', params)

    def test_preview_contains_all_layers_blocks_and_original_coordinates(self):
        def build(doc):
            for i in range(14):
                doc.modelspace().add_line((18100, -10100), (18101, -10101),
                                           dxfattribs={'layer': str(i)})
            for i in range(601):
                doc.modelspace().add_line((18100 + i/1000, -10100), (18101, -10101),
                                           dxfattribs={'layer': '100'})
            b = doc.blocks.new('VALVE')
            b.add_line((0, 0), (1, 0))
            doc.modelspace().add_blockref('VALVE', (18100, -10100))
        data = self.analyze(drawing(build))
        previews = {p['layer']: p['paths'] for p in data['preview']['layers']}
        self.assertEqual(len(previews), 16)
        self.assertEqual(len(previews['100']), 601)
        self.assertIn('块·VALVE', previews)
        self.assertEqual(previews['100'][0][0]['dxf_x'], 18100)

    def test_import_uses_reviewed_calibration_and_persists_source(self):
        a = SiteCalibration.objects.create(points=translated(0), method='sim')
        data = self.analyze()
        SiteCalibration.objects.create(points=translated(.001), method='sim')
        utils._bust_calibration_cache()
        response = self.import_preview(data)
        self.assertEqual(response.status_code, 200, response.content)
        p = Pipeline.objects.get()
        self.assertEqual(p.line_points, [{k: v for k, v in pt.items() if k in ('lat', 'lng')}
                                        for pt in data['preview']['layers'][0]['paths'][0]])
        self.assertEqual(p.source_points, [[18100, -10100], [18120, -10120]])
        self.assertEqual(p.import_batch.calibration_snapshot['id'], a.id)

    def test_import_requires_authentic_matching_preview(self):
        data = self.analyze()
        for preview in ['', data['preview_token'] + 'invalid']:
            data['preview_token'] = preview
            response = self.import_preview(data)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(Pipeline.objects.count(), 0)

    def test_bad_calibration_save_does_not_change_active_state(self):
        a = SiteCalibration.objects.create(points=translated(0), method='sim')
        points = translated(0) + [dict(translated(0)[0], dxf_x=19000, lat=31.2)]
        response = self.client.post('/pipelines/dxf/calibration/save/',
                                    {'pairs': json.dumps(points), 'check_points':json.dumps(checks_for(translated(0))), 'method': 'sim'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SiteCalibration.objects.count(), 1)
        self.assertEqual(calibration_snapshot()['id'], a.id)

    def test_drawing_reset_does_not_change_another_drawing(self):
        global_row = SiteCalibration.objects.create(points=translated(.001), method='sim')
        data = self.analyze()
        response = self.client.post('/pipelines/dxf/calibration/clear/', {'token': data['token']})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(calibration_snapshot(data['token'])['id'], 0)
        self.assertEqual(calibration_snapshot('another-drawing')['id'], global_row.id)

    def test_drawing_calibration_save_is_scoped(self):
        data = self.analyze()
        response = self.client.post('/pipelines/dxf/calibration/save/', {
            'token': data['token'], 'pairs': json.dumps(translated(.001)), 'check_points':json.dumps(checks_for(translated(.001))), 'method': 'sim'})
        self.assertEqual(response.status_code, 200, response.content)
        row_id = response.json()['calibration']['id']
        self.assertEqual(calibration_snapshot(data['token'])['id'], row_id)
        self.assertEqual(calibration_snapshot('another-drawing')['id'], 0)

    def test_degenerate_control_points_are_rejected(self):
        for points in ([translated(0)[0]]*2,
                       [translated(0)[0], dict(translated(0)[1], lat=translated(0)[0]['lat'],
                                               lng=translated(0)[0]['lng'])]):
            response = self.client.post('/pipelines/dxf/calibration/save/', {
                'pairs': json.dumps(points), 'method': 'sim'})
            self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(SiteCalibration.objects.count(), 0)

    def test_preview_cannot_be_reused_by_another_user(self):
        data = self.analyze()
        other = User.objects.create_superuser('other_cad', 'other@example.test', 'x')
        self.client.force_login(other)
        self.assertEqual(self.import_preview(data).status_code, 400)
        self.assertEqual(PipelineImportBatch.objects.count(), 0)

    def test_preview_rejects_a_different_uploaded_file(self):
        data = self.analyze()
        response = self.client.post('/pipelines/dxf/import/', {
            'token': data['token'], 'preview_token': data['preview_token'],
            'file': SimpleUploadedFile('changed.dxf', drawing(lambda doc: doc.modelspace().add_line((0,0),(1,1)))),
            'layers_json': json.dumps({'100':{'include':True}})})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PipelineImportBatch.objects.count(), 0)

    def test_clear_retains_history_and_recalibration_uses_originals(self):
        a = SiteCalibration.objects.create(points=translated(.001), method='sim')
        data = self.analyze()
        self.assertEqual(self.import_preview(data).status_code, 200)
        batch = PipelineImportBatch.objects.get()
        self.assertEqual(self.client.post('/pipelines/dxf/calibration/clear/').status_code, 200)
        self.assertTrue(SiteCalibration.objects.filter(pk=a.id).exists())
        a.refresh_from_db()
        self.assertFalse(a.is_active)
        b = SiteCalibration.objects.create(points=translated(.002), method='sim')
        response = self.apply(b.id, batch.id)
        self.assertEqual(response.status_code, 200, response.content)
        p = Pipeline.objects.get()
        fn, _ = fit_snapshot(calibration_snapshot(calibration_id=b.id))
        want = fn(18100, 10100)
        self.assertAlmostEqual(p.line_points[0]['lat'], want[0], places=6)
        self.assertAlmostEqual(p.line_points[0]['lng'], want[1], places=6)

    def test_identical_nonlinear_calibration_is_a_noop(self):
        points = []
        k = math.cos(math.radians(31))
        for x, y, shift in [(0,0,0), (500,0,0), (0,500,0), (500,500,0), (250,250,2)]:
            points.append({'dxf_x': x, 'dxf_y': y, 'lat': 31+(y+shift)/111320,
                           'lng': 121+x/(111320*k)})
        a = SiteCalibration.objects.create(points=points, method='mls')
        snapshot = calibration_snapshot(calibration_id=a.id)
        fn, _ = fit_snapshot(snapshot)
        baseline = [dict(zip(('lat', 'lng'), fn(x, -y))) for x, y in [(100,250),(200,250)]]
        batch = PipelineImportBatch.objects.create(name='MLS', calibration_snapshot=snapshot,
                                                   applied_calibration=snapshot)
        p = Pipeline.objects.create(name='MLS', code='MLS', import_batch=batch,
                                     line_points=baseline, source_map_points=baseline,
                                     source_points=[[100,250],[200,250]])
        b = SiteCalibration.objects.create(points=points, method='mls')
        response = self.apply(b.id, batch.id)
        self.assertEqual(response.status_code, 200, response.content)
        p.refresh_from_db()
        self.assertEqual(p.line_points, baseline)

    def test_manual_vertex_adjustment_is_preserved_and_apply_is_idempotent(self):
        SiteCalibration.objects.create(points=translated(0), method='sim')
        data = self.analyze()
        self.assertEqual(self.import_preview(data).status_code, 200)
        p = Pipeline.objects.get()
        baseline = p.source_map_points[0]['lat']
        p.line_points[0]['lat'] += .00001
        p.save(update_fields=['line_points'])
        b = SiteCalibration.objects.create(points=translated(.001), method='sim')
        self.assertEqual(self.apply(b.id, p.import_batch_id).status_code, 200)
        p.refresh_from_db()
        self.assertAlmostEqual(p.line_points[0]['lat'] - p.source_map_points[0]['lat'], .00001, places=7)
        self.assertAlmostEqual(p.source_map_points[0]['lat'] - baseline, .001, delta=1e-6)
        before = p.line_points
        self.assertEqual(self.apply(b.id, p.import_batch_id).status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.line_points, before)

    def test_topology_edit_aborts_recalibration_before_any_write(self):
        SiteCalibration.objects.create(points=translated(0), method='sim')
        data = self.analyze()
        self.assertEqual(self.import_preview(data).status_code, 200)
        p = Pipeline.objects.get()
        p.line_points.append({'lat':31, 'lng':121})
        p.save(update_fields=['line_points'])
        b = SiteCalibration.objects.create(points=translated(.001), method='sim')
        before = p.line_points
        self.assertEqual(self.apply(b.id, p.import_batch_id).status_code, 400)
        p.refresh_from_db(); b.refresh_from_db()
        self.assertEqual(p.line_points, before)
        self.assertIsNone(b.applied_at)

    def test_manual_features_are_not_recalibrated(self):
        p = Pipeline.objects.create(name='Manual', code='MAN',
                                     line_points=[{'lat':31,'lng':121},{'lat':31.1,'lng':121}])
        a = SiteCalibration.objects.create(points=translated(.001), method='sim')
        before = p.line_points
        response = self.apply(a.id)
        self.assertEqual(response.status_code, 200, response.content)
        p.refresh_from_db()
        self.assertEqual(p.line_points, before)

    def test_unmatched_valves_and_full_notes_are_retained(self):
        note = 'Valve maintenance instructions ' * 5
        def build(doc):
            doc.modelspace().add_line((18100,-10100),(18120,-10120),dxfattribs={'layer':'100'})
            b=doc.blocks.new('WID_Val-cf'); b.add_circle((0,0),1)
            doc.modelspace().add_blockref('WID_Val-cf',(18000,-10000))
            doc.modelspace().add_mtext(note,dxfattribs={'layer':'NOTES','insert':(18100,-10100)})
        data=self.analyze(drawing(build))
        result=utils.import_dxf_pipelines({'100':{'include':True}},
                {'WID_Val-cf':{'include':True}},token=data['token'],
                preview_token=data['preview_token'], imported_by=self.user)
        self.assertEqual(result['skipped_valves'],1)
        batch=PipelineImportBatch.objects.get()
        self.assertEqual(len(batch.source_geometry['unmatched_valves']),1)
        self.assertEqual(batch.source_geometry['labels'][0]['text'],note.strip())
        payload = self.client.get('/api/pipelines-payload/').json()
        self.assertEqual(len(payload['cad_reference'][0]['unmatched_valves']), 1)
        self.assertEqual(payload['cad_reference'][0]['labels'][0]['text'], note.strip())

    def test_import_page_renders_batch_controls(self):
        batch = PipelineImportBatch.objects.create(name='Reviewed drawing')
        response = self.client.get('/pipelines/dxf/')
        self.assertContains(response, 'id="pdxfCalBatch"')
        self.assertContains(response, 'Reviewed drawing')
        self.assertIn('csrftoken', response.cookies)

    def test_calibration_cannot_bypass_drawing_scope_with_batch_id(self):
        data = self.analyze()
        batch = PipelineImportBatch.objects.create(name='Other drawing', source_token='other')
        for batch_id in ('invalid', batch.id):
            response = self.client.post('/pipelines/dxf/calibration/save/', {
                'token': data['token'], 'batch_id': batch_id,
                'pairs': json.dumps(translated(0)), 'check_points':json.dumps(checks_for(translated(0))), 'method': 'sim'})
            self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(SiteCalibration.objects.count(), 1)

    def test_legacy_global_reset_preserves_drawing_scoped_calibrations(self):
        global_row = SiteCalibration.objects.create(points=translated(0), method='sim')
        scoped = SiteCalibration.objects.create(points=translated(.001), method='sim', drawing_token='other')
        self.assertEqual(self.client.post('/pipelines/dxf/calibration/clear/').status_code, 200)
        global_row.refresh_from_db(); scoped.refresh_from_db()
        self.assertFalse(global_row.is_active)
        self.assertTrue(scoped.is_active)

    def test_edit_data_uses_batch_transform_instead_of_latest_calibration(self):
        a = SiteCalibration.objects.create(points=translated(0), method='sim')
        data = self.analyze()
        self.assertEqual(self.import_preview(data).status_code, 200)
        batch = PipelineImportBatch.objects.get()
        SiteCalibration.objects.create(points=translated(.001), method='sim')
        response = self.client.get('/pipelines/edit/data/')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['batch_calibrations'][str(batch.pk)]['id'], a.id)

    def test_apply_changes_only_the_selected_batch(self):
        SiteCalibration.objects.create(points=translated(0), method='sim')
        data = self.analyze()
        self.assertEqual(self.import_preview(data).status_code, 200)
        first = Pipeline.objects.get()
        self.assertEqual(self.import_preview(data).status_code, 200)
        second = Pipeline.objects.exclude(pk=first.pk).get()
        before = second.line_points
        b = SiteCalibration.objects.create(points=translated(.001), method='sim')
        self.assertEqual(self.apply(b.pk, first.import_batch_id).status_code, 200)
        first.refresh_from_db(); second.refresh_from_db()
        self.assertNotEqual(first.line_points, before)
        self.assertEqual(second.line_points, before)
        self.assertNotEqual(second.import_batch.applied_calibration['id'], b.pk)

    def test_invalid_import_coordinates_roll_back_the_entire_batch(self):
        data = self.analyze()
        for offset in ('not-a-number', 'NaN', '1000'):
            response = self.client.post('/pipelines/dxf/import/', {
                'token': data['token'], 'preview_token': data['preview_token'],
                'offset_lat': offset, 'layers_json': json.dumps({'100': {'include': True}})})
            self.assertEqual(response.status_code, 400, response.content)
            self.assertEqual(PipelineImportBatch.objects.count(), 0)
            self.assertEqual(Pipeline.objects.count(), 0)

    def test_migration_freezes_import_and_effective_calibrations(self):
        from django.apps import apps
        from django.db import connection
        from types import SimpleNamespace
        a = SiteCalibration.objects.create(points=translated(0), method='sim')
        batch = PipelineImportBatch.objects.create(name='Legacy batch')
        b = SiteCalibration.objects.create(points=translated(.001), method='sim')
        from django.utils import timezone
        SiteCalibration.objects.filter(pk=b.pk).update(applied_at=timezone.now())
        migration = importlib.import_module('core.migrations.0129_dxf_source_and_calibration_state')
        migration.freeze_existing_batch_calibrations(apps, SimpleNamespace(connection=connection))
        batch.refresh_from_db()
        self.assertEqual(batch.calibration_snapshot['id'], a.pk)
        self.assertEqual(batch.applied_calibration['id'], b.pk)
        SiteCalibration.objects.create(points=translated(.002), method='sim', applied_at=timezone.now())
        self.assertEqual(batch.applied_calibration['id'], b.pk)

    def test_changed_nonlinear_calibration_uses_exact_source_coordinates(self):
        k = math.cos(math.radians(31))
        points = [{'dxf_x': x, 'dxf_y': y, 'lat': 31+(y+shift)/111320,
                   'lng': 121+x/(111320*k)}
                  for x,y,shift in [(0,0,0),(500,0,0),(0,500,0),(500,500,0),(250,250,2)]]
        a = SiteCalibration.objects.create(points=points, method='mls')
        old = calibration_snapshot(calibration_id=a.pk)
        fn, _ = fit_snapshot(old)
        source = [[100,250],[200,250]]
        baseline = [dict(zip(('lat','lng'),fn(x,-y))) for x,y in source]
        batch = PipelineImportBatch.objects.create(name='MLS sources',calibration_snapshot=old,
                                                   applied_calibration=old)
        pipe = Pipeline.objects.create(name='MLS sources',code='MLS-SOURCE',import_batch=batch,
                                        line_points=baseline,source_map_points=baseline,source_points=source)
        b = SiteCalibration.objects.create(points=[dict(p,lat=p['lat']+.001) for p in points],method='mls')
        self.assertEqual(self.apply(b.pk,batch.pk).status_code,200)
        pipe.refresh_from_db()
        fn,_ = fit_snapshot(calibration_snapshot(calibration_id=b.pk))
        for raw, result in zip(source,pipe.line_points):
            expected = fn(raw[0],-raw[1])
            self.assertAlmostEqual(result['lat'],expected[0],places=7)
            self.assertAlmostEqual(result['lng'],expected[1],places=7)
        self.assertEqual(pipe.source_points,source)

    # 本测试全局 mock Path.open；默认 LOGGING 的 AdminEmailHandler 对 ≥400
    # 响应渲染技术错误页也要 Path.open 读模板（DEBUG=False 时生效），会二次
    # 炸出测试。DEBUG=True 走 console handler，视图受控 500 正常返回。
    @override_settings(DEBUG=True)
    def test_backup_failure_aborts_before_coordinate_writes(self):
        SiteCalibration.objects.create(points=translated(0),method='sim')
        data = self.analyze()
        self.assertEqual(self.import_preview(data).status_code,200)
        pipe = Pipeline.objects.get()
        before = pipe.line_points
        b = SiteCalibration.objects.create(points=translated(.001),method='sim')
        with patch('core.dxf_reproject.Path.open',side_effect=OSError('disk unavailable')):
            response = self.apply(b.pk,pipe.import_batch_id)
        self.assertEqual(response.status_code,500)
        pipe.refresh_from_db(); b.refresh_from_db()
        self.assertEqual(pipe.line_points,before)
        self.assertIsNone(b.applied_at)
