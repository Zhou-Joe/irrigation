import uuid
from django.test import TestCase,override_settings
from core.models import Zone,SubmissionReceipt
from . import tests as fixtures
from .models import Location,LocationGrant,Membership


@override_settings(MULTI_TEAM_ENABLED=True)
class LocationBatchTests(TestCase):
    def setUp(self):fixtures.WorkspaceTests.setUp(self)
    def payload(self,**extra):return {'team':self.pt.pk,'rows':'地点名称\t编号\t类型\t上级编号\t纬度\t经度\n主楼\tB\t建筑\t\t31.1\t121.2\n一楼\tF\t楼层\tB\t\t\n房间\tR\t房间\tF\t\t',
                                      'submission_key':str(uuid.uuid4()),**extra}

    def test_paste_preview_and_atomic_parent_creation_are_retry_safe(self):
        before=Location.objects.count();payload=self.payload(action='preview')
        response=self.client.post('/ops/locations/batch/',payload)
        self.assertEqual(response.status_code,200,response.content);self.assertEqual(response.json()['count'],3)
        self.assertEqual(Location.objects.count(),before);self.assertEqual(SubmissionReceipt.objects.count(),0)
        payload['action']='create';response=self.client.post('/ops/locations/batch/',payload)
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(self.client.post('/ops/locations/batch/',payload).json(),response.json())
        self.assertEqual(Location.objects.count(),before+3)
        self.assertEqual(Location.objects.get(code='R').parent.code,'F')
        self.assertEqual(Location.objects.get(code='F').parent.code,'B')
        self.assertEqual(Location.objects.get(code='B').map_display,'pin')
        self.assertEqual(Zone.objects.count(),1)

    def test_bad_rows_or_cycles_do_not_leave_partial_places(self):
        before=Location.objects.count()
        for rows in ('名称\t编号\t纬度\t经度\nA\tA\tbad\t121\nB\tB\t31\t121',
                     '名称\t编号\nA\tDUP\nB\tDUP','名称\t编号\t上级编号\nA\tA\tB\nB\tB\tA',
                     '名称\t编号\t上级编号\nA\tA\tMISSING','名称\t纬度\nA\t31'):
            response=self.client.post('/ops/locations/batch/',self.payload(rows=rows))
            self.assertEqual(response.status_code,400,response.content)
            self.assertEqual(Location.objects.count(),before)

    def test_names_only_are_supported_and_batch_size_is_bounded(self):
        response=self.client.post('/ops/locations/batch/',self.payload(rows='楼一\n楼二',kind='building'))
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['count'],2)
        self.assertTrue(Location.objects.filter(name='楼一',code='',latitude=None).exists())
        self.assertEqual(self.client.post('/ops/locations/batch/',self.payload(rows='\n'.join(['A']*501))).status_code,400)

    def test_field_cannot_batch_create_or_share_and_stale_team_cannot_replay(self):
        payload=self.payload(rows='Building')
        self.assertEqual(self.client.post('/ops/locations/batch/',payload).status_code,200)
        self.client.force_login(self.field)
        self.assertEqual(self.client.post('/ops/locations/batch/',self.payload()).status_code,403)
        self.assertEqual(self.client.post('/ops/locations/batch-sharing/',{'team':self.pt.pk}).status_code,403)
        self.client.force_login(self.pm)
        member=Membership.objects.create(user=self.pm,team=self.it,role='manager')
        self.client.post('/ops/switch/',{'membership':member.pk})
        self.assertEqual(self.client.post('/ops/locations/batch/',payload).status_code,409)

    def test_owner_can_link_and_share_many_irrigation_zones_in_one_operation(self):
        self.client.force_login(self.im)
        other=Zone.objects.create(code='7-8-9',name='Another')
        payload={'team':self.it.pk,'source':'irrigation','zones':[self.zone.pk,other.pk],'targets':[self.pt.pk],
                 'submission_key':str(uuid.uuid4()),'action':'grant'}
        response=self.client.post('/ops/locations/batch-sharing/',payload)
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['count'],2);self.assertEqual(LocationGrant.objects.count(),2)
        self.assertEqual(self.client.post('/ops/locations/batch-sharing/',payload).status_code,200)
        self.assertEqual(LocationGrant.objects.count(),2)
        self.zone.refresh_from_db();self.assertEqual(self.zone.boundary_source,'dxf')
        self.client.force_login(self.pm)
        self.assertEqual(len(self.client.get('/api/zones-payload/').json()['locations']),2)
        self.assertEqual(self.client.post('/ops/locations/batch-sharing/',{'team':self.pt.pk,'locations':[str(self.shared.pk)],'targets':[self.it.pk]}).status_code,403)

    def test_zone_code_collision_rolls_back_the_entire_share_batch(self):
        self.client.force_login(self.im)
        z=Zone.objects.create(code='COLLIDE',name='Conflict')
        Location.objects.create(owner_team=self.it,code='COLLIDE',name='Unrelated')
        response=self.client.post('/ops/locations/batch-sharing/',{'team':self.it.pk,'zones':[self.zone.pk,z.pk],
             'source':'irrigation','targets':[self.pt.pk]})
        self.assertEqual(response.status_code,400,response.content)
        self.assertEqual(LocationGrant.objects.count(),0)
        self.assertFalse(Location.objects.filter(legacy_zone=z).exists())

    def test_platform_admin_can_bulk_share_to_pest_without_changing_view_or_memberships(self):
        self.client.force_login(self.admin)
        self.client.post('/ops/switch/',{'business':'pest-control'})
        before=list(Membership.objects.filter(user=self.admin).values())
        response=self.client.post('/ops/locations/batch-sharing/',{'team':self.pt.pk,'source':'irrigation',
            'zones':[self.zone.pk],'targets':[self.pt.pk]})
        self.assertEqual(response.status_code,200,response.content)
        self.assertTrue(LocationGrant.objects.filter(location=self.shared,team=self.pt).exists())
        self.assertEqual(before,list(Membership.objects.filter(user=self.admin).values()))
        self.assertEqual(self.client.session['operations_business'],'pest-control')
        self.assertContains(self.client.get('/ops/locations/link-irrigation/'),'批量共享灌溉区域')

    def test_all_matching_is_owned_and_filtered_and_can_be_revoked(self):
        own=Location.objects.create(owner_team=self.pt,name='Match building',code='A')
        Location.objects.create(owner_team=self.pt,name='Other',code='B')
        payload={'team':self.pt.pk,'all_matching':'1','q':'Match','targets':[self.it.pk],'action':'grant'}
        self.assertEqual(self.client.post('/ops/locations/batch-sharing/',payload).json()['count'],1)
        self.assertTrue(LocationGrant.objects.filter(location=own,team=self.it).exists())
        payload['action']='revoke';self.assertEqual(self.client.post('/ops/locations/batch-sharing/',payload).status_code,200)
        self.assertFalse(LocationGrant.objects.filter(location=own,team=self.it).exists())

    def test_single_location_save_and_share_also_support_component_updates(self):
        response=self.client.post('/ops/locations/new/',{'name':'Ajax building','kind':'building','map_display':'pin'},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,200,response.content)
        data=response.json();self.assertTrue(data['success']);self.assertNotIn('Location',response)
        place=Location.objects.get(pk=data['location']['id'])
        self.assertEqual(self.client.post(data['edit_url'],{'name':'Updated building','kind':'building'},HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code,200)
        place.refresh_from_db();self.assertEqual(place.name,'Updated building')
        response=self.client.post(f'/ops/locations/{place.pk}/sharing/',{'team':self.it.pk,'action':'grant'},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,200,response.content);self.assertTrue(response.json()['success'])
