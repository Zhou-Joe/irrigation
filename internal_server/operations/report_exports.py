"""Scheduled and manual attachments stay within the owning business team."""
from io import BytesIO
from openpyxl import Workbook
from core.models import WorkReport
from .access import visible_locations


def build_business_report(team,kind,start,end):
    if team.business.code not in ('pest-control','landscaping') or not team.active or not team.business.active:
        raise ValueError('当前业务未启用邮件报表')
    business=team.business.name
    book=Workbook(write_only=True)
    if kind=='zones':
        label=business+'区域与地点目录';sheet=book.create_sheet('地点')
        sheet.append(['编号','名称','类型','所属团队','纬度','经度'])
        rows=([p.code,p.name,p.get_kind_display(),p.owner_team.name,str(p.latitude or ''),str(p.longitude or '')] for p in visible_locations(team))
    elif kind in ('work_reports','difficult_workorders'):
        label=business+'工单记录' if kind=='work_reports' else business+'疑难问题跟进报表';sheet=book.create_sheet('工单')
        qs=WorkReport.all_businesses.filter(business_team=team,pest_data__isnull=False,date__range=(start,end)).select_related('worker').order_by('date','pk')
        if kind=='difficult_workorders':qs=qs.filter(is_difficult=True)
        sheet.append(['工单号','日期','处理人','地点','工作内容','本组工时','第三方工时','待跟进','疑难已解决','天气','备注'])
        rows=([r.display_number,r.date.isoformat(),r.worker.full_name,r.zone_names,r.work_content,r.team_hours,r.third_party_hours,
               '是' if r.is_pending_repair else '否','是' if r.is_difficult_resolved else '否',r.weather,r.remark] for r in qs.iterator())
    else:raise ValueError('该报表不属于植保业务')
    from openpyxl.cell import WriteOnlyCell
    for row in rows:
        values=[]
        for value in row:
            cell=WriteOnlyCell(sheet,value=value)
            if isinstance(value,str):cell.data_type='s'
            values.append(cell)
        sheet.append(values)
    output=BytesIO();book.save(output)
    return f'{label}_{start}_{end}.xlsx',output,label
