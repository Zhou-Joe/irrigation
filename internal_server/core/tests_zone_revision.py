from datetime import timedelta
from django.contrib.auth.models import User
from django.test import TestCase
from core.models import Zone


class ZoneRevisionTests(TestCase):
    def test_source_switch_changes_revision_and_homepage_payload(self):
        user=User.objects.create_superuser('boundary-refresh','','test-only')
        self.client.force_login(user)
        old=[{'lat':31.14,'lng':121.65},{'lat':31.141,'lng':121.65},{'lat':31.14,'lng':121.651}]
        new=[[{'lat':31.15,'lng':121.66},{'lat':31.151,'lng':121.66},{'lat':31.15,'lng':121.661}]]
        zone=Zone.objects.create(code='6-7-28-refresh',name='Test',boundary_points=old,dxf_boundary_points=new)
        revision=self.client.get('/api/zones-revision/').json()['revision']
        before=self.client.get('/api/zones-payload/')
        self.assertEqual(next(x for x in before.json() if x['id']==zone.pk)['boundary_points'],old)
        zone.boundary_source='dxf';zone.save()
        after=self.client.get('/api/zones-payload/')
        self.assertNotEqual(revision,after['X-Zone-Revision'])
        self.assertEqual(after['X-Zone-Revision'],self.client.get('/api/zones-revision/').json()['revision'])
        self.assertIn('no-store',after['Cache-Control'])
        self.assertEqual(next(x for x in after.json() if x['id']==zone.pk)['boundary_points'],new)
