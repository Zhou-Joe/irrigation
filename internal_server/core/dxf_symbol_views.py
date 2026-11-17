"""Irrigation managers review and reuse CAD valve shape examples."""
import json
import re

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .dxf_views import _pipeline_dxf_gate
from .models import DxfValveShapeTemplate, PipeValve, PipelineImportBatch
from . import dxf_symbols as symbols


def template_items(user):
    return [{'id':str(row.pk),'name':row.name,'valve_type':row.valve_type,
             'valve_type_display':row.get_valve_type_display(),
             'can_delete':row.created_by_id==user.pk or user.is_superuser or user.is_staff}
            for row in DxfValveShapeTemplate.objects.filter(active=True)]


def _source(request):
    token=request.POST.get('token') or ''
    if not re.fullmatch(r'[a-f0-9]{32}',token):raise ValueError('请重新解析当前图纸')
    if request.POST.get('batch_id'):
        batch=get_object_or_404(PipelineImportBatch,pk=request.POST['batch_id'],source_token=token)
        source=batch.source_geometry
        return source.get('layers',{}),source.get('labels',[])
    from .dxf_pipeline_utils import _resolve_parsed_geometry
    layers,_,labels,_=_resolve_parsed_geometry(None,token,None)
    return layers,labels


@login_required
@require_http_methods(['GET','POST'])
@never_cache
def templates(request):
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'success':False,'error':'无权限'},status=403)
    if request.method=='GET':
        return JsonResponse({'success':True,'templates':template_items(request.user)})
    if request.POST.get('action')=='delete':
        try:row=get_object_or_404(DxfValveShapeTemplate,pk=request.POST.get('id'),active=True)
        except (ValueError,TypeError,ValidationError):return JsonResponse({'success':False,'error':'图形模板无效'},status=400)
        if not (row.created_by_id==request.user.pk or request.user.is_superuser or request.user.is_staff):
            return JsonResponse({'success':False,'error':'只有创建者或管理员可以删除模板'},status=403)
        row.active=False;row.save(update_fields=['active'])
        return JsonResponse({'success':True,'templates':template_items(request.user)})
    try:
        if request.POST.get('action')=='recognize':
            layers,labels=_source(request)
            return JsonResponse({'success':True,'shape_candidates':symbols.recognize(layers,labels,symbols.load_templates()),
                                 'templates':template_items(request.user)})
        name=(request.POST.get('name') or '').strip()
        kind=request.POST.get('valve_type')
        if not name or len(name)>100:raise ValueError('请输入不超过 100 字的图形名称')
        if kind not in dict(PipeValve.VALVE_TYPE_CHOICES):raise ValueError('请选择阀门类型')
        refs=json.loads(request.POST.get('parts_json') or '[]')
        layers,labels=_source(request)
        paths=symbols.sample_from_refs(layers,refs)
        definition=symbols.make_template(paths,name,kind,labels)
        with transaction.atomic():
            row,created=DxfValveShapeTemplate.objects.get_or_create(fingerprint=definition['fingerprint'],
                valve_type=kind,active=True,defaults={'name':name,'definition':definition,'created_by':request.user})
        return JsonResponse({'success':True,'id':str(row.pk),'created':created,'templates':template_items(request.user)})
    except (ValueError,TypeError,KeyError) as error:
        return JsonResponse({'success':False,'error':str(error) or '图形样本无效'},status=400)
