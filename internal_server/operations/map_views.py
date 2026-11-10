"""Business adapters for the existing map, modal and work-record URLs."""
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.http import require_GET

from core.models import WorkReport
from core.submissions import submission
from .access import active_membership, require_member, visible_locations, audit
from .models import ReferenceCatalog, PestWorkData
from .catalog_service import current_catalog, selection_snapshot
from .map_data import location_map_data


def is_pest(request):
    if not settings.MULTI_TEAM_ENABLED or not request.user.is_authenticated:
        return False
    member = active_membership(request)
    return bool(member and member.team.business.code == 'pest-control')


def require_writer(request):
    member = require_member(request)
    if member.role not in ('field', 'manager') and not request.user.is_superuser:
        raise PermissionDenied('当前团队身份不能提交工单。')
    return member


def records(request):
    member = require_member(request)
    qs = WorkReport.all_businesses.filter(business_team=member.team, pest_data__isnull=False)
    if member.role != 'manager' and not request.user.is_superuser:
        qs = qs.filter(worker__user=request.user)
    return qs.select_related('worker', 'pest_data').order_by('-date','-id')


def roots_for(catalog):
    nodes = list(catalog.nodes.all())
    items = {n.pk: {'node':n, 'children':[]} for n in nodes}
    roots = []
    for node in nodes:
        item = items[node.pk]
        if node.parent_id:
            items[node.parent_id]['children'].append(item)
        else:
            roots.append(item)
    return roots


def chip_tree(roots):
    return [{'id':item['node'].pk, 'name':item['node'].label, 'kind':item['node'].kind,
             'children':chip_tree(item['children'])} for item in roots]


def pest_dashboard(request):
    member = require_member(request)
    return render(request, 'core/dashboard.html', {
        'pest_mode':True, 'can_pest_submit':member.role in ('manager','field') or request.user.is_superuser,
        'can_pest_manage':member.role=='manager' or request.user.is_superuser})


@require_GET
def pest_map_data(request):
    member = require_member(request)
    if member.team.business.code != 'pest-control':
        raise PermissionDenied
    result = []
    for location in visible_locations(member.team):
        result.append({**location_map_data(location), 'shared':location.owner_team_id != member.team_id})
    from .planning import task_scope
    pending=task_scope(request,member).filter(status='pending',scheduled_date__lte=timezone.localdate()).count()
    response = JsonResponse({'business':'pest-control', 'locations':result,'pending_tasks':pending,
        'records':[{'id':r.pk, 'number':r.display_number, 'date':r.date.isoformat(),
                    'locations':[str(p.pk) for p in r.pest_data.locations.all()]}
                   for r in records(request)[:50].prefetch_related('pest_data__locations')]})
    response['Cache-Control'] = 'private, no-store'
    return response


