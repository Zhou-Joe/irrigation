"""WorkItem tree CRUD endpoints (jsTree + django-mptt), consumed by the
「工单类型」tab inside the 作业计划 (pm_management) page.

This module used to also expose a standalone manage page
(/work-items/manage/); that route and view were removed when the tree moved
into a tab. The 6 JSON endpoints below remain — the tab's jsTree calls them.

Endpoints:
- GET  /work-items/manage/tree.json       → jsTree-format flat node list
- GET  /work-items/manage/<int:id>/detail/→ node attributes + recent entries
- POST /work-items/manage/create/         → {parent_id?, name_zh, value_type, ...}
- POST /work-items/manage/<int:id>/edit/  → rename / update attributes
                                            (full-form save — supports partial)
- POST /work-items/manage/<int:id>/delete/→ refuse if WorkReportEntry references
- POST /work-items/manage/<int:id>/move/  → reparent + reorder (drag-drop)

All endpoints are manager-only (role_utils.is_admin). Returns uniform
{success: bool, message: str} JSON.
"""
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.models import WorkItem, WorkReportEntry
from core.role_utils import is_admin


def _wi_to_jstree_node(wi):
    """Convert one WorkItem to a jsTree node dict."""
    vt_display = dict(WorkItem.VALUE_TYPE_CHOICES).get(wi.value_type, wi.value_type)
    return {
        'id': str(wi.id),
        'parent': str(wi.parent_id) if wi.parent_id else '#',
        'text': wi.name_zh or wi.name_en or wi.code,
        'icon': 'wj-folder' if wi.value_type == 'group' else 'wj-leaf',
        'data': {
            'code': wi.code,
            'name_zh': wi.name_zh,
            'name_en': wi.name_en,
            'section': wi.section,
            'value_type': wi.value_type,
            'value_type_display': vt_display,
            'unit': wi.unit,
            'is_project_scoped': wi.is_project_scoped,
            'active': wi.active,
            'order': wi.order,
            'level': wi.level,
        },
        'li_attr': {'title': f'{wi.code} · {vt_display}'},
        'state': {'opened': wi.level < 1},
    }


def _wi_jstree_full():
    """Build the full jsTree node list in one query (mptt nested-set order)."""
    qs = WorkItem.objects.filter(active=True).order_by('tree_id', 'lft')
    return [_wi_to_jstree_node(wi) for wi in qs]


@login_required(login_url='core:login')
def workitem_tree_json(request):
    """Return the full WorkItem tree as a flat jsTree node list."""
    if not is_admin(request.user):
        return JsonResponse({'success': False, 'message': '无权限'}, status=403)
    return JsonResponse(_wi_jstree_full(), safe=False)


@login_required(login_url='core:login')
def workitem_node_detail(request, node_id):
    """Return one node's full detail: attributes + recent 10 referencing entries.

    Used by the right-side detail panel when a WorkItem node is selected in
    the 工单类型 tab. Mirrors inventory_node_detail's shape so the pm page's
    right panel can reuse the same UX pattern (inline edit + recent history).
    """
    if not is_admin(request.user):
        return JsonResponse({'success': False, 'message': '无权限'}, status=403)
    node = get_object_or_404(WorkItem, pk=node_id)
    vt_display = dict(WorkItem.VALUE_TYPE_CHOICES).get(node.value_type, node.value_type)
    section_display = dict(WorkItem.SECTION_CHOICES).get(node.section, node.section) if node.section else ''

    # Recent referencing entries (latest 10) — same shape as the inventory
    # detail panel's transaction list: dates + quantities + project/workorder.
    entries_qs = (WorkReportEntry.objects
                  .filter(work_item=node)
                  .select_related('work_report', 'pm_work_order', 'project')
                  .order_by('-updated_at', '-id')[:10])
    entries = []
    for e in entries_qs:
        wr = e.work_report
        pm = e.pm_work_order
        # Prefer the regular work-order if both FKs somehow set (rare).
        owner = wr or pm
        owner_label = ''
        owner_id = None
        if wr:
            owner_label = f'工单 #{wr.id}'
            owner_id = wr.id
        elif pm:
            owner_label = f'PM #{pm.id}'
            owner_id = pm.id
        proj = e.project
        # Date: prefer the regular work-order's date, else PM work-order's date.
        e_date = ''
        if wr:
            e_date = wr.date
        elif pm:
            e_date = pm.date
        entries.append({
            'id': e.id,
            'owner_label': owner_label,
            'owner_id': owner_id,
            'owner_type': 'work_report' if wr else ('pm_work_order' if pm else ''),
            'date': e_date.isoformat() if e_date else '',
            'count': e.count or 0,
            'status': e.status or '',
            'text_value': (e.text_value or '')[:80],
            'project_name': proj.name if proj else '',
            'has_photos': bool(e.photos),
        })
    total_count = WorkReportEntry.objects.filter(work_item=node).count()

    # Children count (for the detail panel to show "子节点" count).
    child_count = node.children.filter(active=True).count()

    return JsonResponse({
        'success': True,
        'node': {
            'id': node.id,
            'code': node.code,
            'name_zh': node.name_zh,
            'name_en': node.name_en,
            'section': node.section,
            'section_display': section_display,
            'value_type': node.value_type,
            'value_type_display': vt_display,
            'unit': node.unit,
            'status_options': node.status_options or [],
            'is_project_scoped': node.is_project_scoped,
            'active': node.active,
            'level': node.level,
            'child_count': child_count,
        },
        'entries': entries,
        'total_entry_count': total_count,
    })


