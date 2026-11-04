import io
from datetime import date, timedelta
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl import load_workbook
from core.models import EmailReportConfig, WorkReport, Worker
from core.report_export import build_report, build_all_attachments


@override_settings(TIME_ZONE='Asia/Shanghai')
class DifficultReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user=User.objects.create_superuser('difficult-report','','test-only')
        cls.worker=Worker.objects.create(user=cls.user,employee_id='DIFFICULT-REPORT',full_name='测试处理人')

    def test_old_open_issues_remain_and_children_are_not_duplicate_issues(self):
        today=timezone.localdate()
        old=WorkReport.objects.create(date=today-timedelta(days=200),worker=self.worker,
            is_difficult=True,remark='=HYPERLINK("untrusted")',collab_status='ongoing')
        child=WorkReport.objects.create(date=today,worker=self.worker,parent_work_report=old,
            followup_action='ongoing',remark='检查进展')
        pending=WorkReport.objects.create(date=today,worker=self.worker,is_difficult=True,collab_status='pending_review')
        resolved=WorkReport.objects.create(date=today,worker=self.worker,is_difficult=True,
            is_difficult_resolved=True,collab_status='resolved')
        historical=WorkReport.objects.create(date=today-timedelta(days=100),worker=self.worker,
            is_difficult=True,is_difficult_resolved=True)
        WorkReport.objects.filter(pk=historical.pk).update(updated_at=timezone.now()-timedelta(days=100))
        ordinary=WorkReport.objects.create(date=today,worker=self.worker,remark='正常工单')
        name,data=build_report('difficult_workorders',today,today,self.user)
        workbook=load_workbook(io.BytesIO(data.getvalue()),data_only=False)
        self.assertTrue(name.startswith('difficult_workorders_'))
        ongoing=workbook['进行中'];waiting=workbook['待确认'];done=workbook['时段内已完成']
        self.assertEqual(ongoing['A2'].value,old.display_number)
        self.assertEqual(ongoing.max_row,2)
        self.assertEqual(ongoing['H2'].data_type,'s')
        self.assertEqual(ongoing['I2'].value,1)
        self.assertEqual(ongoing['L2'].value,'检查进展')
        self.assertEqual(waiting['A2'].value,pending.display_number)
        self.assertEqual(done['A2'].value,resolved.display_number)
        self.assertEqual(done.max_row,2)
        self.assertEqual(workbook['跟进明细']['B2'].value,child.display_number)

    def test_mail_attachment_selection_and_empty_report_work_without_sending(self):
        today=date(2026,11,4)
        config=EmailReportConfig.objects.create(name='每日推送',frequency='daily',
            recipients='fixture@example.invalid',report_types=['difficult_workorders'])
        self.assertEqual(config.effective_report_types(),['difficult_workorders'])
        with patch('core.smtp_utils.get_email_connection',side_effect=AssertionError('must not send')):
            attachments=build_all_attachments(config.effective_report_types(),'daily',today,
                report_windows={'difficult_workorders':{'days_start':1,'days_end':0}})
        self.assertEqual(len(attachments),1)
        name,data,label=attachments[0]
        self.assertEqual(label,'疑难问题跟进报表')
        self.assertIn('2026-11-03_2026-11-04',name)
        self.assertEqual(load_workbook(io.BytesIO(data.getvalue()))['进行中'].max_row,1)
