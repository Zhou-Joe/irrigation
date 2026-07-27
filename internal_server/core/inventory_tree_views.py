"""Inventory tree CRUD endpoints (jsTree + django-mptt), consumed by the
「库存目录」tab inside the 库存管理 (inventory_management) page.

Mirrors workitem_manage_views.py's structure. Provides:
- GET  /inventory/tree.json                  → jsTree-format flat node list
- GET  /inventory/node/<int:cat_id>/detail/  → single part's stock + recent txns
- POST /inventory/node/<int:cat_id>/save/    → update part's stock/min/main/unit

The existing inventory_category_create/edit/delete/reorder endpoints are
reused as-is for the jsTree contextmenu actions.
"""
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from core.models import InventoryCategory, InventoryPriceRecord, InventoryTransactionLine
from core.role_utils import is_admin


def _price_record_to_dict(rec):
    """Serialize one InventoryPriceRecord for the detail panel / export."""
    return {
        'id': rec.id,
        'date': rec.date.isoformat() if rec.date else '',
        'supplier': rec.supplier or '',
        'unit_price': str(rec.unit_price),   # Decimal → str for JSON safety
        'unit': rec.unit or '',
        'is_current': rec.is_current,
        'note': rec.note or '',
    }


def current_price_for(category):
    """Return the current-price record for a part, or None.

    Rule (mirrors the UI contract): if any record has ``is_current=True``, the
    newest such record wins; otherwise the newest-by-date record wins. The
    model's Meta ordering (``-date, -id``) makes ``.first()`` return the newest.
    """
    marked = category.price_records.filter(is_current=True).first()
    if marked:
        return marked
    return category.price_records.first()


def _iv_to_jstree_node(c):
    """Convert one InventoryCategory to a jsTree node dict.

    `data` carries the part attributes so the right-side detail panel can
    render without a second fetch (except for the transaction list, which is
    lazy-loaded only when the user opens the part).
    """
    nt = c.node_type
    is_low = c.node_type == 'part' and c.current_stock < c.min_stock
    text_suffix = ''
    if nt == 'part':
        # Show stock inline in the tree text so the manager sees levels at a glance.
        text_suffix = f'  ·  {c.current_stock}{c.unit or ""}'
        if is_low:
            text_suffix += '  ⚠'
    return {
        'id': str(c.id),
        'parent': str(c.parent_id) if c.parent_id else '#',
        'text': (c.name_zh or c.code) + text_suffix,
        'icon': 'iv-folder' if nt == 'category' else 'iv-leaf',
        'data': {
            'code': c.code,
            'name_zh': c.name_zh,
            'node_type': nt,
            'current_stock': c.current_stock,
            'min_stock': c.min_stock,
            'is_main_material': c.is_main_material,
            'unit': c.unit,
            'order': c.order,
            'level': c.level,
            'is_low': is_low,
        },
        'li_attr': {'title': f'{c.code} · {nt}'},
        'state': {'opened': c.level < 1},
    }


def _iv_jstree_full():
    """Build the full jsTree node list in one query (mptt nested-set order)."""
    qs = (InventoryCategory.objects.filter(active=True)
          .order_by('tree_id', 'lft'))
    return [_iv_to_jstree_node(c) for c in qs]


@login_required(login_url='core:login')
def inventory_tree_json(request):
    """Return the full InventoryCategory tree as a flat jsTree node list."""
    # Read-only for everyone (no manager gate — workers also see the catalog
    # so they can pick materials on the mobile cart).
    return JsonResponse(_iv_jstree_full(), safe=False)


