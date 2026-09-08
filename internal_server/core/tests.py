from django.test import TestCase, Client
from core.models import Worker


class WorkerModelTest(TestCase):
    """Test cases for the Worker model."""

    def test_worker_creation(self):
        """Test Worker creation with default values."""
        worker = Worker.objects.create(
            employee_id='EMP001',
            full_name='John Doe'
        )

        # Verify employee_id
        self.assertEqual(worker.employee_id, 'EMP001')
        # Verify full_name
        self.assertEqual(worker.full_name, 'John Doe')
        # Verify active default
        self.assertTrue(worker.active)


# --------------------------------------------------------------------------
# 采购订单 (Purchase Order) — CRUD + inventory integration smoke tests
# --------------------------------------------------------------------------

class PurchaseOrderCRUDTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        cls.admin = User.objects.create_superuser('po_admin', 'a@a.com', 'pass')
        cls.c = Client()
        cls.c.login(username='po_admin', password='pass')

    def _create(self, order_number='PO-1', **extra):
        data = {'order_number': order_number}
        data.update(extra)
        return self.c.post('/purchase-orders/create/', data,
                           HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_create_and_serialize_fields(self):
        r = self._create(po_number='P100', po_amount_untaxed='1234.56',
                         project_name='项目A', project_code='A1')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['success'])
        node = r.json()['node']
        self.assertEqual(node['order_number'], 'PO-1')
        self.assertEqual(node['po_number'], 'P100')
        self.assertEqual(node['po_amount_untaxed'], '1234.56')
        self.assertEqual(node['project_name'], '项目A')
        self.assertEqual(node['project_code'], 'A1')
        self.assertEqual(node['parts'], [])
        self.assertEqual(node['txn_count'], 0)
        return node['id']

    def test_create_duplicate_rejected(self):
        self.test_create_and_serialize_fields()  # PO-1
        r = self._create('PO-1')
        self.assertEqual(r.status_code, 400)
        self.assertIn('已存在', r.json()['message'])

    def test_create_empty_order_number_rejected(self):
        r = self._create('')
        self.assertEqual(r.status_code, 400)
        self.assertIn('不能为空', r.json()['message'])

    def test_create_bad_amount_rejected(self):
        r = self._create('PO-X', po_amount_untaxed='abc')
        self.assertEqual(r.status_code, 400)
        self.assertIn('金额', r.json()['message'])

    def test_edit_preserves_uniqueness(self):
        po_id = self.test_create_and_serialize_fields()  # PO-1
        self._create('PO-2')
        # Clashing rename -> fail.
        r = self.c.post(f'/purchase-orders/{po_id}/edit/', {'order_number': 'PO-2'},
                        HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 400)
        # Valid rename + amount -> succeed.
        r = self.c.post(f'/purchase-orders/{po_id}/edit/',
                        {'order_number': 'PO-1-EDIT', 'po_amount_untaxed': '9999.00'},
                        HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['node']['order_number'], 'PO-1-EDIT')
        self.assertEqual(r.json()['node']['po_amount_untaxed'], '9999.00')

    def test_delete_keeps_txn_but_nulls_fk(self):
        from core.models import (PurchaseOrder, InventoryTransaction,
                                 InventoryCategory)
        po = PurchaseOrder.objects.create(order_number='PO-DEL')
        w = Worker.objects.create(full_name='tester')
        cat = InventoryCategory.objects.create(code='X1', name_zh='part', node_type='part')
        t = InventoryTransaction.objects.create(
            date='2026-07-04', worker=w, operation='入库', entry_subtype='采购',
            order_no='PO-DEL', purchase_order=po)
        po_id = po.id
        r = self.c.post(f'/purchase-orders/{po_id}/delete/',
                        HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['success'])
        self.assertFalse(PurchaseOrder.objects.filter(id=po_id).exists())
        t.refresh_from_db()
        self.assertIsNone(t.purchase_order)        # SET_NULL held
        self.assertEqual(t.order_no, 'PO-DEL')     # free-text preserved


class PurchaseOrderInventoryIntegrationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        cls.admin = User.objects.create_superuser('po_admin2', 'b@b.com', 'pass')
        cls.c = Client()
        cls.c.login(username='po_admin2', password='pass')

    def test_modal_data_exposes_purchase_orders(self):
        from core.models import PurchaseOrder
        PurchaseOrder.objects.create(order_number='PO-A')
        PurchaseOrder.objects.create(order_number='PO-B')
        r = self.c.get('/api/modal/inventory-data/')
        self.assertEqual(r.status_code, 200)
        vals = r.json()['purchase_orders']
        self.assertIn('PO-A', vals)
        self.assertIn('PO-B', vals)

    def test_purchase_inbound_auto_links_po(self):
        # Submitting 入库-采购 with an order_no that matches a PO links the txn.
        from core.models import (PurchaseOrder, InventoryTransaction,
                                 InventoryCategory)
        PurchaseOrder.objects.create(order_number='AUTO-LINK')
        w = Worker.objects.create(full_name='tester')
        cat = InventoryCategory.objects.create(code='AL1', name_zh='part', node_type='part')
        lines = [{'category': cat.id, 'quantity': 5, 'unit': '个'}]
        import json
        r = self.c.post('/mobile/inventory/v2/', {
            'operation': '入库', 'entry_subtype': '采购', 'order_no': 'AUTO-LINK',
            'lines': json.dumps(lines), 'date': '2026-07-04',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['success'])
        t = InventoryTransaction.objects.get(order_no='AUTO-LINK')
        self.assertIsNotNone(t.purchase_order)
        self.assertEqual(t.purchase_order.order_number, 'AUTO-LINK')

