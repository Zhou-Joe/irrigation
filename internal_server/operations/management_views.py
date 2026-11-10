"""Management adapters for the shared web/PWA shell, scoped to the active team."""
import uuid
from collections import Counter
from datetime import timedelta
from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.validators import validate_email
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Sum, Q, F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils import translation
from django.utils.dateparse import parse_date
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.debug import sensitive_post_parameters

from core.models import WorkReportComment
from core.submissions import submission
from .access import require_member, visible_locations, audit
from .catalog_service import current_catalog, node_rows, revise_catalog, selectable_catalogs, selection_snapshot, CatalogConflict
from .models import Location, Membership, PestMaintenancePlan, PestTask, Team
from .planning import eligible_members, generate_due, task_scope


def pest_member(request,manager=False):
    member=require_member(request,manager=manager)
    if member.team.business.code!='pest-control':raise PermissionDenied('请在植保视图使用此功能。')
    return member


def ajax(request):
    return request.headers.get('X-Requested-With')=='XMLHttpRequest'


def render_page(request,template,context,fragment=None,target='opsResults'):
    if ajax(request) and fragment:
        return JsonResponse({'success':True,'html':render_to_string(fragment,context,request=request),'target':target})
    return render(request,template,context)


def catalogue_data(member):
    catalog=current_catalog(member.team)
    return {'catalog_id':catalog.pk if catalog else None,'nodes':node_rows(catalog),
        'versions':[{'id':v.pk,'name':v.name,'time':timezone.localtime(v.imported_at).strftime('%Y-%m-%d %H:%M'),
                     'source':v.source_name} for v in selectable_catalogs(member.team).order_by('-imported_at','-pk')[:20]]}


@login_required
@require_GET
def business_data(request):
    member=pest_member(request)
    return render(request,'operations/business_data.html',{'membership':member,
        'can_manage':member.role=='manager' or request.user.is_superuser,'location_kinds':Location.KINDS})


@login_required
@require_GET
def catalog_data(request):
    return JsonResponse({'success':True,**catalogue_data(pest_member(request))})


@login_required
@require_POST
def catalog_save(request):
    member=pest_member(request,True)
    if request.POST.get('team')!=str(member.team_id):
        return JsonResponse({'success':False,'message':'业务视图已变化，请重新打开本页。'},status=409)
    try:
        action=request.POST.get('action','edit');selected=None
        if action=='activate':
            with transaction.atomic():
                Team.objects.filter(pk=member.team_id).update(work_catalog_id=F('work_catalog_id'))
                team=Team.objects.select_related('business','work_catalog').get(pk=member.team_id)
                current=current_catalog(team)
                if str(current.pk if current else '')!=request.POST.get('catalog',''):
                    raise CatalogConflict('工作目录已有更新，请重新加载后再保存。')
                version=get_object_or_404(selectable_catalogs(team),pk=int(request.POST.get('version','0')))
                team.work_catalog=version;team.save(update_fields=['work_catalog'])
        else:
            version,selected=revise_catalog(member.team,request.POST.get('catalog',''),action,
                request.POST.get('id'),label=request.POST.get('label'),parent=request.POST.get('parent'),
                kind=request.POST.get('kind'),order=request.POST.get('order') or 0)
        audit(request,member.team,'catalog.'+action,version.pk)
        member.team.refresh_from_db()
        return JsonResponse({'success':True,'message':'工作目录已更新，历史工单与已派任务保持原有内容。',
                             'selected':selected,**catalogue_data(member)})
    except (ValueError,TypeError) as error:
        return JsonResponse({'success':False,'message':str(error)},status=409 if isinstance(error,CatalogConflict) else 400)