@login_required(login_url='core:login')
def inventory_node_detail(request, cat_id):
    """Return one part's full detail: attributes + recent 10 transaction lines.

    Used by the right-side detail panel when a part node is selected.
    """
    cat = get_object_or_404(InventoryCategory, pk=cat_id)
    # Recent transactions (latest 10) — same shape as inventory_category_transactions
    # but capped and inlined for the panel (no separate fetch).
    lines_qs = (InventoryTransactionLine.objects
                .filter(category=cat)
                .select_related('transaction', 'transaction__worker',
                                 'transaction__purchase_order')
                .order_by('-transaction__date', '-id')[:10])
    txns = []
    for ln in lines_qs:
        t = ln.transaction
        # 入库 → 正数, 出库 → 负数 (供前端显示带符号数量)
        sign = 1 if (t.operation == '入库') else -1
        txns.append({
            'date': t.date.isoformat() if t.date else '',
            'operation': t.operation,
            'operation_display': t.operation,   # OPERATION_CHOICES 本身就是中文
            'subtype': t.entry_subtype or '',
            'quantity': ln.quantity * sign,
            'unit': cat.unit,
            'counterparty': t.counterparty or '',
            'order_no': t.purchase_order.order_number if t.purchase_order_id else '',
            'worker': t.worker.full_name if t.worker_id and t.worker else '',
            'remark': (t.remark or '')[:80],
        })
    return JsonResponse({
        'success': True,
        'node': {
            'id': cat.id,
            'code': cat.code,
            'name_zh': cat.name_zh,
            'node_type': cat.node_type,
            'current_stock': cat.current_stock,
            'min_stock': cat.min_stock,
            'is_main_material': cat.is_main_material,
            'unit': cat.unit,
            'is_low': cat.node_type == 'part' and cat.current_stock < cat.min_stock,
        },
        'transactions': txns,
        'total_txn_count': InventoryTransactionLine.objects.filter(category=cat).count(),
        # Price-history records (parts only; categories get an empty list).
        # `current_price` carries the resolved current record so the panel can
        # highlight it without recomputing the is_current/fallback rule.
        'price_records': ([_price_record_to_dict(r) for r in cat.price_records.all()]
                          if cat.node_type == 'part' else []),
        'current_price_id': (current_price_for(cat).id
                             if cat.node_type == 'part' and current_price_for(cat) else None),
    })


@require_POST
@login_required(login_url='core:login')
def inventory_node_save(request, cat_id):
    """Update a single part's current_stock / min_stock / is_main_material / unit.

    Replaces the old bulk inventory_save_stock for the new jsTree UI. Manager-only.
    Note: editing current_stock here is allowed (initial value set / correction),
    NOT an inventory transaction — for actual stock movements use 出入库记录.
    """
    from core.role_utils import get_user_role, ROLE_MANAGER, ROLE_SUPER_ADMIN
    role = get_user_role(request.user)
    if role not in (ROLE_MANAGER, ROLE_SUPER_ADMIN):
        return JsonResponse({'success': False, 'message': '无权限'}, status=403)
    cat = get_object_or_404(InventoryCategory, pk=cat_id)
    if cat.node_type != 'part':
        return JsonResponse({'success': False, 'message': '只能编辑部件的库存，目录无库存'}, status=400)

    update_fields = []
    if 'current_stock' in request.POST:
        try:
            cat.current_stock = int(request.POST.get('current_stock'))
            update_fields.append('current_stock')
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'message': '现有库存必须是整数'}, status=400)
    if 'min_stock' in request.POST:
        try:
            cat.min_stock = int(request.POST.get('min_stock'))
            update_fields.append('min_stock')
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'message': '最低库存必须是整数'}, status=400)
    if 'is_main_material' in request.POST:
        cat.is_main_material = request.POST.get('is_main_material') in ('1', 'true', 'on')
        update_fields.append('is_main_material')
    if 'unit' in request.POST:
        cat.unit = (request.POST.get('unit') or '').strip()[:10]
        update_fields.append('unit')

    if not update_fields:
        return JsonResponse({'success': False, 'message': '无字段需要更新'}, status=400)
    with transaction.atomic():
        cat.save(update_fields=update_fields)
    return JsonResponse({
        'success': True,
        'message': f'已更新「{cat.name_zh}」',
        'node': _iv_to_jstree_node(cat),
    })


# ── Price-history CRUD (manager-only, parts only) ──────────────────────
# Mirrors the inventory_node_save permission/guard pattern. Every write path
# keeps at most ONE is_current=True record per category so current_price_for()
# stays unambiguous.

def _require_price_manager(request):
    """Return (ok, error_response). Manager/super-admin gate for price writes."""
    from core.role_utils import get_user_role, ROLE_MANAGER, ROLE_SUPER_ADMIN
    role = get_user_role(request.user)
    if role not in (ROLE_MANAGER, ROLE_SUPER_ADMIN):
        return False, JsonResponse({'success': False, 'message': '无权限'}, status=403)
    return True, None


