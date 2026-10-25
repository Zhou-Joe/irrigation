"""Exactly-once inventory state changes, including SQLite without row locks."""
from django.db import transaction
from django.utils import timezone

from .models import InventoryTransaction, InventoryTransactionEditLog, move_stock_for_txn


def transition(ids, action, editor=None):
    choices = {'confirm': ('pending', 'confirmed', 1), 'unconfirm': ('confirmed', 'pending', -1),
               'restore': ('removed', 'confirmed', 1)}
    count = 0
    # Selection can be stale: the conditional UPDATE inside each transaction
    # is the authority, not the candidate object's status or select_for_update.
    candidates = InventoryTransaction.objects.filter(pk__in=set(ids), consumption_mode='actual')
    if action == 'remove':
        candidates = candidates.exclude(confirm_status='removed')
    else:
        candidates = candidates.filter(confirm_status=choices[action][0])
    for candidate in candidates:
        old = candidate.confirm_status
        target = 'removed' if action == 'remove' else choices[action][1]
        delta = (-1 if old == 'confirmed' else 0) if action == 'remove' else choices[action][2]
        with transaction.atomic():
            claimed = InventoryTransaction.objects.filter(pk=candidate.pk, confirm_status=old,
                consumption_mode='actual').update(confirm_status=target, updated_at=timezone.now())
            if not claimed:
                continue
            candidate.confirm_status = target
            if delta:
                move_stock_for_txn(candidate, delta)
            InventoryTransactionEditLog.objects.create(transaction=candidate, editor=editor,
                note={'confirm': '流水确认（计入台账和库存）', 'unconfirm': '取消确认（回滚库存）',
                      'remove': '流水移除（已确认库存已回滚）', 'restore': '恢复流水（重新计入库存）'}[action])
            reconcile_purchase_order(candidate.purchase_order_id)
            count += 1
    return count


def reconcile_purchase_order(po_id):
    """A completed order must cease to be completed when accepted receipts change."""
    if not po_id:
        return
    from .models import PurchaseOrder
    from django.db.models import Sum
    po = PurchaseOrder.objects.filter(pk=po_id, is_completed=True).first()
    if not po:
        return
    planned = dict(po.planned_lines.values('category_id').annotate(qty=Sum('quantity')).values_list('category_id', 'qty'))
    actual = dict(po.transactions.filter(operation='入库', entry_subtype='采购', confirm_status='confirmed',
        consumption_mode='actual').values('lines__category_id').annotate(qty=Sum('lines__quantity'))
        .values_list('lines__category_id', 'qty'))
    if planned != actual:
        PurchaseOrder.objects.filter(pk=po_id).update(is_completed=False)