@require_GET
def pest_form_data(request):
    member = require_writer(request)
    from .models import PestTask
    from .planning import task_scope
    report=None;task=None
    if request.GET.get('report_id','').isdigit():report=get_object_or_404(records(request),pk=int(request.GET['report_id']))
    if request.GET.get('pest_task','').isdigit():task=get_object_or_404(task_scope(request,member),pk=int(request.GET['pest_task']),status='pending')
    if report and task:return JsonResponse({'error':'请分别打开工单编辑或 PM 任务。'},status=400)
    catalog=report.pest_data.catalog if report else task.catalog if task else current_catalog(member.team)
    if not catalog:
        return JsonResponse({'error':'尚未导入本团队的作业层级，请联系管理员。'}, status=400)
    today=timezone.localdate()
    now=timezone.localtime()
    start_minutes=now.hour*60+now.minute//15*15
    clock=lambda minutes:f'{(minutes%1440)//60:02d}:{minutes%60:02d}'
    time_options={clock(n) for n in range(0,1440,15)}
    if report:
        time_options.update(value.strftime('%H:%M') for value in (report.work_start_time,report.work_end_time) if value)
    tree=chip_tree(roots_for(catalog))
    options=[{'id':str(p.pk),'name':p.name,'code':p.code,'kind':p.kind,'parent':str(p.parent_id) if p.parent_id else ''}
             for p in visible_locations(member.team).select_related(None).only('id','name','code','kind','parent_id')]
    html = render_to_string('operations/_pest_workorder_form.html', {
        'catalog':catalog, 'work_tree':tree, 'location_options':options,
        'team':member.team, 'today':today.isoformat(), 'report':report,'task':task,
        'dates':list(dict.fromkeys(([report.date.isoformat()] if report else [])+[(today-timedelta(days=n)).isoformat() for n in range(90)])),
        'selected_date':report.date.isoformat() if report else today.isoformat(),
        'selected_shift':report.shift if report and report.shift else WorkReport.SHIFT_CHOICES[0][0],
        'preset_nodes':[s['node_id'] for s in (report.pest_data.selections if report else task.selections if task else [])],
        'preset_locations':[str(p.pk) for p in report.pest_data.locations.all()] if report else [str(task.location_id)] if task else [],
        'time_options':sorted(time_options),
        'start_time':report.work_start_time.strftime('%H:%M') if report and report.work_start_time else clock(start_minutes),
        'end_time':report.work_end_time.strftime('%H:%M') if report and report.work_end_time else clock(start_minutes+15),
        'shifts':[value for value,_ in WorkReport.SHIFT_CHOICES],
        'submission_key':str(uuid.uuid4())},request=request)
    return JsonResponse({'business':'pest-control', 'form_html':html,'form_title':'编辑植保工单' if report else '完成植保 PM 任务' if task else '植保作业工单'})


def pest_workorder(request, report_id=None):
    member = require_writer(request)
    if request.method == 'GET':
        return redirect('/?action=workorder')
    if request.method != 'POST':
        return JsonResponse({'success':False,'message':'请求方式无效'},status=405)
    # Validate context before idempotency replay as well as before writes.
    if request.POST.get('team') != str(member.team_id):
        return JsonResponse({'success':False,'message':'团队身份已变化，请重新打开工单。'},status=409)
    if report_id and str(report_id)!=request.POST.get('report_id'):
        return JsonResponse({'success':False,'message':'工单编号不一致，请重新打开。'},status=400)
    return _save_pest_workorder(request)


