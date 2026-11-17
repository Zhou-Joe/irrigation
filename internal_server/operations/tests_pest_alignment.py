import json
import re
from datetime import date,timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import TestCase,Client,override_settings
from django.utils import timezone
from openpyxl import load_workbook

from core.models import (Announcement,Crew,EmailReportConfig,EmailDeliveryProfile,ManagerProfile,
                         RegistrationRequest,WorkReport,Worker,Land,WeatherData)
from . import tests as fixtures
from .models import AdministratorScope,Location,Membership,PestWorkData,ReferenceCatalog,ReferenceNode,Team
from .work_parameters import definitions,form_schema,applicable_fields


@override_settings(MULTI_TEAM_ENABLED=True)
class PestAlignmentTests(TestCase):
    def setUp(self):
        fixtures.WorkspaceTests.setUp(self)
        self.catalog=ReferenceCatalog.objects.create(business=self.pest,owner_team=self.pt,version='alignment',name='植保',source_name='fixture')
        self.pt.work_catalog=self.catalog;self.pt.save()
        self.birds=ReferenceNode.objects.create(catalog=self.catalog,label='鸟类',kind='node',source_line=1,order=0)
        self.dead=ReferenceNode.objects.create(catalog=self.catalog,parent=self.birds,label='死鸟',kind='node',source_line=2,order=1)
        self.strike=ReferenceNode.objects.create(catalog=self.catalog,parent=self.dead,label='撞击死亡',kind='node',source_line=3,order=2)
        self.record=ReferenceNode.objects.create(catalog=self.catalog,parent=self.birds,label='撞击事件记录',kind='node',source_line=4,order=3,parameters=definitions([
            {'key':'object_name','label':'鸟类对象','type':'choice','options':['乌鸫']},
            {'key':'species_alpha_code','label':'鸟类代码','type':'text'},
            {'key':'impact_direction','label':'撞击朝向','type':'location'},
            {'key':'weather','label':'天气','type':'text'},
            {'key':'reported_by','label':'报告人','type':'text'},
            {'key':'notes','label':'观察备注','type':'text'}]))
        self.building=Location.objects.create(owner_team=self.pt,name='观测楼',kind='building',latitude=31.145,longitude=121.655,
            parameters=[{'key':'impact_direction','label':'撞击朝向','type':'choice','options':[{'value':'N','label':'N'},{'value':'E','label':'E'}]}])
        Worker.objects.create(user=self.pm,employee_id='PM-ALIGN',full_name='植保经理')

    def report(self,day,number='ALIGN',**fields):
        report=WorkReport.all_businesses.create(worker=self.pm.worker_profile,business_team=self.pt,date=day,ticket_number=number,**fields)
        detail=PestWorkData.objects.create(report=report,catalog=self.catalog,selections=[{'node_id':self.strike.pk,'path':['鸟类','死鸟','撞击死亡'],'kind':'node'}])
        detail.locations.add(self.building)
        return report

    def test_dead_bird_strike_automatically_exposes_the_complete_collision_form_and_saves_it(self):
        schema=form_schema(self.catalog,[self.building]);node=next(n for n in schema['nodes'] if n['id']==str(self.strike.pk))
        self.assertEqual(node['related_forms'][0]['id'],str(self.record.pk))
        fields=applicable_fields(schema,[self.strike.pk],[self.building.pk])
        self.assertEqual({p['key'] for p in fields['work']},{'object_name','species_alpha_code','weather','reported_by','notes'})
        self.assertEqual([p['label'] for p in fields['locations'][0]['options']],['北','东'])
        now=timezone.localtime();WeatherData.objects.create(date=now.date(),latitude=31.14,longitude=121.65,hourly_data=[{'hour':now.hour,'code':0,'temp':24}])
        response=self.client.post('/mobile/workorder/v2/',{'team':self.pt.pk,'catalog':self.catalog.pk,'nodes':[self.strike.pk],
            'locations':[str(self.building.pk)],'date':now.date().isoformat(),'team_size':'1','remark':'窗前发现',
            'parameters':json.dumps({'work':[{'key':'object_name','value':'自填鸟种'},{'key':'species_alpha_code','value':'CUSTOM'}],
                'locations':[{'key':'impact_direction','location_id':str(self.building.pk),'value':'N'}]})})
        self.assertEqual(response.status_code,200,response.content)
        saved=WorkReport.all_businesses.get(pk=response.json()['report_id']);values={p['key']:p['value'] for p in saved.pest_data.parameters['work']}
        self.assertEqual(values['object_name'],'自填鸟种');self.assertEqual(values['species_alpha_code'],'CUSTOM')
        self.assertEqual(values['reported_by'],self.pm.username);self.assertIn('24°C',values['weather'])
        self.assertEqual(len(saved.pest_data.selections),1);self.assertEqual(saved.pest_data.parameters['locations'][0]['value_label'],'北')
        page=self.client.get(f'/work-reports/{saved.pk}/')
        self.assertContains(page,'class="zd-head-right"');self.assertContains(page,'class="zd-weather"');self.assertContains(page,'24°C')

    def test_noncollision_work_does_not_receive_the_collision_form(self):
        bee=ReferenceNode.objects.create(catalog=self.catalog,label='蜜蜂处置',kind='node',source_line=5,order=4)
        self.assertEqual(applicable_fields(form_schema(self.catalog,[self.building]),[bee.pk],[self.building.pk]),{'work':[],'locations':[]})

    def test_all_and_custom_ranges_exceed_a_year_without_widening_the_team_scope(self):
        self.report(date(2020,1,1),'ALIGN-OLD');self.report(timezone.localdate(),'ALIGN-NOW')
        self.assertNotContains(self.client.get('/work-reports/'),'ALIGN-OLD')
        for params in ({'period':'all'},{'date_from':'2019-01-01','date_to':timezone.localdate().isoformat()}):
            page=self.client.get('/work-reports/',params);self.assertContains(page,'ALIGN-OLD');self.assertEqual(page.context['totals']['total'],2)
            self.assertEqual(self.client.get('/ops/reports/export/',params).status_code,200)
        self.assertNotContains(self.client.get('/work-reports/',{'period':'year'}),'ALIGN-OLD')
        page=self.client.get('/work-reports/',{'date_from':'2026-11-18','date_to':'2026-11-17'})
        self.assertContains(page,'开始日期不能晚于结束日期')
        self.client.force_login(self.field);self.assertNotContains(self.client.get('/work-reports/',{'period':'all'}),'ALIGN-OLD')

    def test_map_reuses_region_names_without_disclosing_irrigation_work(self):
        self.zone.land=Land.objects.create(name='二级大区');self.zone.dxf_boundary_points=[[{'lat':31.145,'lng':121.655},{'lat':31.146,'lng':121.655},{'lat':31.145,'lng':121.656}]];self.zone.save()
        data=self.client.get('/api/zones-payload/').json()
        self.assertEqual(data['region_labels'][0]['name'],'二级大区');self.assertAlmostEqual(data['region_labels'][0]['center'][0],31.145333,places=5)
        self.assertNotIn('private-irrigation-note',json.dumps(data))

    def test_user_management_uses_all_five_shared_tabs_with_business_owned_data(self):
        Announcement.objects.create(title='灌溉专用通知',body='private');Announcement.objects.create(title='植保通知',body='pest',business_team=self.pt)
        Crew.objects.create(name='灌溉专用班组');Crew.objects.create(name='植保班组',business_team=self.pt)
        page=self.client.get('/user-management/')
        self.assertEqual(page.status_code,200)
        for name in ('users','approval','announcements','crews','email'):self.assertContains(page,f'data-tab="{name}"')
        for private in ('灌溉专用通知','灌溉专用班组','private-irrigation-note'):self.assertNotContains(page,private)
        self.assertContains(page,'植保通知');self.assertContains(page,'植保班组')

    def test_notification_and_crew_mutations_cannot_address_irrigation_rows(self):
        other=Announcement.objects.create(title='Irrigation',body='private');crew=Crew.objects.create(name='Irrigation')
        self.assertEqual(self.client.post(f'/announcements/{other.pk}/delete/').status_code,404)
        self.assertEqual(self.client.get(f'/settings/crew/{crew.pk}/',{'json':'1'}).status_code,404)
        self.client.post('/announcements/save/',{'title':'植保通知','body':'正常通知','active':'1'})
        self.assertTrue(Announcement.objects.filter(title='植保通知',business_team=self.pt).exists())
        created=self.client.post('/settings/crew/new/',{'name':'植保巡查','leader':self.field.worker_profile.pk,
            'members':[self.field.worker_profile.pk],'locations':[str(self.building.pk)],'active':'1'},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(created.status_code,200,created.content);saved=Crew.objects.get(pk=created.json()['crew_id'])
        self.assertEqual(saved.business_team,self.pt);self.assertEqual(list(saved.locations.all()),[self.building])
        invalid=self.client.post('/settings/crew/new/',{'name':'越权地点','locations':[str(self.private.pk)]},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(invalid.status_code,400);self.assertFalse(Crew.objects.filter(name='越权地点').exists())

    def test_pest_mail_configuration_and_attachments_are_owned_and_export_only_pest_records(self):
        foreign=EmailReportConfig.objects.create(name='Irrigation mail',report_type='work_reports')
        self.assertEqual(self.client.post(f'/email-configs/{foreign.pk}/delete/').status_code,404)
        profile=EmailDeliveryProfile.objects.create(name='Pest mail',host='smtp.invalid',business_team=self.pt)
        saved=self.client.post('/email-configs/save/',{'name':'植保日报','report_types':['work_reports'],'recipients':'fixture@example.invalid',
            'delivery_profile_id':profile.pk,'win_work_reports_days_start':'2','win_work_reports_days_end':'0'})
        self.assertEqual(saved.status_code,200,saved.content)
        cfg=EmailReportConfig.objects.get(pk=saved.json()['config']['id']);self.assertEqual(cfg.business_team,self.pt)
        self.report(timezone.localdate(),'PEST-ATTACHMENT')
        from core.report_export import build_all_attachments
        attachments=build_all_attachments(['work_reports'],cfg.frequency,timezone.localdate(),business_team=cfg.business_team)
        workbook=load_workbook(attachments[0][1],read_only=True,data_only=True)
        values=list(workbook.active.values);self.assertIn('PEST-ATTACHMENT',str(values));self.assertNotIn('private-irrigation',str(values))
        self.assertTrue(build_all_attachments(['irrigation'],'daily',timezone.localdate(),business_team=self.pt)[0][2].startswith('FAILED:'))


@override_settings(MULTI_TEAM_ENABLED=True)
class AdministratorScopeTests(TestCase):
    def setUp(self):
        fixtures.WorkspaceTests.setUp(self)
        AdministratorScope.objects.create(user=self.admin,business=None)
        self.limited=get_user_model().objects.create_superuser('pest-only','',password='fixture')
        self.scope=AdministratorScope.objects.create(user=self.limited,business=self.pest)
        self.worker=Worker.objects.create(user=self.limited,employee_id='SCOPED',full_name='植保管理员')
        # Stored superuser flags and a prior irrigation membership must not bypass scope.
        Membership.objects.create(user=self.limited,team=self.it,role='manager')
        self.client.force_login(self.limited)

    def test_scoped_superuser_has_only_its_business_and_cannot_reach_global_endpoints(self):
        page=self.client.get('/');self.assertEqual(page.status_code,200);self.assertTrue(page.context['pest_mode'])
        self.assertEqual(page.context['business_choices'],[{'code':'pest-control','label':'植保'}]);self.assertEqual(page.context['account_role_label'],'植保管理员')
        for path in ('/admin/','/irrigation/','/api/ai/status','/account-mail/settings/','/email-configs/smtp/'):
            with self.subTest(path=path):self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.client.post('/ops/switch/',{'business':'irrigation'}).status_code,403)
        self.assertEqual(self.client.get('/ops/team/',{'team':self.it.pk}).status_code,403)

    def test_limited_admin_cannot_promote_its_scope_or_edit_a_general_administrator(self):
        response=self.client.post(f'/user-management/worker/{self.worker.pk}/edit/',{'admin_business':'general'})
        self.assertEqual(response.status_code,403);self.scope.refresh_from_db();self.assertEqual(self.scope.business,self.pest)
        general_worker=Worker.objects.create(user=self.admin,employee_id='GENERAL',full_name='General')
        self.assertEqual(self.client.post(f'/user-management/worker/{general_worker.pk}/edit/',{'full_name':'forged'}).status_code,403)
        self.assertEqual(self.client.post(f'/user-management/manager/{self.im.manager_profile.pk}/edit/',{'full_name':'forged'}).status_code,403)

    def test_general_administrator_can_restrict_itself_and_the_next_request_enforces_it(self):
        self.client.force_login(self.admin)
        response=self.client.post(f'/user-management/account/{self.admin.pk}/edit/',{'admin_business':'pest-control','full_name':'General'})
        self.assertEqual(response.status_code,200,response.content);self.assertTrue(response.json()['reload'])
        self.assertEqual(self.client.session['operations_business'],'pest-control')
        self.assertEqual(self.client.get('/admin/').status_code,403)
        self.assertEqual(self.client.post('/ops/switch/',{'business':'irrigation'}).status_code,403)
        self.assertEqual(self.client.get('/user-management/').status_code,200)

    def test_approvals_filter_and_reject_cross_business_requests_and_assign_new_admin_scope(self):
        irrigation=RegistrationRequest.objects.create(username='irr-applicant',full_name='Irr',phone='1',requested_role='field_worker',worker_type='irrigation',password=make_password('fixture'))
        pest=RegistrationRequest.objects.create(username='pest-applicant',full_name='Pest',phone='2',requested_role='manager',admin_business='pest-control',password=make_password('fixture'))
        page=self.client.get('/user-management/',{'tab':'approval'});self.assertContains(page,'pest-applicant');self.assertNotContains(page,'irr-applicant')
        foreign=self.client.post('/user-management/',{'action':'approve','request_id':irrigation.pk},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(foreign.status_code,404)
        from core.registration_service import approve
        with self.assertRaises(Exception) as denied:
            approve(irrigation.pk,self.limited)
        from django.core.exceptions import PermissionDenied
        self.assertIsInstance(denied.exception,PermissionDenied)
        response=self.client.post('/user-management/',{'action':'approve','request_id':pest.pk},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,200,response.content)
        pest.refresh_from_db();self.assertEqual(pest.created_user.administrator_scope.business,self.pest)

    def test_scoped_admin_can_create_a_mail_profile_but_cannot_change_shared_secrets_or_global_settings(self):
        common=EmailDeliveryProfile.objects.create(name='Shared SMTP',host='shared.invalid',password='secret')
        self.assertEqual(self.client.post('/email-configs/delivery-profiles/save/',{'id':common.pk,'name':'forged','host':'forged.invalid'}).status_code,404)
        self.assertEqual(self.client.post('/email-configs/delivery-profiles/%s/delete/'%common.pk).status_code,404)
        response=self.client.post('/email-configs/delivery-profiles/save/',{'name':'Scoped SMTP','host':'smtp.invalid','port':'465'})
        self.assertEqual(response.status_code,200,response.content);self.assertEqual(EmailDeliveryProfile.objects.get(name='Scoped SMTP').business_team,self.pt)
        data=self.client.get('/email-configs/delivery-profiles/').json();self.assertNotIn('secret',str(data))

    def test_csrf_is_required_for_scope_changes(self):
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.admin)
        self.assertEqual(csrf.post(f'/user-management/account/{self.admin.pk}/edit/',{'admin_business':'pest-control'}).status_code,403)

    def test_irrigation_admin_cannot_bypass_account_scope_through_the_worker_api(self):
        self.scope.business=self.irrigation;self.scope.save()
        foreign=self.field.worker_profile
        response=self.client.patch(f'/api/workers/{foreign.pk}/',data=json.dumps({'full_name':'forged'}),content_type='application/json')
        self.assertEqual(response.status_code,404)
        foreign.refresh_from_db();self.assertEqual(foreign.full_name,'Field')
        manager=ManagerProfile.objects.create(user=self.limited,employee_id='TOKEN-SCOPED',full_name='Scoped')
        token=Client().get(f'/api/workers/{foreign.pk}/',HTTP_AUTHORIZATION='Token '+str(manager.api_token))
        self.assertEqual(token.status_code,404)

    def test_even_general_administrators_see_only_general_and_current_business_users(self):
        general=Worker.objects.create(user=self.admin,employee_id='VISIBLE-GENERAL',full_name='通用管理员')
        manager=get_user_model().objects.create_user('membership-manager')
        field=get_user_model().objects.create_user('membership-field')
        Membership.objects.create(user=manager,team=self.pt,role='manager')
        Membership.objects.create(user=field,team=self.pt,role='field')
        other_team=Team.objects.create(business=self.pest,code='second-pest-team',name='植保二组')
        second=get_user_model().objects.create_user('second-pest-employee')
        Membership.objects.create(user=second,team=other_team,role='field')
        self.client.force_login(self.admin)
        for code,expected,absent in (('irrigation',self.im,self.pm),('pest-control',self.pm,self.im)):
            self.client.post('/ops/switch/',{'business':code})
            rows=self.client.get('/user-management/').context['users_list'];ids={row['user_id'] for row in rows}
            self.assertIn(self.admin.pk,ids);self.assertIn(expected.pk,ids);self.assertNotIn(absent.pk,ids)
            if code=='pest-control':
                for person in (self.field,manager,field,second):self.assertIn(person.pk,ids)
        green=Team.objects.get(code='landscaping')
        green_worker=get_user_model().objects.create_user('green-worker')
        Membership.objects.create(user=green_worker,team=green,role='field')
        self.client.post('/ops/switch/',{'business':'landscaping'})
        page=self.client.get('/user-management/');self.assertEqual(page.status_code,200)
        ids={row['user_id'] for row in page.context['users_list']}
        self.assertEqual(ids,{self.admin.pk,green_worker.pk})
