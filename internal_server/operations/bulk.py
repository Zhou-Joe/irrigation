"""Atomic, team-scoped batch operations for locations and explicit sharing."""
import csv
import io
import uuid

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from core.submissions import submission
from .access import require_member, visible_locations, audit
from .models import Location, LocationGrant, Team, Membership
from .location_filters import matching_locations


def failure(message, status=400, **extra):
    return JsonResponse({'success':False,'message':message,**extra},status=status)


def scope(request):
    member=require_member(request,manager=True)
    if request.POST.get('team')!=str(member.team_id):
        return member,failure('团队已变化，请重新打开批量操作。',409)
    return member,None


def parse_rows(request, member):
    text=request.POST.get('rows','')
    upload=request.FILES.get('file')
    if upload:
        if upload.size>2*1024*1024:raise ValueError('文件不能超过 2 MB。')
        raw=upload.read()
        try:text=raw.decode('utf-8-sig')
        except UnicodeDecodeError:text=raw.decode('gb18030')
    if len(text)>2*1024*1024:raise ValueError('批量内容过大。')
    text=text.lstrip('\ufeff')
    delimiter='\t' if '\t' in text else ','
    rows=[row for row in csv.reader(io.StringIO(text),delimiter=delimiter) if any(v.strip() for v in row)]
    headers={'地点名称':'name','名称':'name','name':'name','地点编号':'code','编号':'code','code':'code',
        '类型':'kind','地点类型':'kind','kind':'kind','上级编号':'parent','parent':'parent',
        '纬度':'latitude','latitude':'latitude','经度':'longitude','longitude':'longitude',
        '说明':'description','位置说明':'description','description':'description'}
    fields=['name','code','kind','parent','latitude','longitude','description']
    header=bool(rows and rows[0][0].strip() in ('地点名称','名称','name'))
    if header:
        fields=[headers.get(v.strip(),'') for v in rows.pop(0)]
        if '' in fields or len(set(fields))!=len(fields):raise ValueError('表头不识别或存在重复列。')
    if not rows or len(rows)>500:raise ValueError('每批填写 1–500 个地点。')
    kinds={label:key for key,label in Location.KINDS}
    existing=list(visible_locations(member.team))
    by_code={}
    for place in existing:
        if place.code:by_code.setdefault(place.code,[]).append(place)
    default_parent=None
    if request.POST.get('parent'):
        default_parent=next((p for p in existing if str(p.pk)==request.POST['parent']),None)
        if default_parent is None:raise ValueError('上级地点不可用。')
    instances=[];references=[];codes={};errors=[]
    own_codes=set(Location.objects.filter(owner_team=member.team).exclude(code='').values_list('code',flat=True))
    for index,row in enumerate(rows,start=2 if header else 1):
        if len(row)>len(fields):
            errors.append({'row':index,'message':'列数超过表头；含逗号的内容请用引号括起或从 Excel 直接粘贴。'});continue
        data=dict(zip(fields,[v.strip() for v in row]))
        code=data.get('code','')
        kind=data.get('kind') or request.POST.get('kind','building')
        kind=kinds.get(kind,kind)
        place=Location(owner_team=member.team,name=data.get('name',''),code=code,kind=kind,map_display='pin',
            latitude=data.get('latitude') or None,longitude=data.get('longitude') or None,
            description=data.get('description',''))
        try:
            if code and (code in own_codes or code in codes):raise ValidationError('本团队或当前批次已有相同编号。')
            place.clean_fields(exclude=['parent'])
            place.clean()
            if code:codes[code]=place
            instances.append((index,place));references.append(data.get('parent',''))
        except ValidationError as exc:errors.append({'row':index,'message':'；'.join(exc.messages)})
    if errors:return [],errors
    for (index,place),reference in zip(instances,references):
        if reference:
            matches=[codes[reference]] if reference in codes else by_code.get(reference,[])
            if len(matches)!=1:errors.append({'row':index,'message':'上级编号不存在或不唯一。'});continue
            place.parent=matches[0]
        else:place.parent=default_parent
    if errors:return [],errors
    for index,place in instances:
        try:place.clean()
        except ValidationError as exc:errors.append({'row':index,'message':'；'.join(exc.messages)})
    return [place for _,place in instances],errors


@login_required
@require_POST
def create(request):
    member,error=scope(request)
    if error:return error
    if request.POST.get('action')=='preview':return _create(request,preview=True)
    return _save(request)


@submission('location-batch')
def _save(request):return _create(request,preview=False)