@require_POST
@login_required(login_url='core:login')
def workitem_create(request):
    """Create a new WorkItem node. Code auto-derived from parent + sibling count."""
    if not is_admin(request.user):
        return JsonResponse({'success': False, 'message': '无权限'}, status=403)
    name_zh = (request.POST.get('name_zh') or '').strip()
    if not name_zh:
        return JsonResponse({'success': False, 'message': '请填写名称'}, status=400)
    value_type = (request.POST.get('value_type') or 'count').strip()
    if value_type not in dict(WorkItem.VALUE_TYPE_CHOICES):
        return JsonResponse({'success': False, 'message': '值类型无效'}, status=400)

    parent_id = request.POST.get('parent_id', '').strip()
    parent = None
    if parent_id and parent_id != '#':
        try:
            parent = WorkItem.objects.get(pk=int(parent_id))
        except (WorkItem.DoesNotExist, ValueError):
            return JsonResponse({'success': False, 'message': '父节点不存在'}, status=400)

    # Derive a stable code: parent's code (or empty for roots) + next sibling
    # index. Code is the idempotency key for the seed command; we keep it
    # stable-ish but DON'T try to renumber siblings when one is inserted
    # (too expensive for 1300+ nodes). New nodes get a high-numbered suffix.
    sib_count = WorkItem.objects.filter(parent=parent).count()
    prefix = (parent.code + '.') if parent and parent.code else ''
    code = f'{prefix}x{sib_count + 1}' if not parent else f'{prefix}{sib_count + 1}'
    # Ensure uniqueness (defensive — auto-generated codes shouldn't collide,
    # but a hand-renamed sibling might have grabbed this slot).
    if WorkItem.objects.filter(code=code).exists():
        code = f'{code}-{WorkItem.objects.filter(parent=parent).count() + 100}'

    section = (request.POST.get('section') or (parent.section if parent else '')).strip()
    if section and section not in dict(WorkItem.SECTION_CHOICES):
        return JsonResponse({'success': False, 'message': '章节无效'}, status=400)

    unit = (request.POST.get('unit') or '').strip()
    is_project_scoped = request.POST.get('is_project_scoped') in ('1', 'true', 'on')

    with transaction.atomic():
        node = WorkItem.objects.create(
            code=code,
            parent=parent,
            name_zh=name_zh,
            name_en=(request.POST.get('name_en') or '').strip(),
            section=section,
            value_type=value_type,
            unit=unit,
            is_project_scoped=is_project_scoped,
            order=sib_count,
            active=True,
        )
    return JsonResponse({
        'success': True,
        'message': f'已创建节点 {node.name_zh}（code={node.code}）',
        'node': _wi_to_jstree_node(node),
    })


@require_POST
@login_required(login_url='core:login')
def workitem_edit(request, node_id):
    """Rename / update attributes. Does NOT touch tree structure.

    Supports PARTIAL updates: only fields present in POST are changed. This
    lets the right-side detail panel save single fields (e.g. just `unit` or
    `is_project_scoped`) without forcing the caller to resend every field.
    The full-form modal always sends all fields, so behavior is unchanged for
    that path.
    """
    if not is_admin(request.user):
        return JsonResponse({'success': False, 'message': '无权限'}, status=403)
    node = get_object_or_404(WorkItem, pk=node_id)

    update_fields = []
    if 'name_zh' in request.POST:
        name_zh = (request.POST.get('name_zh') or '').strip()
        if not name_zh:
            return JsonResponse({'success': False, 'message': '请填写名称'}, status=400)
        node.name_zh = name_zh
        update_fields.append('name_zh')
    if 'name_en' in request.POST:
        node.name_en = (request.POST.get('name_en') or '').strip()
        update_fields.append('name_en')
    if 'value_type' in request.POST:
        value_type = (request.POST.get('value_type') or '').strip()
        if value_type not in dict(WorkItem.VALUE_TYPE_CHOICES):
            return JsonResponse({'success': False, 'message': '值类型无效'}, status=400)
        node.value_type = value_type
        update_fields.append('value_type')
    if 'unit' in request.POST:
        node.unit = (request.POST.get('unit') or '').strip()
        update_fields.append('unit')
    if 'is_project_scoped' in request.POST:
        node.is_project_scoped = request.POST.get('is_project_scoped') in ('1', 'true', 'on')
        update_fields.append('is_project_scoped')
    if 'section' in request.POST:
        sec = (request.POST.get('section') or '').strip()
        if sec and sec not in dict(WorkItem.SECTION_CHOICES):
            return JsonResponse({'success': False, 'message': '章节无效'}, status=400)
        node.section = sec
        update_fields.append('section')

    if not update_fields:
        return JsonResponse({'success': False, 'message': '无字段需要更新'}, status=400)
    with transaction.atomic():
        node.save(update_fields=update_fields)
    return JsonResponse({
        'success': True,
        'message': f'已更新节点 {node.name_zh}',
        'node': _wi_to_jstree_node(node),
    })


