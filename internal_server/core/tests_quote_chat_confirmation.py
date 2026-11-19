import json
import uuid
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core import signing
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from .models import AIConversation, AIExecutionLease, AISettings, InventoryCategory, InventoryPriceRecord, SubmissionReceipt
from .inventory_quotes import DRAFT_SALT


@override_settings(MULTI_TEAM_ENABLED=False, ALLOWED_HOSTS=['testserver'])
class QuoteChatConfirmationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('quote-manager', is_staff=True)
        self.client.force_login(self.user)
        self.part = InventoryCategory.objects.create(code='Q-PART', name_zh='Valve', node_type='part', unit='each')
        self.key = str(uuid.uuid4())
        source = {'row_id': 'r1', 'name': 'Valve', 'code': 'Q-PART', 'unit': 'each', 'unit_price': '12.50', 'source_path': ''}
        token = signing.dumps({'owner': self.user.pk, 'draft': self.key, 'source': 'vendor.xlsx', 'rows': [source]}, salt=DRAFT_SALT, compress=True)
        self.payload = {'token': token, 'submission_key': self.key, 'confirmed': 'yes',
            'supplier': 'Vendor A', 'quote_date': '2026-11-16',
            'items': json.dumps([{**source, 'action': 'existing', 'category_id': self.part.pk}])}
        AISettings.objects.create(enabled=True, api_base_url='https://fixture.invalid', api_key='test', model_name='fixture')
        self.thread = f'u{self.user.pk}-abcdef12'
        AIConversation.objects.create(id=self.thread, owner=self.user)

    def test_import_destination_follows_request_and_evidence(self):
        from .ai_agent import _inventory_import_destination
        order = {'order_number':'PO-12', 'purchase_date':'2026-11-19'}
        for request in ('请导入这张订单', 'Import this purchase order', '导入这份采购单', 'Import PO #12'):
            self.assertEqual(_inventory_import_destination(request, order), 'order', request)
        self.assertEqual(_inventory_import_destination('导入报价', order), 'quote')
        self.assertEqual(_inventory_import_destination('导入附件', order), 'order')
        self.assertEqual(_inventory_import_destination('导入附件', {'quote_date':'2026-11-19'}), 'quote')
        self.assertEqual(_inventory_import_destination('导入附件', {}), 'choose')
        self.assertEqual(_inventory_import_destination('导入附件', {**order, 'quote_date':'2026-11-19'}), 'choose')
        self.assertEqual(_inventory_import_destination('从报价生成订单', {}, 'order'), 'order')
        self.assertEqual(_inventory_import_destination('Import this purchase order', order, 'quote'), 'choose')

    def save(self):
        return self.client.post('/inventory/quotes/confirm/', self.payload)

    def test_purchase_import_requires_quantity_and_creates_one_order_on_replay(self):
        from .models import PurchaseOrder
        row = json.loads(self.payload['items'])[0]
        self.payload.update(destination='order', order_number='IR-145')
        self.assertEqual(self.save().status_code, 400)
        self.assertFalse(PurchaseOrder.objects.exists())
        self.payload['items'] = json.dumps([{**row, 'quantity': 8}])
        first = self.save()
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(self.save().json()['order_id'], first.json()['order_id'])
        po = PurchaseOrder.objects.get(order_number='IR-145')
        self.assertEqual(po.purchase_date.isoformat(), self.payload['quote_date'])
        self.assertIsNone(po.received_date)
        line = po.planned_lines.get()
        self.assertEqual((line.category, line.quantity, line.supplier), (self.part, 8, 'Vendor A'))
        self.assertEqual(str(line.unit_price), '12.50')
        self.assertFalse(InventoryPriceRecord.objects.exists())

    def test_reviewed_save_and_retries_create_one_price_and_verified_chat_receipt(self):
        first, second = self.save(), self.save()
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(InventoryPriceRecord.objects.count(), 1)
        record = InventoryPriceRecord.objects.get()
        self.assertEqual(str(record.unit_price), '12.50')
        self.assertEqual(record.supplier, 'Vendor A')
        self.assertFalse(record.is_current)
        with patch('core.ai_views._stream_via_queue', return_value=iter(())) as stream:
            response = self.client.post('/api/ai/chat', json.dumps({'message': '确认保存报价',
                'thread_id': self.thread, 'quote_receipt': self.key}), content_type='application/json')
            self.assertEqual(response.status_code, 200)
            list(response.streaming_content)
            receipt = stream.call_args.kwargs['quote_receipt']
            self.assertEqual(receipt['submission_key'], self.key)
            self.assertEqual(receipt['result']['prices_added'], 1)
            response.close()
        self.assertEqual(InventoryPriceRecord.objects.count(), 1)

    def test_chat_cannot_create_a_price_from_an_invented_or_foreign_receipt(self):
        self.assertEqual(self.save().status_code, 200)
        other = User.objects.create_user('other-quote-manager', is_staff=True)
        self.client.force_login(other)
        for key in (self.key, str(uuid.uuid4()), {'prices_added': 999}, 'bad'):
            response = self.client.post('/api/ai/chat', json.dumps({'message': '确认写入', 'quote_receipt': key}), content_type='application/json')
            self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(InventoryPriceRecord.objects.count(), 1)

    def test_other_submission_kinds_are_not_quotation_confirmation(self):
        SubmissionReceipt.objects.create(owner=self.user, key=self.key, kind='workorder',
            fingerprint='x', status_code=200, response={'success': True, 'prices_added': 999})
        response = self.client.post('/api/ai/chat', json.dumps({'message': '确认', 'quote_receipt': self.key}), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(InventoryPriceRecord.objects.exists())

    def test_signed_draft_explicit_confirmation_and_manager_permission_still_apply(self):
        for patch_values in ({'token': self.payload['token'] + 'bad'}, {'confirmed': 'no'}, {'supplier': ''}):
            response = self.client.post('/inventory/quotes/confirm/', {**self.payload, **patch_values})
            self.assertGreaterEqual(response.status_code, 400)
        visitor = User.objects.create_user('quote-visitor')
        from .models import Worker
        Worker.objects.create(user=visitor, employee_id='Q-visitor', full_name='Visitor')
        self.client.force_login(visitor)
        self.assertEqual(self.save().status_code, 403)
        self.assertFalse(InventoryPriceRecord.objects.exists())
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post('/inventory/quotes/confirm/', self.payload).status_code, 403)