def filtered_records(request):
    from .map_views import records
    qs=records(request);today=timezone.localdate()
    error=''
    try:
        start=parse_date(request.GET.get('date_from','')) or today-timedelta(days=29)
        end=parse_date(request.GET.get('date_to','')) or today
    except ValueError:
        start=end=today;error='请填写有效的查询日期。';qs=qs.none()
    if start>end or (end-start).days>366:
        error='查询时间范围应为连续 1–367 天。';qs=qs.none()
    qs=qs.filter(date__range=(start,end));query=request.GET.get('q','').strip()[:150]
    if query:qs=qs.filter(Q(ticket_number__icontains=query)|Q(zone_names__icontains=query)|
        Q(work_content__icontains=query)|Q(remark__icontains=query)|Q(worker__full_name__icontains=query))
    worker=request.GET.get('worker','')
    if worker.isdigit():qs=qs.filter(worker__user_id=int(worker))
    place=request.GET.get('location','')
    if place:
        try:qs=qs.filter(pest_data__locations__pk=uuid.UUID(place))
        except ValueError:qs=qs.none()
    category=request.GET.get('category','')[:255]
    if category:
        identifiers=[identifier for identifier,selections in qs.values_list('pk','pest_data__selections')
            if any(item.get('path',[None])[0]==category for item in selections if item.get('path'))]
        qs=qs.filter(pk__in=identifiers)
    tab=request.GET.get('tab','records')
    if tab=='pending':qs=qs.filter(is_pending_repair=True)
    elif tab=='difficult':qs=qs.filter(is_difficult=True,is_difficult_resolved=False)
    return qs.order_by('-date','-pk'),{'date_from':start.isoformat(),'date_to':end.isoformat(),
        'query':query,'selected_worker':worker,'selected_location':place,'selected_category':category,'active_tab':tab,'filter_error':error}


def filter_options(request,member):
    catalog=current_catalog(member.team)
    return {'places':visible_locations(member.team).select_related(None).only('id','name','code'),
        'staff':Membership.objects.filter(team=member.team,user__is_active=True).select_related('user'),
        'categories':catalog.nodes.filter(parent__isnull=True) if catalog else [],
        'membership':member,'can_manage':member.role=='manager' or request.user.is_superuser}


def record_context(request):
    member=pest_member(request);qs,filters=filtered_records(request)
    totals=qs.aggregate(total=Count('pk'),hours=Sum('team_hours'),external_hours=Sum('third_party_hours'))
    tasks=task_scope(request,member)
    state=request.GET.get('task_status','pending')
    if state=='overdue':tasks=tasks.filter(status='pending',deadline__lt=timezone.localdate())
    elif state in ('pending','completed','skipped'):tasks=tasks.filter(status=state)
    context={**filters,**filter_options(request,member),'totals':totals,
        'reports':Paginator(qs,20).get_page(request.GET.get('page')),
        'tasks':Paginator(tasks,20).get_page(request.GET.get('page')),'task_status':state,'today':timezone.localdate()}
    return context


@login_required
@require_GET
def report_list(request):
    return render_page(request,'operations/pest_reports.html',record_context(request),'operations/_pest_report_results.html')


@login_required
@require_GET
def statistics(request):
    member=pest_member(request);qs,filters=filtered_records(request)
    totals=qs.aggregate(total=Count('pk'),hours=Sum('team_hours'),external_hours=Sum('third_party_hours'),
        pending=Count('pk',filter=Q(is_pending_repair=True)),difficult=Count('pk',filter=Q(is_difficult=True,is_difficult_resolved=False)))
    days=list(qs.values('date').annotate(count=Count('pk'),hours=Sum('team_hours')).order_by('date'))
    roots=Counter()
    for selections in qs.values_list('pest_data__selections',flat=True).iterator():
        roots.update({item['path'][0] for item in selections if item.get('path')})
    category_rows=[{'label':label,'count':count} for label,count in roots.most_common()]
    staff=list(qs.values('worker__full_name').annotate(count=Count('pk'),hours=Sum('team_hours'),external_hours=Sum('third_party_hours')).order_by('-count'))
    places=list(qs.values('pest_data__locations__name').annotate(count=Count('pk',distinct=True)).order_by('-count')[:30])
    context={**filters,**filter_options(request,member),'totals':totals,'daily':days,'category_rows':category_rows,
        'staff_rows':staff,'place_rows':places,'max_daily':max((row['count'] for row in days),default=1),
        'max_category':max(roots.values(),default=1)}
    return render_page(request,'operations/statistics.html',context,'operations/_statistics_results.html')


