"""Confirm-gated stock lifecycle tests.

Invariant: ``current_stock`` only reflects transactions with
``consumption_mode='actual'`` AND ``confirm_status='confirmed'``. Every state
transition (submit / confirm / unconfirm / remove / restore / edit-rebuild /
estimate promotion) must keep the balance consistent with that single rule.
"""

import json
from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase, Client

from core.models import (
    InventoryCategory, InventoryTransaction, Worker, WorkReport,
)
from core.workorder_tree_views import _save_workorder_materials


class ConfirmGatedStockTests(TestCase):
    """Standalone form + ledger endpoints + work-order materials."""

    def setUp(self):
        self.mgr_user = User.objects.create_user('mgr', password='x', is_staff=True)
        self.wk_user = User.objects.create_user('wk', password='x')
        self.worker = Worker.objects.create(
            user=self.wk_user, employee_id='T0001', full_name='测试工人')
        self.cat = InventoryCategory.objects.create(
            code='TEST-CAT', name_zh='测试球阀', current_stock=100, unit='个')
        self.mgr = Client()
        self.mgr.force_login(self.mgr_user)
        self.wkc = Client()
        self.wkc.force_login(self.wk_user)

    def stock(self):
        self.cat.refresh_from_db()
        return self.cat.current_stock

    def post_txn(self, client, op='出库', subtype='日常维护', mode=None,
                 txn_id=None, qty=5):
        data = {
            'operation': op, 'entry_subtype': subtype,
            'lines': json.dumps(
                [{'category': self.cat.id, 'quantity': qty, 'unit': '个'}]),
            'date': date.today().isoformat(),
        }
        if mode:
            data['consumption_mode'] = mode
        if txn_id:
            data['txn_id'] = str(txn_id)
        return client.post('/mobile/inventory/v2/', data, HTTP_HOST='127.0.0.1',
                           HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def txn_action(self, action, ids):
        from django.urls import reverse
        url = reverse('core:inventory_txn_%s' % action)
        return self.mgr.post(url, [('txn_ids', str(i)) for i in ids],
                             HTTP_HOST='127.0.0.1',
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    # ── standalone form ────────────────────────────────────────────────

    def test_worker_submit_pending_no_deduction(self):
        r = self.post_txn(self.wkc)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['success'])
        t = InventoryTransaction.objects.order_by('-id').first()
        self.assertEqual(t.confirm_status, 'pending')
        self.assertEqual(self.stock(), 100)   # untouched until confirmed

    def test_confirm_deducts_and_unconfirm_refunds(self):
        self.post_txn(self.wkc)
        t = InventoryTransaction.objects.order_by('-id').first()
        self.txn_action('confirm', [t.id])
        t.refresh_from_db()
        self.assertEqual(t.confirm_status, 'confirmed')
        self.assertEqual(self.stock(), 95)
        self.txn_action('unconfirm', [t.id])
        t.refresh_from_db()
        self.assertEqual(t.confirm_status, 'pending')
        self.assertEqual(self.stock(), 100)

    def test_remove_from_confirmed_refunds_restore_reapplies(self):
        self.post_txn(self.wkc)
        t = InventoryTransaction.objects.order_by('-id').first()
        self.txn_action('confirm', [t.id])            # 95
        self.txn_action('remove', [t.id])             # refund → 100
        t.refresh_from_db()
        self.assertEqual(t.confirm_status, 'removed')
        self.assertEqual(self.stock(), 100)
        self.txn_action('restore', [t.id])            # re-apply → 95
        t.refresh_from_db()
        self.assertEqual(t.confirm_status, 'confirmed')
        self.assertEqual(self.stock(), 95)

    def test_remove_from_pending_never_moves_stock(self):
        self.post_txn(self.wkc)
        t = InventoryTransaction.objects.order_by('-id').first()
        self.txn_action('remove', [t.id])
        t.refresh_from_db()
        self.assertEqual(t.confirm_status, 'removed')
        self.assertEqual(self.stock(), 100)
        self.txn_action('restore', [t.id])            # removed → confirmed applies
        t.refresh_from_db()
        self.assertEqual(self.stock(), 95)

    def test_manager_submit_deducts_immediately(self):
        self.post_txn(self.mgr)
        t = InventoryTransaction.objects.order_by('-id').first()
        self.assertEqual(t.confirm_status, 'confirmed')
        self.assertEqual(self.stock(), 95)

    def test_edit_pending_untouched_then_confirm_uses_new_qty(self):
        self.post_txn(self.wkc)                       # pending, stock 100
        t = InventoryTransaction.objects.order_by('-id').first()
        r = self.post_txn(self.wkc, txn_id=t.id, qty=8)
        self.assertTrue(r.json()['success'])
        self.assertEqual(self.stock(), 100)           # still pending → no movement
        self.txn_action('confirm', [t.id])
        self.assertEqual(self.stock(), 92)            # new quantity applied

    def test_edit_confirmed_reverses_old_applies_new(self):
        self.post_txn(self.mgr, qty=5)                # confirmed → 95
        t = InventoryTransaction.objects.order_by('-id').first()
        self.post_txn(self.mgr, txn_id=t.id, qty=9)   # -5 +9 → 96
        self.assertEqual(self.stock(), 96)

    def test_inbound_pending_no_add_until_confirm(self):
        self.post_txn(self.wkc, op='入库', subtype='采购')
        t = InventoryTransaction.objects.order_by('-id').first()
        self.assertEqual(self.stock(), 100)           # no add while pending
        self.txn_action('confirm', [t.id])
        self.assertEqual(self.stock(), 105)

    # ── estimated consumption ──────────────────────────────────────────

    def _estimate(self, client):
        self.post_txn(client, op='出库', subtype='项目', mode='estimated')

    def test_worker_estimate_promotion_waits_for_ledger_confirm(self):
        self._estimate(self.wkc)
        t = InventoryTransaction.objects.order_by('-id').first()
        self.assertEqual(t.consumption_mode, 'estimated')
        self.assertEqual(self.stock(), 100)
        r = self.wkc.post('/inventory/estimate/%d/confirm/' % t.id,
                          {'quantities': '{}'}, HTTP_HOST='127.0.0.1',
                          HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(r.json()['success'])
        t.refresh_from_db()
        self.assertEqual(t.consumption_mode, 'actual')
        self.assertEqual(t.confirm_status, 'pending')  # worker promotion
        self.assertEqual(self.stock(), 100)            # still untouched
        self.txn_action('confirm', [t.id])
        self.assertEqual(self.stock(), 95)             # deducted at ledger confirm

    def test_manager_estimate_promotion_deducts_now(self):
        self._estimate(self.mgr)
        t = InventoryTransaction.objects.order_by('-id').first()
        r = self.mgr.post('/inventory/estimate/%d/confirm/' % t.id,
                          {'quantities': json.dumps(
                              {str(ln.id): 7 for ln in t.lines.all()})},
                          HTTP_HOST='127.0.0.1',
                          HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(r.json()['success'])
        t.refresh_from_db()
        self.assertEqual(t.confirm_status, 'confirmed')
        self.assertEqual(self.stock(), 93)             # revised qty applied

    # ── work-order materials ───────────────────────────────────────────

    def _report(self):
        return WorkReport.objects.create(
            date=date.today(), worker=self.worker)

    def test_workorder_worker_materials_pending_then_confirm(self):
        rep = self._report()
        from django.db import transaction
        with transaction.atomic():
            _save_workorder_materials(rep, [
                {'category': self.cat.id, 'quantity': 4, 'unit': '个'}],
                submitter_is_manager=False)
        t = rep.material_consumptions.first()
        self.assertEqual(t.confirm_status, 'pending')
        self.assertEqual(self.stock(), 100)           # not deducted yet
        self.txn_action('confirm', [t.id])
        self.assertEqual(self.stock(), 96)

    def test_workorder_manager_materials_deduct_at_save(self):
        rep = self._report()
        from django.db import transaction
        with transaction.atomic():
            _save_workorder_materials(rep, [
                {'category': self.cat.id, 'quantity': 4, 'unit': '个'}],
                submitter_is_manager=True)
        self.assertEqual(self.stock(), 96)

    def test_workorder_rebuild_confirmed_refunds_and_reapplies(self):
        rep = self._report()
        from django.db import transaction
        with transaction.atomic():
            _save_workorder_materials(rep, [
                {'category': self.cat.id, 'quantity': 4, 'unit': '个'}],
                submitter_is_manager=True)             # 96
        with transaction.atomic():
            _save_workorder_materials(rep, [
                {'category': self.cat.id, 'quantity': 6, 'unit': '个'}],
                submitter_is_manager=True)             # +4 −6 → 94
        self.assertEqual(self.stock(), 94)
        t = rep.material_consumptions.first()
        self.assertEqual(t.confirm_status, 'confirmed')  # carried over

    def test_workorder_rebuild_pending_moves_nothing(self):
        rep = self._report()
        from django.db import transaction
        with transaction.atomic():
            _save_workorder_materials(rep, [
                {'category': self.cat.id, 'quantity': 4, 'unit': '个'}],
                submitter_is_manager=False)            # pending, stock 100
        with transaction.atomic():
            _save_workorder_materials(rep, [
                {'category': self.cat.id, 'quantity': 7, 'unit': '个'}],
                submitter_is_manager=False)            # rebuild, still pending
        self.assertEqual(self.stock(), 100)
        t = rep.material_consumptions.first()
        self.assertEqual(t.confirm_status, 'pending')
