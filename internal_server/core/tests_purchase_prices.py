import json
from decimal import Decimal
from django.contrib.auth.models import User
from django.test import TestCase
from core.models import InventoryCategory,InventoryPriceRecord,PurchaseOrder,PurchaseOrderLine
from core.inventory_tree_views import current_price_for

class PurchasePriceTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_superuser('po-price','','test-only');self.client.force_login(self.user)
        self.part=InventoryCategory.objects.create(name_zh='Fixture part',node_type='part',unit='个')
    def save_order(self,price,po=None):
        data={'order_number':'PRICE-TEST','lines':json.dumps([{'category':self.part.pk,'quantity':2,'unit':'个','unit_price':price}])}
        return self.client.post(f'/purchase-orders/{po.pk}/edit/' if po else '/purchase-orders/create/',data)
    def test_new_price_history_and_unchanged_edit_preserve_newer_catalog_price(self):
        self.assertEqual(self.save_order('12.50').status_code,200)
        po=PurchaseOrder.objects.get(order_number='PRICE-TEST')
        self.assertEqual(po.planned_lines.get().unit_price,Decimal('12.50'))
        self.assertEqual(current_price_for(self.part).unit_price,Decimal('12.50'))
        InventoryPriceRecord.objects.filter(category=self.part).update(is_current=False)
        newer=InventoryPriceRecord.objects.create(category=self.part,unit_price=20,is_current=True)
        self.assertEqual(self.save_order('12.50',po).status_code,200)
        self.assertEqual(current_price_for(self.part).pk,newer.pk)
        self.assertEqual(InventoryPriceRecord.objects.count(),2)
        self.assertEqual(self.save_order('15.25',po).status_code,200)
        self.assertEqual(current_price_for(self.part).unit_price,Decimal('15.25'))
        self.assertEqual(InventoryPriceRecord.objects.filter(is_current=True).count(),1)
    def test_invalid_prices_rollback_order_and_zero_is_an_explicit_price(self):
        for value in ('NaN','Infinity','-1','1.234','10000000000'):
            self.assertEqual(self.save_order(value).status_code,400)
            self.assertFalse(PurchaseOrder.objects.exists())
            self.assertFalse(InventoryPriceRecord.objects.exists())
        self.assertEqual(self.save_order('0').status_code,200)
        self.assertEqual(current_price_for(self.part).unit_price,0)
    def test_blank_price_does_not_modify_catalog(self):
        price=InventoryPriceRecord.objects.create(category=self.part,unit_price=9,is_current=True)
        self.assertEqual(self.save_order('').status_code,200)
        self.assertIsNone(PurchaseOrderLine.objects.get().unit_price)
        self.assertEqual(current_price_for(self.part).pk,price.pk)
