import math

import ezdxf
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from .dxf_pipeline_utils import _collect_geometry
from .valve_orientation import batch_poses


def project(x, y, precision):
    return {'lat': round(y / 100000, precision), 'lng': round(x / 100000, precision)}


class ValveOrientationTests(SimpleTestCase):
    def test_insert_axis_honors_rotation_negative_scale_and_map_calibration(self):
        doc = ezdxf.new()
        block = doc.blocks.new('Q')
        block.add_circle((0, 0), 1)
        doc.modelspace().add_blockref('Q', (20, 30), dxfattribs={'rotation': 35, 'yscale': -2})
        layers, valves, _ = _collect_geometry(doc.modelspace())
        source = {'valves': valves, 'layers': layers}
        sid = valves[0]['source_id']
        pose = batch_poses(source, project, {sid})[sid]
        self.assertAlmostEqual(pose['angle'], -35, places=2)
        self.assertTrue(pose['mirrored'])
        self.assertEqual(pose['source'], 'block')
        turned = batch_poses(source, lambda x,y,n: project(-y,x,n), {sid})[sid]
        self.assertAlmostEqual(turned['angle'], -125, places=2)

    def test_historical_inserts_and_reversed_polylines_use_the_same_undirected_axis(self):
        outline = [[0,0],[4,4],[5,3],[1,-1],[0,0]]
        square = [[0,0],[4,0],[4,4],[0,4],[0,0]]
        circle = [[math.cos(i*math.pi/32),math.sin(i*math.pi/32)] for i in range(65)]
        source = {'valves':[{'source_id':'A/0','x':0,'y':0}],
                  'recognized_shapes':[{'id':str(i),'x':0,'y':0,'source_refs':[{'layer':'Refs','index':i}]} for i in range(3)],
                  'layers':{'块·G':{'polys':[outline],'entities':[{'source_id':'A/0/1/0'}]},
                            'Refs':{'polys':[outline[::-1],square,circle]}}}
        poses = batch_poses(source, project, {'A/0','0','1','2'})
        self.assertEqual(poses, {sid:{'angle':-45.,'mirrored':False,'source':'axis'} for sid in ['A/0','0']})


@override_settings(MULTI_TEAM_ENABLED=False)
class ValveShapeTests(TestCase):
    url = '/pipelines/valve-shapes/'

    def setUp(self):
        self.manager = get_user_model().objects.create_user('map-manager',is_staff=True)
        self.client.force_login(self.manager)
        self.payload = {'type':'gate','paths':[[[4,32],[60,32]]],'offset':15,'revision':0}

    def post(self, **changes):
        return self.client.post(self.url, {**self.payload, **changes}, content_type='application/json')

    def test_save_conflict_and_reset_feed_both_maps(self):
        self.assertContains(self.client.get(self.url), '阀门图案画布')
        self.assertEqual(self.post().status_code,200)
        self.assertEqual(self.post().status_code,409)
        for url in ('/api/pipelines-payload/','/pipelines/edit/data/?editor=1'):
            shape = self.client.get(url).json()['valve_shapes']['gate']
            self.assertEqual(shape,{'paths':self.payload['paths'],'offset':15,'revision':1})
        self.assertEqual(self.post(revision=1,paths=[]).status_code,200)
        self.assertEqual(self.client.get('/api/pipelines-payload/').json()['valve_shapes']['gate']['paths'],[])

    def test_invalid_points_and_non_managers_cannot_save(self):
        self.assertEqual(self.post(paths=[[[0,0],['bad',32]]]).status_code,400)
        from .models import Worker
        reader = get_user_model().objects.create_user('reader')
        Worker.objects.create(user=reader, employee_id='shape-reader', full_name='reader')
        self.client.force_login(reader)
        self.assertEqual(self.post().status_code,403)
