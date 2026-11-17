import json
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import WorkReport
from .access import visible_locations
from .catalog_service import revise_catalog
from .forms import LocationForm
from .models import BusinessArea, Team, Membership, Location, ReferenceCatalog, ReferenceNode
from .work_parameters import definitions, form_schema, applicable_fields, parameter_snapshot


@override_settings(MULTI_TEAM_ENABLED=True)
class WorkParameterTests(TestCase):
    def setUp(self):
        self.business=BusinessArea.objects.create(code='pest-control',name='植保')
        self.team=Team.objects.create(business=self.business,code='parameter-team',name='植保')
        self.user=get_user_model().objects.create_user('parameter-manager',password='fixture')
        Membership.objects.create(user=self.user,team=self.team,role='manager')
        self.client.force_login(self.user)
        self.catalog=ReferenceCatalog.objects.create(business=self.business,owner_team=self.team,name='Work',version='parameters',source_name='fixture')
        self.team.work_catalog=self.catalog;self.team.save()
        self.branch=ReferenceNode.objects.create(catalog=self.catalog,label='鸟类撞击调查',kind='node',source_line=1,order=0,
            parameters=definitions([{'key':'object_name','label':'鸟种','type':'text'},
                {'key':'count','label':'数量','type':'integer'},
                {'key':'impact_direction','label':'撞击朝向','type':'location'}]))
        self.leaf=ReferenceNode.objects.create(catalog=self.catalog,parent=self.branch,label='记录调查结果',kind='node',source_line=2,order=1)
        self.bee=ReferenceNode.objects.create(catalog=self.catalog,label='蜜蜂作业',kind='node',source_line=3,order=2)
        self.a=Location.objects.create(owner_team=self.team,name='建筑 A',kind='building',parameters=definitions([
            {'key':'impact_direction','label':'撞击朝向','type':'choice','options':['N','S']}],allow_location=False))
        self.b=Location.objects.create(owner_team=self.team,name='建筑 B',kind='building',parameters=definitions([
            {'key':'impact_direction','label':'撞击朝向','type':'choice','options':['E','W']}],allow_location=False))
        self.room=Location.objects.create(owner_team=self.team,parent=self.a,name='二楼房间',kind='room')

    def raw(self, direction='N'):
        return {'work':[{'key':'object_name','value':'乌鸫（疑似）'},{'key':'count','value':0}],
            'locations':[{'key':'impact_direction','location_id':str(self.a.pk),'value':direction}]}

    def snapshot(self, raw=None, **kwargs):
        return parameter_snapshot(self.catalog,[self.leaf.pk],[self.room],self.raw() if raw is None else raw,
                                  available_locations=visible_locations(self.team),**kwargs)

    def payload(self, **kwargs):
        return {'team':str(self.team.pk),'catalog':str(self.catalog.pk),'nodes':[str(self.leaf.pk)],
            'locations':[str(self.room.pk)],'date':timezone.localdate().isoformat(),'team_size':'1',
            'submission_key':str(uuid.uuid4()),'parameters':json.dumps(self.raw()),**kwargs}

    def test_child_rooms_inherit_each_building_fields_without_global_direction(self):
        schema=form_schema(self.catalog,visible_locations(self.team))
        fields=applicable_fields(schema,[self.leaf.pk],[self.room.pk,self.a.pk,self.b.pk])
        self.assertEqual({f['key'] for f in fields['work']},{'object_name','count'})
        self.assertEqual({f['owner_id'] for f in fields['locations']},{str(self.a.pk),str(self.b.pk)})
        self.assertEqual(len(fields['locations']),2)
        self.assertEqual(applicable_fields(schema,[self.bee.pk],[self.a.pk]),{'work':[],'locations':[]})

    def test_values_keep_unknown_zero_and_tentative_species_meaning(self):
        result=self.snapshot()
        self.assertEqual(result['work'][0]['value'],'乌鸫（疑似）')
        self.assertEqual(result['work'][1]['value'],0)
        self.assertEqual(result['locations'][0]['location_id'],str(self.a.pk))
        self.assertEqual(result['locations'][0]['location_label'],'建筑 A')
        unknown=self.snapshot({'work':[],'locations':[]})
        self.assertIsNone(unknown['work'][0]['value'])
        self.assertIsNone(unknown['locations'][0]['value'])

    def test_other_building_options_and_forged_values_are_rejected(self):
        for raw in (self.raw('E'),{'work':[],'locations':[{'key':'impact_direction','location_id':str(self.b.pk),'value':'E'}]},
                    {'work':[{'key':'undeclared','value':'bad'}],'locations':[]},
                    {'work':[{'key':'count','value':'NaN'}],'locations':[]},
                    {'work':[{'key':'count','value':1.5}],'locations':[]},
                    {'work':[{'key':'object_name','value':'x','label':'forged'}],'locations':[]},
                    {'work':[{'key':'count','value':0},{'key':'count','value':1}],'locations':[]}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):self.snapshot(raw)

    def test_unmodified_historical_choice_can_be_retained_after_retirement(self):
        previous=self.snapshot()
        self.a.parameters[0]['options']=[{'value':'S','label':'南侧'}];self.a.save()
        with self.assertRaises(ValueError):self.snapshot()
        saved=self.snapshot(previous=previous)
        self.assertEqual(saved['locations'][0]['value'],'N')
        with self.assertRaises(ValueError):self.snapshot(self.raw('UNKNOWN'),previous=previous)

    def test_form_and_submission_use_real_structured_fields_and_server_labels(self):
        response=self.client.get('/api/modal/workorder-data/')
        self.assertContains(response,'pest-parameter-schema')
        result=self.client.post('/mobile/workorder/v2/',self.payload())
        self.assertEqual(result.status_code,200,result.content)
        report=WorkReport.all_businesses.get(pk=result.json()['report_id'])
        self.assertEqual(report.pest_data.parameters,self.snapshot())
        self.a.name='Renamed';self.a.save()
        self.assertEqual(report.pest_data.parameters['locations'][0]['location_label'],'建筑 A')
        self.assertContains(self.client.get(f'/work-reports/{report.pk}/'),'建筑 A · 撞击朝向')
        invalid=self.client.post('/mobile/workorder/v2/',self.payload(parameters=json.dumps(self.raw('E'))))
        self.assertEqual(invalid.status_code,400)
        self.assertEqual(WorkReport.all_businesses.count(),1)

    def test_catalog_edits_copy_parameters_and_do_not_mutate_issued_version(self):
        self.assertIn('parameters',self.client.get('/ops/business-data/data/').json()['nodes'][0])
        version,selected=revise_catalog(self.team,self.catalog.pk,'edit',self.branch.pk,
            label='鸟类调查',kind='node',parent='',order=0)
        cloned=version.nodes.get(pk=selected)
        self.assertEqual(cloned.parameters,self.branch.parameters)
        self.assertEqual(version.nodes.get(label=self.leaf.label).parameters,[])
        revise_catalog(self.team,version.pk,'edit',cloned.pk,label='鸟类调查',kind='node',parent='',order=0,
                       parameters='[]')
        self.branch.refresh_from_db();cloned.refresh_from_db()
        self.assertTrue(self.branch.parameters);self.assertTrue(cloned.parameters)

    def test_building_config_validation_and_older_client_preservation(self):
        payload={'name':self.a.name,'kind':'building','map_display':'auto'}
        form=LocationForm(payload,instance=self.a,parents=Location.objects.none())
        self.assertTrue(form.is_valid(),form.errors);self.assertEqual(form.cleaned_data['parameters'],self.a.parameters)
        for config in ('{"not":"a list"}',json.dumps([{'key':'bad-key','label':'bad'}]),
                       json.dumps([{'key':'direction','label':'bad','type':'location'}])):
            form=LocationForm({**payload,'parameters':config},instance=self.a,parents=Location.objects.none())
            self.assertFalse(form.is_valid())
        form=LocationForm({**payload,'parameters':'[]'},instance=self.a,parents=Location.objects.none())
        self.assertTrue(form.is_valid(),form.errors);self.assertEqual(form.cleaned_data['parameters'],[])

    def test_private_ancestor_config_is_not_disclosed_by_child_visibility(self):
        # A grant on a child must not reveal other ungranted ancestor data.
        schema=form_schema(self.catalog,[self.room])
        self.assertEqual(applicable_fields(schema,[self.leaf.pk],[self.room.pk])['locations'],[])
        self.assertNotIn('建筑 A',json.dumps(schema,ensure_ascii=False))

    def test_definition_validation_rejects_ambiguous_unsafe_or_unbounded_config(self):
        for config in ([{'key':'x','label':'X'},{'key':'x','label':'Y'}],
                       [{'key':'x','label':'X','type':'choice','options':['N','N']}],
                       [{'key':'x','label':'X','required':'yes'}],
                       [{'key':'x','label':'X','type':[]}],
                       [{'key':'x','label':'X','type':{}}],
                       [{'key':'x','label':'X','script':'alert(1)'}]):
            with self.subTest(config=config),self.assertRaises(ValueError):definitions(config)
        required=definitions([{'key':'x','label':'必填','required':True}])
        self.branch.parameters=required;self.branch.save()
        with self.assertRaises(ValueError):self.snapshot({'work':[{'key':'x','value':'   '}],'locations':[]})

    def test_required_building_binding_rejects_a_place_without_its_definition(self):
        self.branch.parameters=[{'key':'custom_direction','label':'撞击朝向','type':'location','required':True}]
        self.branch.save()
        self.a.parameters=[];self.a.save()
        with self.assertRaisesMessage(ValueError,'尚未配置撞击朝向'):
            self.snapshot({'work':[],'locations':[]})

    def test_existing_buildings_get_cardinal_directions_for_nested_bird_collision_work(self):
        self.a.parameters=[];self.a.save()
        self.b.parameters=[];self.b.save()
        self.branch.parameters=[];self.branch.label='鸟类';self.branch.save()
        self.leaf.label='撞击死亡';self.leaf.save()
        schema=form_schema(self.catalog,visible_locations(self.team))
        fields=applicable_fields(schema,[self.leaf.pk],[self.room.pk,self.b.pk])
        self.assertEqual(len(fields['locations']),2)
        for field in fields['locations']:
            self.assertEqual([option['label'] for option in field['options']],['东','南','西','北'])
        self.assertEqual(applicable_fields(schema,[self.bee.pk],[self.a.pk]),{'work':[],'locations':[]})
        raw={'work':[],'locations':[{'location_id':str(self.a.pk),'key':'impact_direction','value':'E'},
                                  {'location_id':str(self.b.pk),'key':'impact_direction','value':'W'}]}
        result=parameter_snapshot(self.catalog,[self.leaf.pk],[self.room,self.b],raw,available_locations=visible_locations(self.team))
        self.assertEqual({item['location_id']:item['value_label'] for item in result['locations']},{str(self.a.pk):'东',str(self.b.pk):'西'})
        raw['locations'][0]['value']='NE'
        with self.assertRaisesMessage(ValueError,'请重新选择撞击方向'):
            parameter_snapshot(self.catalog,[self.leaf.pk],[self.room,self.b],raw,available_locations=visible_locations(self.team))

    def test_managers_edit_building_directions_without_json_and_keep_other_parameters(self):
        self.a.parameters.append({'key':'window_count','label':'窗户数量','type':'integer','required':False})
        self.a.save()
        form=LocationForm({'name':self.a.name,'kind':'building','orientation_options':'N、S、东南，东北'},
                          instance=self.a,parents=Location.objects.none())
        self.assertTrue(form.is_valid(),form.errors)
        form.save();self.a.refresh_from_db()
        direction=next(field for field in self.a.parameters if field['key']=='impact_direction')
        self.assertEqual([choice['label'] for choice in direction['options']],['N','S','东南','东北'])
        self.assertTrue(any(field['key']=='window_count' for field in self.a.parameters))
        saved=self.snapshot(self.raw('东北'))
        self.assertEqual(saved['locations'][0]['value_label'],'东北')
        self.assertContains(self.client.get(f'/ops/locations/{self.a.pk}/'),'建筑方位')
        for value in ('','东、东','、'.join(str(i) for i in range(101))):
            with self.subTest(value=value):
                form=LocationForm({'name':self.a.name,'kind':'building','orientation_options':value},instance=self.a,parents=Location.objects.none())
                self.assertFalse(form.is_valid())
                self.assertIn('orientation_options',form.errors)

    def test_nested_building_keeps_historical_direction_owner_when_only_remarks_change(self):
        self.room.kind = 'building'; self.room.save()
        response = self.client.post('/mobile/workorder/v2/', self.payload())
        self.assertEqual(response.status_code, 200, response.content)
        report = WorkReport.all_businesses.get(pk=response.json()['report_id'])
        old = report.pest_data.parameters
        schema = form_schema(self.catalog, visible_locations(self.team), old)
        fields = applicable_fields(schema, [self.leaf.pk], [self.room.pk])
        self.assertEqual(fields['locations'][0]['owner_id'], str(self.a.pk))
        self.assertEqual(fields['locations'][0]['options'][0]['value'], 'N')
        response = self.client.post('/mobile/workorder/v2/', self.payload(report_id=str(report.pk), remark='只改备注'))
        self.assertEqual(response.status_code, 200, response.content)
        report.pest_data.refresh_from_db()
        self.assertEqual(report.pest_data.parameters, old)
        self.assertContains(self.client.get(f'/ops/locations/{self.room.pk}/'), 'N、S')

    def test_building_rename_preserves_empty_or_complex_direction_configuration(self):
        for options in (None, [{'value':'NE_GATE','label':'东北，入口'}, {'value':'SW','label':'西南'}],
                        [{'value':str(i),'label':str(i)} for i in range(100)]):
            with self.subTest(options=options):
                self.a.parameters = [] if options is None else definitions([
                    {'key':'impact_direction','label':'撞击朝向','type':'choice','options':options,'unit':'面'}])
                self.a.save()
                original = self.a.parameters
                initial = LocationForm(instance=self.a, parents=Location.objects.none()).initial
                form = LocationForm({'name':'新名称','kind':'building','parameters':json.dumps(original),
                                     'orientation_options':initial['orientation_options'].replace('\n','\r\n')},
                                    instance=self.a, parents=Location.objects.none())
                self.assertTrue(form.is_valid(), form.errors)
                form.save(); self.a.refresh_from_db()
                self.assertEqual(self.a.parameters, original)

    def test_adding_a_direction_keeps_punctuation_and_existing_option_codes(self):
        self.a.parameters = definitions([{'key':'impact_direction','label':'撞击朝向','type':'choice','unit':'面',
            'options':[{'value':'NE_GATE','label':'东北，入口'}, {'value':'SW','label':'西南'}]}])
        self.a.save()
        initial = LocationForm(instance=self.a, parents=Location.objects.none()).initial
        form = LocationForm({'name':self.a.name,'kind':'building',
                             'orientation_options':initial['orientation_options']+'\n东南'},
                            instance=self.a, parents=Location.objects.none())
        self.assertTrue(form.is_valid(), form.errors)
        form.save(); self.a.refresh_from_db()
        field = self.a.parameters[0]
        self.assertEqual(field['options'], [{'value':'NE_GATE','label':'东北，入口'}, {'value':'SW','label':'西南'}, {'value':'东南','label':'东南'}])
        self.assertEqual(field['unit'], '面')

    def test_bird_bindings_merge_by_key_and_keep_the_stricter_requirement(self):
        self.branch.parameters = []; self.branch.save()
        second = ReferenceNode.objects.create(catalog=self.catalog, label='鸟类撞击事件记录', kind='node',
            source_line=99, order=99, parameters=[{'key':'impact_direction','label':'撞击朝向','type':'location','required':True}])
        raw = {'work': [], 'locations': [{'key':'impact_direction','location_id':str(self.a.pk),'value':'N'}]}
        for nodes in ([self.leaf.pk, second.pk], [second.pk, self.leaf.pk]):
            result = parameter_snapshot(self.catalog, nodes, [self.room], raw, available_locations=visible_locations(self.team))
            self.assertEqual(len(result['locations']), 1)
            self.assertEqual(result['locations'][0]['value_label'], 'N')
        with self.assertRaisesMessage(ValueError, '请填写'):
            parameter_snapshot(self.catalog, [self.leaf.pk, second.pk], [self.room], {},
                               available_locations=visible_locations(self.team))
