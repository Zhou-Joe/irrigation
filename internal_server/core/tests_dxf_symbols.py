"""Shape variation, negative pipe examples and reviewed CAD symbol workflows."""
import math
import json

from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase, override_settings

from . import dxf_symbols as symbols
from . import tests_dxf_integrity as helpers
from .models import DxfValveShapeTemplate, ManagerProfile, PipeValve, Pipeline, PipelineImportBatch, Worker


BOWTIE = [[[-1,-.6],[1,.6],[1,-.6],[-1,.6],[-1,-.6]]]
CUSTOM = [[[-1,-.7],[.4,-.7],[1,0],[.4,.7],[-1,.7],[-.5,0],[-1,-.7]]]


def transformed(paths, angle=0, scale=1, mirror=False, aspect=1, offset=(10000,-20000)):
    cosine,sine=math.cos(angle),math.sin(angle)
    return [[[(x*(-1 if mirror else 1)*cosine-y*aspect*sine)*scale+offset[0],
              (x*(-1 if mirror else 1)*sine+y*aspect*cosine)*scale+offset[1]] for x,y in path] for path in paths]


def layers(paths, name='100'):
    return {name:{'polys':paths,'closed':0,'entities':[{'source_id':str(i),'type':'LWPOLYLINE'} for i in range(len(paths))]}}


class ShapeMathTests(SimpleTestCase):
    def test_saved_arbitrary_shape_matches_different_positions_sizes_rotations_and_mirrors(self):
        for angle in (0,.31,1.2,2.8):
            for scale in (.02,1,100):
                for mirror in (False,True):
                    with self.subTest(angle=angle,scale=scale,mirror=mirror):
                        value=transformed(CUSTOM,angle,scale,mirror,aspect=1.8)
                        self.assertLess(symbols.shape_error(CUSTOM,value),symbols.MATCH_ERROR)

    def test_resampling_and_reversing_vertices_does_not_change_identity(self):
        detailed=[]
        for path in CUSTOM:
            points=[]
            for a,b in zip(path,path[1:]):
                points.extend([[a[0]+(b[0]-a[0])*t/5,a[1]+(b[1]-a[1])*t/5] for t in range(5)])
            detailed.append(list(reversed(points+[path[-1]])))
        self.assertLess(symbols.shape_error(CUSTOM,detailed),.04)

    def test_plain_elbows_open_curves_and_straight_pipes_do_not_become_bowtie_valves(self):
        bends=[[[0,0],[1,0],[1,1]],[[0,0],[10,0]],
               [[math.cos(t*math.pi/24),math.sin(t*math.pi/24)] for t in range(25)]]
        self.assertEqual(symbols.recognize(layers(bends),[]),[])
        for points in bends[:2]:
            with self.assertRaises(ValueError):symbols.make_template([points],'Incomplete','gate')

    def test_standard_shape_and_saved_examples_produce_stable_source_candidates(self):
        template=dict(symbols.make_template(CUSTOM,'Custom valve','angle'),id='saved-example')
        geometry=layers(transformed(BOWTIE,.42,.8)+transformed(CUSTOM,1.1,2,True,offset=(20,30)))
        first=symbols.recognize(geometry,[],[template]);second=symbols.recognize(geometry,[],[template])
        self.assertEqual(first,second)
        self.assertEqual(len(first),2)
        self.assertEqual({c['source_refs'][0]['index'] for c in first},{0,1})
        learned=next(c for c in first if c['template_id']=='saved-example')
        self.assertEqual(learned['valve_type_guess'],'angle')

    def test_wd_text_inside_any_closed_outline_identifies_washdown_and_keeps_label_identity(self):
        circle=[[math.cos(t*math.pi/18),math.sin(t*math.pi/18)] for t in range(37)]
        labels=[{'text':'WD','x':0,'y':0,'source_id':'wd-text'}]
        found=symbols.recognize(layers([circle]),labels)
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]['valve_type_guess'],'washdown')
        self.assertEqual(found[0]['text'],'WD')
        self.assertEqual(found[0]['label_refs'],['wd-text'])
        self.assertEqual(symbols.recognize(layers([circle]),[dict(labels[0],text='A')]),[])

    def test_multi_polyline_example_matches_a_separate_drawing(self):
        parts=[[[-1,-.6],[-1,.6],[0,0],[-1,-.6]],[[0,0],[1,.6],[1,-.6],[0,0]]]
        template=dict(symbols.make_template(parts,'Two-part valve','gate'),id='two-part')
        found=symbols.recognize(layers(transformed(parts,.6,3,True)),[],[template])
        self.assertEqual(len(found),1)
        self.assertEqual(len(found[0]['source_refs']),2)

    def test_a_labelled_circle_example_does_not_auto_convert_unlabelled_circles_to_that_type(self):
        circle=[[math.cos(t*math.pi/18),math.sin(t*math.pi/18)] for t in range(37)]
        label={'text':'WD','x':0,'y':0,'source_id':'wd'}
        template=dict(symbols.make_template([circle],'WD circle','washdown',[label]),id='wd-example')
        found=symbols.recognize(layers([circle]),[],[template])
        self.assertEqual(len(found),1);self.assertFalse(found[0]['include_guess'])
        self.assertLess(found[0]['confidence'],.8)

    def test_source_references_are_validated_and_block_geometry_is_not_double_counted(self):
        geometry=layers(BOWTIE)
        with self.assertRaises(ValueError):symbols.sample_from_refs(geometry,[{'layer':'100','index':100}])
        with self.assertRaises(ValueError):symbols.sample_from_refs(geometry,[{'layer':[],'index':0}])
        self.assertEqual(symbols.recognize(layers(BOWTIE,'块·VALVE'),[]),[])
        self.assertEqual(symbols.sample_from_refs(layers(BOWTIE,'块·VALVE'),[{'layer':'块·VALVE','index':0}]),BOWTIE)


