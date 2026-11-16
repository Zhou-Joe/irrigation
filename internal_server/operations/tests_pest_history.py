import hashlib
import json
import tempfile
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from django.core.management import call_command
from django.test import TestCase, override_settings

from core.models import WorkReport, Worker
from .history_import import import_history
from .models import (BusinessArea, Location, PestHistoryImport, PestHistoryRecord,
                     ReferenceCatalog, ReferenceNode, Team)


class PestHistoryImportTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = self.root / 'private'
        override = override_settings(PEST_WORKORDER_PRIVATE_ROOT=self.private)
        override.enable(); self.addCleanup(override.disable)
        business = BusinessArea.objects.create(code='pest-control', name='Pest')
        self.team = Team.objects.create(business=business, code='pest-test', name='Pest team')
        output = BytesIO(); Image.new('RGB', (4, 4), 'green').save(output, format='PNG')
        image = output.getvalue(); (self.root / 'media').mkdir()
        (self.root / 'media' / 'observation.png').write_bytes(image)
        self.manifest = {'schema_version': 1, 'team_business_code': 'pest-control',
            'source': {'name': 'private-fixture.xlsx', 'sha256': 'a' * 64},
            'controlled_options': {'side_of_building': ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'],
                                   'status': ['Alive', 'Dead', 'No birds found']},
            'exclusions': [{'reason': 'Template row excluded'}], 'records': [{
                'source_no': 1, 'source_sheet': 'Records', 'source_row': 3,
                'source_key': 'source-specific-original-key', 'date': '2024-03-04', 'time': '08:15',
                'parent_code': 'TEST-AREA', 'parent_name': 'Test area',
                'building_code': 'TEST-BLDG', 'building_name': 'Building A',
                'location_detail': '大堂', 'object_name': 'Bird (unidentified)',
                'completion_outcome': None, 'completion_note': 'Observation only',
                'parameters': {'side_of_building': 'N', 'species_alpha_code': None, 'status': None,
                               'weather': 'Cloudy', 'reported_by': 'Source observer', 'notes': 'Found outside'},
                'original_cells': {'A3': {'value': '1'}}, 'warnings': ['Source outcome missing'],
                'media': [{'path': 'media/observation.png', 'bytes': len(image),
                           'sha256': hashlib.sha256(image).hexdigest()}],
            }]}
        self.path = self.root / 'manifest.json'
        self.write_manifest()

    def write_manifest(self):
        self.path.write_text(json.dumps(self.manifest, ensure_ascii=False))

    def test_dry_run_has_no_business_or_storage_side_effects(self):
        summary = import_history(self.path, self.team)
        self.assertEqual(summary['new_records'], 1)
        self.assertEqual(summary['new_locations'], 3)
        self.assertEqual(summary['photos'], 1)
        self.assertFalse(summary['applied'])
        self.assertEqual(WorkReport.all_businesses.count(), 0)
        self.assertEqual(Location.objects.count(), 0)
        self.assertEqual(ReferenceCatalog.objects.count(), 0)
        self.assertFalse(self.private.exists())
        stdout = StringIO()
        call_command('import_pest_history', str(self.path), team=self.team.code, stdout=stdout)
        self.assertFalse(json.loads(stdout.getvalue())['applied'])

    def test_apply_preserves_observations_and_building_binding_without_fabricated_work(self):
        result = import_history(self.path, self.team, apply=True)
        self.assertEqual(result['new_records'], 1)
        report = WorkReport.all_businesses.get()
        source = report.history_source
        self.assertEqual(source.source_key, '1')
        self.assertEqual(source.source_sheet, 'Records')
        self.assertEqual(source.source_row, 3)
        self.assertEqual(source.original['original_cells'], {'A3': {'value': '1'}})
        self.assertEqual(source.observations['reported_by'], 'Source observer')
        self.assertEqual(source.observations['observed_time'], '08:15')
        self.assertIsNone(source.observations['status'])
        self.assertIsNone(source.observations['completion_outcome'])
        self.assertEqual(report.team_size, 0)
        self.assertEqual(report.team_hours, 0)
        self.assertIsNone(report.work_start_time)
        self.assertIsNone(report.work_end_time)
        self.assertFalse(report.is_pm)
        self.assertFalse(report.worker.active)
        self.assertIsNone(report.worker.user_id)
        self.assertEqual(WorkReport.objects.count(), 0)
        self.assertEqual(report.pest_data.locations.get().kind, 'room')
        building = Location.objects.get(code='TEST-BLDG')
        field = report.pest_data.parameters['locations'][0]
        self.assertEqual(field['location_id'], str(building.pk))
        self.assertEqual(field['key'], 'impact_direction')
        self.assertEqual(field['value'], 'N')
        self.assertEqual(report.pest_data.selections[0]['path'], ['野生动物', '鸟类', '撞击事件记录'])
        self.assertEqual(len(report.photos), 1)
        self.assertEqual(sum(1 for p in self.private.rglob('*') if p.is_file()), 1)
        self.assertTrue(all(p.latitude is None and p.longitude is None for p in Location.objects.all()))

    def test_reapply_is_idempotent_and_keeps_current_team_catalog(self):
        import_history(self.path, self.team, apply=True)
        self.team.refresh_from_db(); catalog_id = self.team.work_catalog_id
        summary = import_history(self.path, self.team, apply=True)
        self.assertEqual(summary['new_records'], 0)
        self.assertEqual(summary['existing_records'], 1)
        self.assertEqual(WorkReport.all_businesses.count(), 1)
        self.assertEqual(PestHistoryImport.objects.count(), 1)
        self.assertEqual(PestHistoryRecord.objects.count(), 1)
        self.team.refresh_from_db(); self.assertEqual(self.team.work_catalog_id, catalog_id)
        self.assertEqual(sum(1 for p in self.private.rglob('*') if p.is_file()), 1)

    def test_changed_source_record_is_not_overwritten_or_duplicated(self):
        import_history(self.path, self.team, apply=True)
        self.manifest['records'][0]['parameters']['weather'] = 'Updated'
        self.manifest['source']['sha256'] = 'b' * 64
        self.write_manifest()
        with self.assertRaisesMessage(ValueError, '内容有变化'):
            import_history(self.path, self.team, apply=True)
        self.assertEqual(WorkReport.all_businesses.count(), 1)
        self.assertEqual(PestHistoryImport.objects.count(), 1)
        self.assertEqual(WorkReport.all_businesses.get().weather, 'Cloudy')

    def test_media_tampering_and_traversal_are_rejected_before_writes(self):
        for change in ({'path': '../outside.png'}, {'sha256': 'b' * 64}, {'bytes': 1}):
            original = dict(self.manifest['records'][0]['media'][0])
            self.manifest['records'][0]['media'][0].update(change); self.write_manifest()
            with self.assertRaises(ValueError):
                import_history(self.path, self.team, apply=True)
            self.manifest['records'][0]['media'][0] = original
        self.assertEqual(WorkReport.all_businesses.count(), 0)
        self.assertFalse(self.private.exists())

    def test_invalid_records_and_wrong_business_do_not_create_partial_data(self):
        for change in ({'source_no': True}, {'date': 'invalid'}, {'date': '2099-01-01'},
                       {'completion_outcome': 'disposed'}, {'parameters': {'side_of_building': 'wrong'}}):
            original = dict(self.manifest['records'][0])
            self.manifest['records'][0].update(change); self.write_manifest()
            with self.assertRaises(ValueError):
                import_history(self.path, self.team, apply=True)
            self.manifest['records'][0] = original
        self.write_manifest()
        irrigation = BusinessArea.objects.create(code='irrigation', name='Irrigation')
        other = Team.objects.create(business=irrigation, code='irrigation-test', name='Other team')
        with self.assertRaises(ValueError):
            import_history(self.path, other, apply=True)
        self.assertEqual(Location.objects.count(), 0)
        self.assertEqual(WorkReport.all_businesses.count(), 0)

    def test_rollback_removes_written_private_media_and_all_database_rows(self):
        with patch('operations.history_import.PestHistoryRecord.objects.create', side_effect=RuntimeError('Late failure')):
            with self.assertRaisesMessage(RuntimeError, 'Late failure'):
                import_history(self.path, self.team, apply=True)
        self.assertEqual(WorkReport.all_businesses.count(), 0)
        self.assertEqual(Location.objects.count(), 0)
        self.assertEqual(PestHistoryImport.objects.count(), 0)
        self.assertEqual(Worker.objects.count(), 0)
        self.assertFalse(any(p.is_file() for p in self.private.rglob('*')))

    def test_existing_catalog_and_other_team_locations_are_preserved(self):
        original = ReferenceCatalog.objects.create(business=self.team.business, owner_team=self.team,
            name='Existing', version='existing', source_name='Fixture')
        leaf = ReferenceNode.objects.create(catalog=original, label='Other work', kind='node',
            source_line=1, order=0, parameters=[{'key': 'note', 'label': 'Old field', 'type': 'text'}])
        self.team.work_catalog = original; self.team.save(update_fields=['work_catalog'])
        other = Team.objects.create(business=self.team.business, code='other', name='Other')
        foreign = Location.objects.create(owner_team=other, code='TEST-BLDG', name='Foreign building', kind='building')
        import_history(self.path, self.team, apply=True)
        self.team.refresh_from_db()
        self.assertNotEqual(self.team.work_catalog_id, original.pk)
        self.assertEqual(original.nodes.get().pk, leaf.pk)
        self.assertEqual(self.team.work_catalog.nodes.get(label='Other work').parameters[0]['key'], 'note')
        foreign.refresh_from_db()
        self.assertEqual(foreign.name, 'Foreign building')
        self.assertEqual(Location.objects.filter(code='TEST-BLDG').count(), 2)

    def test_dry_run_detects_existing_catalog_conflicts_before_any_write(self):
        catalog = ReferenceCatalog.objects.create(business=self.team.business, owner_team=self.team,
            name='Existing', version='conflict', source_name='Fixture')
        parent = None
        for line, label in enumerate(('野生动物', '鸟类', '撞击事件记录'), 1):
            parent = ReferenceNode.objects.create(catalog=catalog, parent=parent, label=label,
                kind='node', source_line=line, order=line)
        self.team.work_catalog = catalog; self.team.save(update_fields=['work_catalog'])
        with self.assertRaisesMessage(ValueError, '配置不同'):
            import_history(self.path, self.team)
        self.assertEqual(Location.objects.count(), 0)
        self.assertEqual(WorkReport.all_businesses.count(), 0)
        self.assertFalse(self.private.exists())

    def test_oversized_media_is_rejected_before_loading_any_attachment(self):
        original = self.manifest['records'][0]['media'][0]
        for media in ([dict(original) for _ in range(11)],
                      [{**original, 'bytes': 50 * 1024 * 1024 + 1}]):
            self.manifest['records'][0]['media'] = media; self.write_manifest()
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('Must not read oversized media')):
                with self.assertRaises(ValueError):
                    import_history(self.path, self.team, apply=True)
        self.assertEqual(WorkReport.all_businesses.count(), 0)
        self.assertFalse(self.private.exists())

    def test_whole_batch_limit_is_checked_before_loading_attachments(self):
        row = self.manifest['records'][0]
        row['media'] = [{**row['media'][0], 'bytes': 50 * 1024 * 1024} for _ in range(2)]
        second = {**row, 'source_no': 2}
        self.manifest['records'] = [row, second]; self.write_manifest()
        actual_stat = Path.stat

        def sized_media(path, *args, **kwargs):
            stat = actual_stat(path, *args, **kwargs)
            if path.suffix == '.png':
                from types import SimpleNamespace
                return SimpleNamespace(st_size=50 * 1024 * 1024, st_mode=stat.st_mode)
            return stat

        with patch.object(Path, 'stat', sized_media), patch.object(Path, 'read_bytes',
                side_effect=AssertionError('Must not read oversized batch')):
            with self.assertRaisesMessage(ValueError, '100 MB'):
                import_history(self.path, self.team)
        self.assertEqual(WorkReport.all_businesses.count(), 0)
        self.assertFalse(self.private.exists())

    def test_apply_preflights_only_once_under_lock(self):
        from . import history_import
        with patch('operations.history_import._preflight', wraps=history_import._preflight) as preflight:
            import_history(self.path, self.team, apply=True)
        self.assertEqual(preflight.call_count, 1)