@require_POST
@login_required(login_url='core:login')
def inventory_price_add(request, cat_id):
    """Add a price record to a part. Clears other is_current flags if this one
    is marked current, so the one-current-price invariant holds."""
    ok, err = _require_price_manager(request)
    if not ok:
        return err
    cat = get_object_or_404(InventoryCategory, pk=cat_id)
    if cat.node_type != 'part':
        return JsonResponse({'success': False, 'message': '只能给部件添加价格记录'}, status=400)
    from datetime import date as date_cls
    from decimal import Decimal, InvalidOperation
    date_str = (request.POST.get('date') or '').strip()
    try:
        rec_date = date_cls.fromisoformat(date_str) if date_str else date_cls.today()
    except ValueError:
        return JsonResponse({'success': False, 'message': '日期格式无效（需 YYYY-MM-DD）'}, status=400)
    try:
        price = Decimal(request.POST.get('unit_price') or '0')
        if price < 0:
            raise InvalidOperation()
    except (InvalidOperation, ValueError):
        return JsonResponse({'success': False, 'message': '单价必须是非负数字'}, status=400)
    supplier = (request.POST.get('supplier') or '').strip()[:200]
    unit = (request.POST.get('unit') or '').strip()[:10]
    note = (request.POST.get('note') or '').strip()[:200]
    is_current = request.POST.get('is_current') in ('1', 'true', 'on')
    with transaction.atomic():
        if is_current:
            cat.price_records.exclude(is_current=False).update(is_current=False)
        rec = InventoryPriceRecord.objects.create(
            category=cat, date=rec_date, supplier=supplier,
            unit_price=price, unit=unit, is_current=is_current, note=note,
        )
    cur = current_price_for(cat)
    return JsonResponse({
        'success': True,
        'message': '价格记录已添加',
        'record': _price_record_to_dict(rec),
        'current_price_id': cur.id if cur else None,
    })


@require_POST
@login_required(login_url='core:login')
def inventory_price_edit(request, record_id):
    """Partial-update a price record. Honors is_current exclusivity."""
    ok, err = _require_price_manager(request)
    if not ok:
        return err
    rec = get_object_or_404(InventoryPriceRecord, pk=record_id)
    from datetime import date as date_cls
    from decimal import Decimal, InvalidOperation
    update_fields = []
    if 'date' in request.POST:
        date_str = (request.POST.get('date') or '').strip()
        try:
            rec.date = date_cls.fromisoformat(date_str) if date_str else date_cls.today()
            update_fields.append('date')
        except ValueError:
            return JsonResponse({'success': False, 'message': '日期格式无效'}, status=400)
    if 'unit_price' in request.POST:
        try:
            rec.unit_price = Decimal(request.POST.get('unit_price') or '0')
            update_fields.append('unit_price')
        except (InvalidOperation, ValueError):
            return JsonResponse({'success': False, 'message': '单价必须是非负数字'}, status=400)
    if 'supplier' in request.POST:
        rec.supplier = (request.POST.get('supplier') or '').strip()[:200]
        update_fields.append('supplier')
    if 'unit' in request.POST:
        rec.unit = (request.POST.get('unit') or '').strip()[:10]
        update_fields.append('unit')
    if 'note' in request.POST:
        rec.note = (request.POST.get('note') or '').strip()[:200]
        update_fields.append('note')
    if 'is_current' in request.POST:
        rec.is_current = request.POST.get('is_current') in ('1', 'true', 'on')
        update_fields.append('is_current')
    if not update_fields:
        return JsonResponse({'success': False, 'message': '无字段需要更新'}, status=400)
    with transaction.atomic():
        # Maintain one-current-per-category invariant.
        if 'is_current' in update_fields and rec.is_current:
            rec.category.price_records.exclude(id=rec.id).update(is_current=False)
        rec.save(update_fields=update_fields)
    cur = current_price_for(rec.category)
    return JsonResponse({
        'success': True,
        'message': '价格记录已更新',
        'record': _price_record_to_dict(rec),
        'current_price_id': cur.id if cur else None,
    })


@require_POST
@login_required(login_url='core:login')
def inventory_price_delete(request, record_id):
    """Delete a price record."""
    ok, err = _require_price_manager(request)
    if not ok:
        return err
    rec = get_object_or_404(InventoryPriceRecord, pk=record_id)
    cat = rec.category
    with transaction.atomic():
        rec.delete()
    cur = current_price_for(cat)
    return JsonResponse({
        'success': True,
        'message': '价格记录已删除',
        'current_price_id': cur.id if cur else None,
    })


@require_POST
@login_required(login_url='core:login')
def inventory_price_set_current(request, record_id):
    """Mark a record as the current price (clears other is_current on its category)."""
    ok, err = _require_price_manager(request)
    if not ok:
        return err
    rec = get_object_or_404(InventoryPriceRecord, pk=record_id)
    with transaction.atomic():
        rec.category.price_records.exclude(id=rec.id).update(is_current=False)
        rec.is_current = True
        rec.save(update_fields=['is_current'])
    return JsonResponse({
        'success': True,
        'message': '已设为当前价格',
        'record': _price_record_to_dict(rec),
    })