@override_settings(ALLOWED_HOSTS=['testserver'],CACHES={
    'default':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache','LOCATION':'shape-workflow'},
    'dxffile':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache','LOCATION':'shape-source'}})
class ShapeWorkflowTests(TestCase):
    setUp=helpers.ImportIntegrityTests.setUp
    analyze=helpers.ImportIntegrityTests.analyze

    def import_shapes(self,data,shapes=None,blocks=None,layer_specs=None):
        return self.client.post('/pipelines/dxf/import/',{'token':data['token'],'preview_token':data['preview_token'],
            'submission_key':data['submission_key'],'import_mode':'aligned',
            'layers_json':json.dumps({'100':{'include':True}} if layer_specs is None else layer_specs),
            'blocks_json':json.dumps(blocks or {}),'shapes_json':json.dumps(shapes or {}),'label_layers':'[]'})

    def gapped_valve(self):
        def build(doc):
            msp=doc.modelspace()
            msp.add_line((18097,-10100),(18099,-10100),dxfattribs={'layer':'100'})
            msp.add_line((18101,-10100),(18103,-10100),dxfattribs={'layer':'100'})
            msp.add_lwpolyline(transformed(BOWTIE,offset=(18100,-10100))[0],dxfattribs={'layer':'100'})
        return self.analyze(helpers.drawing(build))

    def test_reviewed_polyline_becomes_one_valve_and_preserves_pipe_connectivity_and_originals(self):
        data=self.gapped_valve();candidate=data['shape_candidates'][0]
        response=self.import_shapes(data,{candidate['id']:{'include':True,'valve_type':'gate'}})
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual((response.json()['pipelines'],response.json()['valves']),(1,1))
        pipe=Pipeline.objects.get();valve=pipe.valves.get();batch=pipe.import_batch
        self.assertEqual(valve.source_attributes['source_kind'],'polyline')
        self.assertEqual(valve.source_attributes['source_refs'],candidate['source_refs'])
        self.assertEqual(valve.valve_type,'gate')
        self.assertTrue(all(abs(p[1]+10100)<1e-6 for p in pipe.source_points))
        self.assertEqual(batch.source_geometry['recognized_shapes'][0]['connection'],'bridge')
        self.assertEqual(len(batch.source_geometry['layers']['100']['polys']),3)
        self.assertEqual(len(batch.source_geometry['layers']['100']['polys'][2]),5)
        from .dxf_pipeline_utils import build_cad_reference_payload
        payload=build_cad_reference_payload()[0]
        self.assertEqual(len(payload['symbols'][0]['paths']),1)
        self.assertEqual(len(payload['layers'][0]['paths']),2)

    def test_unselected_suggestions_leave_original_pipe_geometry_and_create_no_devices(self):
        data=self.gapped_valve();candidate=data['shape_candidates'][0]
        self.assertEqual(self.import_shapes(data).status_code,200)
        first=sorted(json.dumps(p.source_points) for p in Pipeline.objects.all())
        # Reuse the same drawing source, with a fresh reviewed preview.
        from .dxf_pipeline_utils import analyze_dxf_pipelines
        data2=analyze_dxf_pipelines(token=data['token'],user_id=self.user.pk)
        self.assertEqual(self.import_shapes(data2,{candidate['id']:{'include':False}}).status_code,200)
        batch=PipelineImportBatch.objects.order_by('-pk').first()
        self.assertEqual(sorted(json.dumps(p.source_points) for p in batch.pipelines.all()),first)
        self.assertFalse(PipeValve.objects.exists())

    def test_forged_or_untyped_candidates_are_rejected_before_writes(self):
        data=self.gapped_valve();candidate=data['shape_candidates'][0]
        for specs in ({'shape:forged':{'include':True,'valve_type':'gate'}},
                      {candidate['id']:{'include':True,'valve_type':''}},
                      {candidate['id']:{'include':'true','valve_type':'gate'}}):
            response=self.import_shapes(data,specs)
            self.assertEqual(response.status_code,400,response.content)
            self.assertFalse(PipelineImportBatch.objects.exists())

    def test_opaque_blocks_keep_wd_text_and_infer_type_from_their_own_contents(self):
        def build(doc):
            from ezdxf.enums import TextEntityAlignment
            block=doc.blocks.new('WID_Spr-209');block.add_circle((0,0),1.4)
            block.add_text('WD',dxfattribs={'height':.5}).set_placement((0,0),align=TextEntityAlignment.MIDDLE_CENTER)
            for x in (18100,18110,18120):doc.modelspace().add_blockref('WID_Spr-209',(x,-10100))
        data=self.analyze(helpers.drawing(build))
        self.assertEqual(data['blocks'][0]['valve_type_guess'],'washdown')
        self.assertTrue(data['blocks'][0]['include_guess'])
        self.assertEqual(data['shape_candidates'],[])
        points=data['labels'][0]['points'];self.assertEqual(len(points),3)
        self.assertTrue(all(p['inline_symbol'] and p['text']=='WD' for p in points))
        response=self.import_shapes(data,blocks={'WID_Spr-209':{'include':True,'valve_type':'washdown'}},layer_specs={})
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['skipped_valves'],3)
        self.assertEqual((Pipeline.objects.count(),PipeValve.objects.count()),(0,0))
        from .dxf_pipeline_utils import build_cad_reference_payload
        payload=build_cad_reference_payload()[0]
        self.assertTrue(all(label['inline_symbol'] for label in payload['labels']))
        self.assertEqual(len(payload['unmatched_valves']),3)

    def custom_drawing(self,angle=0,scale=1,mirror=False):
        def build(doc):
            doc.modelspace().add_line((18060,-10100),(18140,-10100),dxfattribs={'layer':'100'})
            doc.modelspace().add_lwpolyline(transformed(CUSTOM,angle,scale,mirror,offset=(18100,-10100))[0],dxfattribs={'layer':'100'})
        return self.analyze(helpers.drawing(build))

    def save_custom(self,data):
        return self.client.post('/pipelines/dxf/symbol-templates/',{'token':data['token'],
            'name':'自定义阀门图形','valve_type':'angle','parts_json':json.dumps([{'layer':'100','index':1}])})

    def test_reviewed_example_is_reused_in_a_different_drawing_and_duplicate_save_is_idempotent(self):
        first=self.custom_drawing();saved=self.save_custom(first)
        self.assertEqual(saved.status_code,200,saved.content)
        self.assertEqual(self.save_custom(first).json()['id'],saved.json()['id'])
        self.assertEqual(DxfValveShapeTemplate.objects.count(),1)
        definition=DxfValveShapeTemplate.objects.get().definition
        self.assertLess(max(abs(v) for path in definition['geometry'] for p in path for v in p),5)
        second=self.custom_drawing(angle=1.1,scale=12,mirror=True)
        match=next(c for c in second['shape_candidates'] if c['template_id']==saved.json()['id'])
        self.assertEqual(match['valve_type_guess'],'angle');self.assertGreater(match['confidence'],.8)
        self.assertTrue(match['include_guess'])

    def test_template_access_requires_manager_csrf_and_owner_or_administrator_for_delete(self):
        data=self.custom_drawing();saved=self.save_custom(data);key=saved.json()['id']
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.user)
        self.assertEqual(csrf.post('/pipelines/dxf/symbol-templates/',{'action':'delete','id':key}).status_code,403)
        manager=User.objects.create_user('shape-peer-manager')
        ManagerProfile.objects.create(user=manager,employee_id='S-M',full_name='Shape manager')
        self.client.force_login(manager)
        self.assertEqual(self.client.get('/pipelines/dxf/symbol-templates/').status_code,200)
        self.assertEqual(self.client.post('/pipelines/dxf/symbol-templates/',{'action':'delete','id':key}).status_code,403)
        field=User.objects.create_user('shape-field')
        Worker.objects.create(user=field,employee_id='S-F',full_name='Shape field colleague')
        self.client.force_login(field)
        self.assertEqual(self.client.get('/pipelines/dxf/symbol-templates/').status_code,403)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post('/pipelines/dxf/symbol-templates/',{'action':'delete','id':key}).status_code,200)
        self.assertFalse(DxfValveShapeTemplate.objects.get().active)

    def test_bad_example_references_and_plain_pipe_samples_never_create_templates(self):
        data=self.custom_drawing()
        for refs in ([{'layer':'missing','index':0}],[{'layer':'100','index':0}],[],[{'layer':[],'index':1}]):
            response=self.client.post('/pipelines/dxf/symbol-templates/',{'token':data['token'],
                'name':'bad','valve_type':'gate','parts_json':json.dumps(refs)})
            self.assertEqual(response.status_code,400,response.content)
        self.assertFalse(DxfValveShapeTemplate.objects.exists())
