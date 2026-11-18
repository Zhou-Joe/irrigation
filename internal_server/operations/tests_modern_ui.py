"""Null user references must not crash optional landscaping UI fields."""
from datetime import date, datetime, timezone
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase


class OptionalWorkorderPeopleTests(SimpleTestCase):
    def order(self, **values):
        fields = dict(pk=1, display_number='UI-001', title='巡查', get_kind_display='巡检',
                      scheduled_date=date(2026, 11, 18), assignee=None,
                      created_by=SimpleNamespace(get_full_name='', username='manager'),
                      created_at=datetime(2026, 11, 18, tzinfo=timezone.utc),
                      reviewed_by=None, completed_at=None, get_status_display='待处理',
                      assets=SimpleNamespace(all=[]), instructions='记录现场情况', completion_notes='')
        fields.update(values)
        return SimpleNamespace(**fields)

    def test_list_displays_unassigned_workorder(self):
        html = render_to_string('operations/landscaping/workorders.html', {'records': [self.order()]})
        self.assertIn('待指派', html)

    def test_detail_displays_unassigned_workorder(self):
        html = render_to_string('operations/landscaping/workorder.html', {'order': self.order()})
        self.assertIn('待指派', html)

    def test_detail_handles_removed_reviewer_and_system_actor(self):
        html = render_to_string('operations/landscaping/workorder.html', {
            'order': self.order(completed_at=datetime(2026, 11, 18, tzinfo=timezone.utc)),
            'events': [SimpleNamespace(actor=None, action='green.workorder.complete', detail={},
                                       created_at=datetime(2026, 11, 18, tzinfo=timezone.utc))],
        })
        self.assertIn('系统', html)
        self.assertIn('复核完成', html)
