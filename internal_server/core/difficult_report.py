"""Current difficult/repair follow-up snapshot for the existing Excel mailer."""
import io
from datetime import datetime, time, timedelta

from django.db.models import Prefetch, Q
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def build_difficult_workorders_excel(start_date, end_date, user):
    """Keep old open issues visible; date limits apply to completed issues."""
    from core.models import WorkReport
    from core.role_utils import is_admin
    from core.views import _scoped_work_reports_qs

    end_exclusive = timezone.make_aware(datetime.combine(end_date + timedelta(days=1), time.min))
    start = timezone.make_aware(datetime.combine(start_date, time.min))
    related = WorkReport.objects.select_related('worker').order_by('date', 'id')
    base = (WorkReport.objects.select_related('worker', 'location').prefetch_related('zones')
            if is_admin(user) else _scoped_work_reports_qs(user, False))
    issues = (base
              .filter(parent_work_report__isnull=True)
              .filter(Q(is_difficult=True) | Q(is_pending_repair=True) |
                      Q(collab_status__in=['ongoing', 'pending_review', 'resolved']) |
                      Q(resolved_by_pm__isnull=False) | Q(followup_children__isnull=False))
              .prefetch_related(Prefetch('followup_children', queryset=related, to_attr='_followups'),
                                'zone_location', 'resolved_by_pm')
              .distinct().order_by('date', 'id'))

    buckets = {'进行中': [], '待确认': [], '时段内已完成': []}
    included = []
    for issue in issues:
        if issue.collab_status == 'pending_review':
            status = '待确认'
        elif issue.collab_status == 'ongoing':
            status = '进行中'
        elif issue.collab_status == 'resolved' or issue.resolved_by_pm_id or (
                not issue.is_pending_repair and (not issue.is_difficult or issue.is_difficult_resolved)):
            if not start <= issue.updated_at < end_exclusive:
                continue
            status = '时段内已完成'
        else:
            status = '进行中'
        included.append(issue)
        zones = '、'.join(z.code for z in issue.zones.all()) or issue.zone_names
        if not zones and issue.zone_location:
            zones = issue.zone_location.code
        latest = issue._followups[-1] if issue._followups else None
        buckets[status].append([
            issue.display_number, issue.date, status,
            issue.location.code if issue.location else '', zones,
            issue.worker.full_name, '疑难' if issue.is_difficult else '待修',
            issue.work_content or issue.remark,
            len(issue._followups), latest.date if latest else None,
            latest.worker.full_name if latest else '',
            (latest.work_content or latest.remark) if latest else '',
            timezone.localtime(issue.updated_at).replace(tzinfo=None),
            issue.resolved_by_pm.display_number if issue.resolved_by_pm else '',
        ])

    workbook = Workbook()
    summary = workbook.active
    summary.title = '跟进汇总'
    generated = timezone.localtime().replace(tzinfo=None)
    summary.append(['疑难问题跟进报表'])
    summary.append(['生成时间（上海时间）', generated])
    summary['B2'].number_format = 'yyyy-mm-dd hh:mm:ss'
    summary.append(['已完成记录更新范围', f'{start_date} 至 {end_date}'])
    summary.append(['清单口径', '进行中和待确认包含所有当前未闭环问题，不因原工单日期较早而遗漏；已完成按最近更新时间筛选。'])
    summary.append(['状态', '工单数'])
    for status, rows in buckets.items():
        summary.append([status, len(rows)])
    summary.append(['合计', sum(map(len, buckets.values()))])
    summary.column_dimensions['A'].width = 27
    summary.column_dimensions['B'].width = 100
    summary.row_dimensions[4].height = 34
    summary['B4'].alignment = Alignment(wrap_text=True, vertical='center')

    headers = ['工单号', '原工单日期', '状态', 'CCU', '区域', '处理人', '问题类型',
               '问题描述', '跟进次数', '最近跟进日期', '最近跟进人', '最近跟进内容',
               '工单最近更新（上海时间）', '关联解决工单']
    widths = [16, 15, 18, 12, 32, 18, 12, 60, 12, 16, 18, 60, 25, 18]
    for title, rows in buckets.items():
        sheet = workbook.create_sheet(title)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        for idx, width in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(idx)].width = width
        sheet.freeze_panes = 'C2'
        sheet.auto_filter.ref = sheet.dimensions
        for cells in sheet.iter_rows(min_row=2):
            for cell in cells:
                cell.alignment = Alignment(vertical='top', wrap_text=True)
                # User-authored content is text, including a leading '='.
                if isinstance(cell.value, str):
                    cell.data_type = 's'
            for idx in (2, 10):
                cells[idx-1].number_format = 'yyyy-mm-dd'
            cells[12].number_format = 'yyyy-mm-dd hh:mm:ss'

    stories = workbook.create_sheet('跟进明细')
    stories.append(['原工单号', '跟进工单号', '日期', '处理人', '动作', '跟进内容'])
    for issue in included:
        for child in issue._followups:
            stories.append([issue.display_number, child.display_number, child.date,
                            child.worker.full_name, dict(WorkReport.FOLLOWUP_ACTION_CHOICES).get(child.followup_action, '跟进'),
                            child.work_content or child.remark])
    for index, width in enumerate([16, 16, 15, 18, 16, 100], 1):
        stories.column_dimensions[get_column_letter(index)].width = width
    stories.freeze_panes = 'C2'
    stories.auto_filter.ref = stories.dimensions
    for cells in stories.iter_rows(min_row=2):
        cells[2].number_format = 'yyyy-mm-dd'
        for cell in cells:
            cell.alignment = Alignment(vertical='top', wrap_text=True)
            if isinstance(cell.value, str):
                cell.data_type = 's'
    for sheet in workbook:
        sheet.sheet_view.showGridLines = False
        for cell in sheet[1]:
            cell.font = Font(name='Arial', size=11, bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='1B4332')
            cell.alignment = Alignment(vertical='center', wrap_text=True)
        sheet.row_dimensions[1].height = 30
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return f'difficult_workorders_{start_date}_{end_date}.xlsx', buffer