@override_settings(MULTI_TEAM_ENABLED=False)
class QuoteReceiptHistoryTests(TransactionTestCase):
    def test_success_is_persisted_and_reported_without_an_llm_or_snapshot_call(self):
        from .ai_views import _stream_via_queue
        user = User.objects.create_user('quote-history-manager', is_staff=True)
        thread = f'u{user.pk}-abcdef12'
        conversation = AIConversation.objects.create(id=thread, owner=user)
        AIExecutionLease.objects.create(conversation=conversation, owner=user,
            expires_at=timezone.now() + timezone.timedelta(minutes=5))
        agent = Mock()
        receipt = {'submission_key': str(uuid.uuid4()), 'result': {'success': True,
            'created_parts_count': 0, 'prices_added': 2, 'duplicate_prices': 1}}
        with patch('core.ai_agent.build_agent', return_value=agent), patch('core.ai_agent.ensure_workspace') as snapshot:
            frames = ''.join(_stream_via_queue('确认写入', thread, user.pk, quote_receipt=receipt))
        self.assertIn('2 条供应商报价记录', frames)
        self.assertIn('1 条重复价格', frames)
        self.assertIn('"event": "done"', frames)
        snapshot.assert_not_called()
        agent.stream.assert_not_called()
        messages = agent.update_state.call_args.args[1]['messages']
        self.assertEqual(messages[0].content, '确认写入')
        self.assertEqual(messages[1].additional_kwargs['quote_receipt'], receipt)