@require_POST
@login_required(login_url='core:login')
def workitem_delete(request, node_id):
    """Delete a node. Refused if it has WorkReportEntry references (PROTECT
    semantics live on the FK, but we surface a friendly message before the DB
    raises IntegrityError). Also refused if it still has children — delete
    children first.
    """
    if not is_admin(request.user):
        return JsonResponse({'success': False, 'message': '无权限'}, status=403)
    node = get_object_or_404(WorkItem, pk=node_id)
    if WorkReportEntry.objects.filter(work_item_id=node.id).exists():
        cnt = WorkReportEntry.objects.filter(work_item_id=node.id).count()
        return JsonResponse({
            'success': False,
            'message': f'该节点被 {cnt} 条工单引用，无法删除（PROTECT）',
        }, status=400)
    child_count = node.children.count()
    if child_count:
        return JsonResponse({
            'success': False,
            'message': f'该节点还有 {child_count} 个子节点，请先删除子节点',
        }, status=400)
    code, name = node.code, node.name_zh
    with transaction.atomic():
        node.delete()
    return JsonResponse({'success': True, 'message': f'已删除节点 {name}（{code}）'})


@require_POST
@login_required(login_url='core:login')
def workitem_move(request, node_id):
    """Reparent + reorder. jsTree's dnd plugin sends {new_parent_id, position}.

    `position` is the 0-based index among the new parent's children. We honor
    it by reordering siblings' `order` fields. mptt's `move_to` handles the
    nested-set recompute.
    """
    if not is_admin(request.user):
        return JsonResponse({'success': False, 'message': '无权限'}, status=403)
    node = get_object_or_404(WorkItem, pk=node_id)
    new_parent_raw = (request.POST.get('new_parent_id') or '').strip()
    position_raw = (request.POST.get('position') or '').strip()

    new_parent = None
    if new_parent_raw and new_parent_raw != '#':
        try:
            new_parent = WorkItem.objects.get(pk=int(new_parent_raw))
        except (WorkItem.DoesNotExist, ValueError):
            return JsonResponse({'success': False, 'message': '目标父节点不存在'}, status=400)
    # Forbid moving a node under its own descendant (would create a cycle).
    if new_parent and (new_parent.id == node.id or node.get_descendants(include_self=True)
                                                                    .filter(id=new_parent.id).exists()):
        return JsonResponse({'success': False, 'message': '不能移动到自己的子节点下'}, status=400)

    try:
        position = int(position_raw) if position_raw.isdigit() else None
    except ValueError:
        position = None

    with transaction.atomic():
        # Re-parent: mptt move_to a specific sibling slot.
        if position is not None and position == 0:
            # First child of new parent.
            first_sib = (WorkItem.objects.filter(parent=new_parent)
                         .exclude(id=node.id).order_by('order', 'lft').first())
            if first_sib:
                node.move_to(first_sib, position='left')
            else:
                node.parent = new_parent
                node.save()
        elif position is not None:
            siblings = [w for w in WorkItem.objects.filter(parent=new_parent)
                                                       .exclude(id=node.id)
                                                       .order_by('order', 'lft')]
            target = siblings[min(position - 1, len(siblings) - 1)] if siblings else None
            if target:
                node.move_to(target, position='right')
            else:
                node.parent = new_parent
                node.save()
        else:
            # No position specified — just reparent (append).
            node.parent = new_parent
            node.save()
        # Re-number `order` for ALL siblings (including moved node) so the
        # explicit order column matches the visual position.
        sibs = list(WorkItem.objects.filter(parent=new_parent).order_by('lft'))
        for i, s in enumerate(sibs):
            if s.order != i:
                WorkItem.objects.filter(id=s.id).update(order=i)

    return JsonResponse({
        'success': True,
        'message': f'已移动节点 {node.name_zh}',
        'node': _wi_to_jstree_node(node),
    })