@submission('pest-workorder')
def _save_pest_workorder(request):
    member = require_writer(request)
    from .models import PestTask
    from .planning import task_scope
    report=None;task=None
    report_id=request.POST.get('report_id','');task_id=request.POST.get('pest_task','')
    if report_id:
        if not report_id.isdigit():return JsonResponse({'success':False,'message':'工单编号无效。'},status=400)
        report=get_object_or_404(records(request),pk=int(report_id))
        task=PestTask.objects.filter(report=report,team=member.team).first()
    elif task_id:
        if not task_id.isdigit():return JsonResponse({'success':False,'message':'任务编号无效。'},status=400)
        task=get_object_or_404(task_scope(request,member),pk=int(task_id),status='pending')
    try:
        day = parse_date(request.POST.get('date',''))
        if not day or day > timezone.localdate():
            raise ValueError('请填写有效的作业日期，不能晚于今天。')
        size = int(request.POST.get('team_size','1'))
        third_party=int(request.POST.get('third_party_count','0'))
        if not (0 <= size <= 99 and 0 <= third_party <= 99 and size+third_party > 0):
            raise ValueError('请核对作业人数。')
        shift=request.POST.get('shift','')
        if shift and shift not in dict(WorkReport.SHIFT_CHOICES):
            raise ValueError('班次无效。')
        start_raw=request.POST.get('work_start_time','')
        end_raw=request.POST.get('work_end_time','')
        start=parse_time(start_raw) if start_raw else None
        end=parse_time(end_raw) if end_raw else None
        if bool(start_raw)!=bool(end_raw) or (start_raw and (start is None or end is None)):
            raise ValueError('请核对开始和完成时间。')
        catalog = ReferenceCatalog.objects.get(pk=int(request.POST.get('catalog','0')),business=member.team.business)
        if catalog.owner_team_id not in (None,member.team_id):raise ValueError('目录不属于当前团队。')
        if report and report.pest_data.catalog_id!=catalog.pk:raise ValueError('工单目录版本不一致。')
        ids = {int(value) for value in request.POST.getlist('nodes')}
        if not ids:
            raise ValueError('请从作业层级中选择至少一项工作内容。')
        nodes = list(catalog.nodes.filter(pk__in=ids,children__isnull=True))
        if len(nodes) != len(ids):
            raise ValueError('工作内容不属于当前表单版本，或选择了非填报节点。')
        location_ids = {uuid.UUID(value) for value in request.POST.getlist('locations')}
        locations = list(visible_locations(member.team).filter(pk__in=location_ids))
        if not locations or len(locations) != len(location_ids):
            raise ValueError('请选择当前团队有权使用的地点。')
        if task and (catalog.pk!=task.catalog_id or task.location_id not in location_ids or
                     not {s['node_id'] for s in task.selections}.issubset(ids)):
            raise ValueError('请保留任务要求的地点和工作内容。')
        remark=request.POST.get('remark','').strip()
        if len(remark)>10000:raise ValueError('备注最多支持 10000 字。')
    except (ValueError,TypeError,ReferenceCatalog.DoesNotExist):
        # Do not disclose other teams' node/place identifiers.
        return JsonResponse({'success':False,'message':'请核对日期、人数、地点和作业内容；地点或目录不可用时请重新打开表单。'},status=400)
    selections=selection_snapshot(catalog,ids)
    from core.role_utils import resolve_or_create_worker
    from core.workorder_tree_views import _calc_hours
    with transaction.atomic():
        worker, _ = resolve_or_create_worker(request.user)
        editing=report is not None
        if task and not editing:
            task=get_object_or_404(task_scope(request,member).select_for_update(),pk=task.pk,status='pending')
        values=dict(date=day,team_size=size,third_party_count=third_party,shift=shift,work_start_time=start,work_end_time=end,
            team_hours=_calc_hours(start,end,size),third_party_hours=_calc_hours(start,end,third_party),
            zone_names='、'.join(p.name for p in locations),remark=remark,
            work_content='\n'.join(' / '.join(s['path']) for s in selections))
        if editing:
            for field,value in values.items():setattr(report,field,value)
            report.save(update_fields=[*values,'updated_at'])
            from core.models import WorkReportEditLog
            WorkReportEditLog.objects.create(work_report=report,editor=worker,note='编辑植保作业记录')
        else:
            report=WorkReport.all_businesses.create(worker=worker,business_team=member.team,is_pm=bool(task),**values)
            report.ticket_number=f'PPC-PM-{task.pk}' if task else f'PPC-{report.pk}'
            report.save(update_fields=['ticket_number'])
        detail,_=PestWorkData.objects.update_or_create(report=report,defaults=dict(catalog=catalog,selections=selections,
            location_labels=[{'id':str(p.pk),'name':p.name,'code':p.code} for p in locations]))
        detail.locations.set(locations)
        if task and not editing:
            changed=PestTask.objects.filter(pk=task.pk,status='pending',assignee_id=task.assignee_id).update(
                report=report,status='completed',updated_at=timezone.now())
            if not changed:
                transaction.set_rollback(True)
                return JsonResponse({'success':False,'message':'任务状态已有变化，请重新打开任务。'},status=409)
        audit(request,member.team,'pest.workorder.edit' if editing else 'pest.workorder.submit',report.pk)
    return JsonResponse({'success':True,'report_id':report.pk,'number':report.display_number,'message':'植保工单已保存。'})


@require_GET
def pest_reports(request):
    from .management_views import report_list
    return report_list(request)


@require_GET
def pest_report_detail(request, report_id):
    from .management_views import render_page
    member=require_member(request)
    report=get_object_or_404(records(request).prefetch_related('comments__author','edit_logs__editor'),pk=report_id)
    context={'membership':member,'report':report,'can_manage':member.role=='manager' or request.user.is_superuser,
             'can_submit':member.role in ('manager','field') or request.user.is_superuser}
    return render_page(request,'operations/pest_report_detail.html',context,'operations/_pest_report_detail.html')