def _create(request,preview):
    member=require_member(request,manager=True)
    try:
        places,errors=parse_rows(request,member)
        if errors:return failure('请修正标出的行，尚未创建任何地点。',errors=errors)
        summary=[{'name':p.name,'code':p.code,'kind':p.get_kind_display(),'positioned':p.latitude is not None} for p in places]
        if preview:return JsonResponse({'success':True,'preview':True,'count':len(places),'rows':summary})
        with transaction.atomic():
            Location.objects.bulk_create(places)
            audit(request,member.team,'location.batch.create',str(uuid.uuid4()),count=len(places),ids=[str(p.pk) for p in places])
        return JsonResponse({'success':True,'count':len(places),'message':f'已创建 {len(places)} 个地点。','ids':[str(p.pk) for p in places]})
    except (ValueError,UnicodeError,csv.Error,ValidationError) as exc:return failure(str(exc))
    except IntegrityError:return failure('编号已被使用，请刷新预览后重试。',409)


@login_required
@require_POST
def share(request):
    member,error=scope(request)
    if error:return error
    if request.POST.get('source')=='irrigation' and member.team.business.code!='irrigation' and request.user.is_superuser:
        owner=Team.objects.filter(business__code='irrigation',legacy_irrigation_access=True,active=True,business__active=True).first()
        if owner is None:return failure('灌溉所属团队不可用。')
        request._bulk_source_owner=owner
    return _share(request)


@submission('location-batch-sharing')
def _share(request):
    member=require_member(request,manager=True)
    if getattr(request,'_bulk_source_owner',None):
        member=Membership(user=request.user,team=request._bulk_source_owner,role='manager')
    try:
        targets={int(value) for value in request.POST.getlist('targets')}
        teams=list(Team.objects.filter(pk__in=targets,active=True,business__active=True).exclude(pk=member.team_id))
        if not teams or len(teams)!=len(targets):raise ValueError('请选择有效的接收团队。')
        action=request.POST.get('action','grant')
        if action not in ('grant','revoke'):raise ValueError('共享操作无效。')
        ids={uuid.UUID(value) for value in request.POST.getlist('locations')}
        places=list(Location.objects.filter(pk__in=ids,owner_team=member.team))
        if len(places)!=len(ids):raise PermissionDenied('只能批量共享或取消自己团队拥有的地点。')
        from core.models import Zone
        zone_ids={int(value) for value in request.POST.getlist('zones')}
        source=request.POST.get('source','locations')
        if zone_ids or source=='irrigation':
            if member.team.business.code!='irrigation' or not member.team.legacy_irrigation_access:
                raise PermissionDenied('请由灌溉团队经理选择共享原区域。')
            zones=Zone.objects.all()
            if request.POST.get('all_matching')=='1':
                query=request.POST.get('q','').strip()[:150]
                if query:zones=zones.filter(Q(code__icontains=query)|Q(name__icontains=query))
            else:zones=zones.filter(pk__in=zone_ids)
            zones=list(zones.select_related('shared_location')[:1001])
            if request.POST.get('all_matching')!='1' and len(zones)!=len(zone_ids):raise ValueError('部分区域不存在。')
        else:
            zones=[]
            if request.POST.get('all_matching')=='1':
                # Apply precisely the same filters as the list and map. Starting
                # from owned locations excludes read-only shared places without
                # ever changing another team's grants.
                qs=matching_locations(Location.objects.filter(owner_team=member.team),member.team,request.POST)
                places=list(qs[:1001])
                if not places:raise ValueError('当前筛选结果中没有本团队拥有的可共享地点。')
        if not 1<=len(zones)+len(places)<=1000:raise ValueError('每批选择 1–1000 个地点或区域。')
        # Preflight all references and code collisions before the first write.
        codes=set(Location.objects.filter(owner_team=member.team).exclude(code='').values_list('code',flat=True))
        linked=[];new=[]
        for zone in zones:
            location=getattr(zone,'shared_location',None)
            if location:
                if location.owner_team_id!=member.team_id:raise PermissionDenied('区域引用属于其他团队。')
                linked.append(location)
            elif action=='grant':
                if zone.code and zone.code in codes:raise ValueError(f'编号 {zone.code} 已被其他地点使用。')
                if zone.code:codes.add(zone.code)
                new.append(Location(owner_team=member.team,legacy_zone=zone,code=zone.code,name=zone.name or zone.code))
        with transaction.atomic():
            Location.objects.bulk_create(new)
            places=list({p.pk:p for p in [*places,*linked,*new]}.values())
            if action=='grant':
                LocationGrant.objects.bulk_create([LocationGrant(location=p,team=t,created_by=request.user) for p in places for t in teams],ignore_conflicts=True)
            else:LocationGrant.objects.filter(location__in=places,team__in=teams).delete()
            audit(request,member.team,'location.batch.'+action,str(uuid.uuid4()),count=len(places),targets=list(targets))
        return JsonResponse({'success':True,'count':len(places),'message':f'已{"共享" if action=="grant" else "取消共享"} {len(places)} 个地点。'})
    except (ValueError,TypeError) as exc:return failure(str(exc))
    except IntegrityError:return failure('地点编号发生冲突，尚未完成操作，请刷新后重试。',409)