@login_required
@require_GET
def report_export(request):
    pest_member(request);qs,filters=filtered_records(request)
    if filters['filter_error']:return JsonResponse({'success':False,'message':filters['filter_error']},status=400)
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font, PatternFill
    workbook=Workbook(write_only=True);sheet=workbook.create_sheet('植保作业记录')
    sheet.freeze_panes='A2'
    headings=['工单编号','日期','班次','处理人','作业地点','工作内容','开始时间','完成时间','本组人数','第三方人数','本组工时','第三方工时','待跟进','疑难问题','备注']
    for column,width in zip('ABCDEFGHIJKLMNO',[18,14,12,18,35,70,14,14,14,14,14,14,12,12,50]):sheet.column_dimensions[column].width=width
    header=[]
    for title in headings:
        cell=WriteOnlyCell(sheet,value=title);cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='1B4332');header.append(cell)
    sheet.append(header)
    for report in qs.iterator():
        values=[report.display_number,report.date.isoformat(),report.shift,report.worker.full_name,
            report.zone_names,report.work_content,str(report.work_start_time or ''),str(report.work_end_time or ''),
            report.team_size,report.third_party_count,report.team_hours,report.third_party_hours,
            '是' if report.is_pending_repair else '否','是' if report.is_difficult else '否',report.remark]
        row=[]
        for value in values:
            cell=WriteOnlyCell(sheet,value=value)
            if isinstance(value,str):cell.data_type='s'
            row.append(cell)
        sheet.append(row)
    output=BytesIO();workbook.save(output)
    response=HttpResponse(output.getvalue(),content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition']=content_disposition_header(True,f'植保工单_{filters["date_from"]}_{filters["date_to"]}.xlsx')
    response['Cache-Control']='private, no-store'
    return response


@login_required
@require_POST
def report_action(request,pk):
    from .map_views import records, require_writer
    member=pest_member(request);report=get_object_or_404(records(request),pk=pk)
    if request.POST.get('team')!=str(member.team_id):return JsonResponse({'success':False,'message':'业务视图已变化，请重新打开工单。'},status=409)
    return _report_action(request,member,report)


@submission('pest-report-action')
def _report_action(request,member,report):
    from .map_views import require_writer
    action=request.POST.get('action');text=request.POST.get('body','').strip()
    with transaction.atomic():
        if action=='comment':
            require_writer(request)
            if not text or len(text)>5000:return JsonResponse({'success':False,'message':'请填写跟进说明（最多 5000 字）。'},status=400)
            from core.role_utils import resolve_or_create_worker
            worker,_=resolve_or_create_worker(request.user)
            WorkReportComment.objects.create(work_report=report,author=worker,body=text)
        elif action in ('pending','resolve','difficult','resolve_difficult'):
            require_member(request,manager=True)
            if action=='pending':report.is_pending_repair=True
            elif action=='resolve':report.is_pending_repair=False
            elif action=='difficult':report.is_difficult=True;report.is_difficult_resolved=False
            else:report.is_difficult_resolved=True
            report.save(update_fields=['is_pending_repair','is_difficult','is_difficult_resolved','updated_at'])
        else:return JsonResponse({'success':False,'message':'操作无效。'},status=400)
        audit(request,member.team,'pest.report.'+action,report.pk)
    return JsonResponse({'success':True,'message':'工单已更新。','refresh':True})


@login_required
@require_GET
def plans(request):
    member=pest_member(request);qs=PestMaintenancePlan.objects.filter(team=member.team).prefetch_related('locations','assignees')
    context={**filter_options(request,member),'plans':qs,'frequency_units':PestMaintenancePlan.FREQUENCIES,
        'today':timezone.localdate(),'plan_options':[]}
    if context['can_manage']:
        context['plan_options']=[{'id':p.pk,'name':p.name,'frequency_value':p.frequency_value,'frequency_unit':p.frequency_unit,
            'anchor_date':p.anchor_date.isoformat(),'active':p.active,'notes':p.notes,
            'locations':[str(place.pk) for place in p.locations.all()],'assignees':[u.pk for u in p.assignees.all()],
            'nodes':[s['node_id'] for s in p.selections],'catalog_id':p.catalog_id} for p in qs]
    else:context['plans']=qs.filter(assignees=request.user)
    catalog=current_catalog(member.team)
    context['plan_leaves']=[]
    if catalog:
        rows=node_rows(catalog);by_id={row['id']:row for row in rows};parents={row['parent'] for row in rows}
        for row in rows:
            if row['id'] in parents:continue
            trail=[];current=row
            while current:trail.insert(0,current['label']);current=by_id.get(current['parent'])
            context['plan_leaves'].append({'id':row['id'],'label':' / '.join(trail)})
    context['catalog']=catalog
    return render_page(request,'operations/plans.html',context,'operations/_plan_results.html')


@login_required
@require_POST
def plan_save(request):
    member=pest_member(request,True)
    if request.POST.get('team')!=str(member.team_id):return JsonResponse({'success':False,'message':'业务视图已变化，请重新打开计划。'},status=409)
    return _plan_save(request,member)


@submission('pest-plan')
def _plan_save(request,member):
    try:
        pk=request.POST.get('id');action=request.POST.get('action','save')
        plan=get_object_or_404(PestMaintenancePlan,pk=int(pk),team=member.team) if pk else PestMaintenancePlan(team=member.team,created_by=request.user)
        if action=='toggle':
            plan.active=not plan.active;plan.save(update_fields=['active','updated_at'])
        else:
            name=request.POST.get('name','').strip();unit=request.POST.get('frequency_unit');value=int(request.POST.get('frequency_value','0'))
            day=parse_date(request.POST.get('anchor_date',''))
            if not name or len(name)>150 or not day or unit not in dict(PestMaintenancePlan.FREQUENCIES) or not 1<=value<=366:
                raise ValueError('请核对计划名称、开始日期和周期（1–366）。')
            place_ids={uuid.UUID(identifier) for identifier in request.POST.getlist('locations')}
            locations=list(visible_locations(member.team).filter(pk__in=place_ids))
            users={int(identifier) for identifier in request.POST.getlist('assignees')}
            valid=set(eligible_members(member.team).filter(user_id__in=users).values_list('user_id',flat=True))
            if not locations or len(locations)!=len(place_ids) or not users or users!=valid:raise ValueError('请选择有效地点及本团队已启用的负责人员。')
            catalog=current_catalog(member.team)
            if not catalog or str(catalog.pk)!=request.POST.get('catalog'):raise ValueError('作业目录已有变化，请重新打开计划。')
            selections=selection_snapshot(catalog,request.POST.getlist('nodes'))
            with transaction.atomic():
                changed=not plan.pk or (plan.anchor_date,plan.frequency_value,plan.frequency_unit)!=(day,value,unit)
                plan.name=name;plan.catalog=catalog;plan.selections=selections
                plan.anchor_date=day;plan.frequency_unit=unit;plan.frequency_value=value
                if changed:plan.next_cycle=day
                plan.notes=request.POST.get('notes','').strip()[:5000];plan.active=request.POST.get('active')=='1'
                plan.save();plan.locations.set(locations);plan.assignees.set(users)
        audit(request,member.team,'pest.plan.'+action,plan.pk)
        return JsonResponse({'success':True,'message':'计划已保存，已派发任务保持原有安排。','refresh':True})
    except (ValueError,TypeError,ValidationError) as error:
        return JsonResponse({'success':False,'message':str(error)},status=400)


@login_required
@require_POST
def dispatch(request):
    member=pest_member(request,True)
    if request.POST.get('team')!=str(member.team_id):return JsonResponse({'success':False,'message':'业务视图已变化，请重新打开本页。'},status=409)
    result=generate_due(team=member.team)
    audit(request,member.team,'pest.plan.dispatch',member.team_id,**result)
    return JsonResponse({'success':not result['errors'],'message':f'已生成 {result["generated"]} 项任务。'+' '.join(result['errors']), 'refresh':True})


@login_required
@require_POST
def task_action(request,pk):
    member=pest_member(request,True)
    if request.POST.get('team')!=str(member.team_id):return JsonResponse({'success':False,'message':'业务视图已变化，请重新打开本页。'},status=409)
    task=get_object_or_404(task_scope(request,member),pk=pk)
    if task.status!='pending':return JsonResponse({'success':False,'message':'任务已处理，不能重复操作。'},status=409)
    action=request.POST.get('action')
    with transaction.atomic():
        if action=='skip':
            note=request.POST.get('notes','').strip()
            if not note:return JsonResponse({'success':False,'message':'请填写跳过原因。'},status=400)
            changed=PestTask.objects.filter(pk=task.pk,status='pending').update(status='skipped',notes=note[:1000],updated_at=timezone.now())
        elif action=='assign':
            user_id=request.POST.get('assignee','')
            if not user_id.isdigit() or not eligible_members(member.team).filter(user_id=int(user_id)).exists():
                return JsonResponse({'success':False,'message':'请选择本团队已启用的负责人员。'},status=400)
            changed=PestTask.objects.filter(pk=task.pk,status='pending').update(assignee_id=int(user_id),updated_at=timezone.now())
        else:return JsonResponse({'success':False,'message':'操作无效。'},status=400)
        if not changed:return JsonResponse({'success':False,'message':'任务已被其他人处理，请刷新任务。'},status=409)
        audit(request,member.team,'pest.task.'+action,task.pk)
    return JsonResponse({'success':True,'message':'任务已更新。','refresh':True})


@login_required
@require_http_methods(['GET','POST'])
@sensitive_post_parameters('old_password','new_password','confirm_password')
def profile(request):
    member=pest_member(request);user=request.user
    if request.method=='POST':
        try:
            action=request.POST.get('action','details')
            if action=='password':
                if not user.check_password(request.POST.get('old_password','')):raise ValueError('原密码不正确。')
                password=request.POST.get('new_password','')
                with translation.override('zh-hans'):
                    try:validate_password(password,user)
                    except ValidationError as error:raise ValueError('；'.join(str(message) for message in error.messages))
                if password!=request.POST.get('confirm_password'):raise ValueError('两次输入的新密码不一致。')
                user.set_password(password);user.save(update_fields=['password']);update_session_auth_hash(request,user)
            elif action=='details':
                name=request.POST.get('full_name','').strip();email=request.POST.get('email','').strip()
                if not name or len(name)>150:raise ValueError('姓名应为 1–150 个字符。')
                if email:validate_email(email)
                user.first_name=name;user.last_name='';user.email=email;user.save(update_fields=['first_name','last_name','email'])
            else:raise ValueError('操作无效。')
            audit(request,member.team,'account.'+action,user.pk)
            return JsonResponse({'success':True,'message':'账号资料已保存。' if action=='details' else '密码已更新。'})
        except (ValueError,ValidationError) as error:
            return JsonResponse({'success':False,'message':'；'.join(error.messages) if isinstance(error,ValidationError) else str(error)},status=400)
    return render(request,'operations/profile.html',{'membership':member})
