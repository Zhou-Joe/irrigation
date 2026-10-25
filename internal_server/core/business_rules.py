"""Shared operation scopes and validated values for web and API writes."""
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .role_utils import get_django_user, get_worker_for_user, is_admin, is_field_worker


def require_workorder_user(user):
    if not (is_admin(user) or is_field_worker(user)):
        raise PermissionDenied('无权限操作维修工单')


def inventory_scope(user):
    from .models import InventoryTransaction
    qs = InventoryTransaction.objects.all()
    if is_admin(user):
        return qs
    worker = get_worker_for_user(user) if is_field_worker(user) else None
    return qs.filter(worker=worker) if worker else qs.none()


def require_inventory_edit(user, txn):
    if not is_admin(user) and txn.confirm_status in ('confirmed', 'removed'):
        raise PermissionDenied('已确认或已移除的流水由经理修改，请联系经理')


def integer_quantity(raw, *, zero=False):
    try:
        value = Decimal(str(raw))
        if (not value.is_finite() or value != value.to_integral_value()
                or value < (0 if zero else 1) or value > 2147483647):
            raise ValueError
        return int(value)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('物料数量必须为' + ('非负' if zero else '正') + '整数') from None


def material_lines(lines):
    """Validate everything before refunding/replacing any existing ledger rows."""
    from .models import InventoryCategory
    if not isinstance(lines, list) or any(not isinstance(row, dict) for row in lines):
        raise ValueError('材料明细必须是列表')
    normalized = {}
    for row in lines:
        cid = integer_quantity(row.get('category'))
        qty = integer_quantity(row.get('quantity'))
        if cid in normalized:
            raise ValueError('同一物料不能重复添加')
        normalized[cid] = dict(category=cid, quantity=qty, unit=str(row.get('unit') or '').strip()[:20])
    valid = set(InventoryCategory.objects.filter(pk__in=normalized, node_type='part', active=True).values_list('pk', flat=True))
    if set(normalized) - valid:
        raise ValueError('物料不存在或已停用，请刷新后重试')
    return list(normalized.values())


def water_window(start, end):
    values = []
    for raw in (start, end):
        try:
            value = parse_datetime(raw) if isinstance(raw, str) else raw
            if value is None:
                raise ValueError
            if timezone.is_naive(value):
                value = timezone.make_aware(value, timezone.get_default_timezone())
            values.append(value)
        except (TypeError, ValueError):
            raise ValueError('请填写有效的需求开始和结束时间') from None
    if values[1] <= values[0]:
        raise ValueError('结束时间必须晚于开始时间')
    return tuple(values)


def water_owner_kwargs(user):
    return dict(submitter=get_worker_for_user(user), submitter_user=get_django_user(user))


def atomic_operation(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        from django.db import transaction, IntegrityError
        from django.http import JsonResponse
        try:
            with transaction.atomic():
                return view(*args,**kwargs)
        except (ValueError,InvalidOperation) as exc:
            return JsonResponse({'success':False,'message':str(exc) or '数值无效'},status=400)
        except IntegrityError:
            return JsonResponse({'success':False,'message':'记录已变化或存在重复，请刷新后重试'},status=409)
    return wrapped
