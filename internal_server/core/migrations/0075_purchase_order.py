"""Add PurchaseOrder model and link it from InventoryTransaction.

Backfills a PurchaseOrder row for each distinct non-empty order_no already
present on 入库-采购 transactions, and links those transactions to it, so the
new 采购订单 page isn't empty for existing data.
"""
from django.db import migrations, models


def backfill_purchase_orders(apps, schema_editor):
    """Create a PurchaseOrder per distinct historical order_no and link txns."""
    PurchaseOrder = apps.get_model('core', 'PurchaseOrder')
    InventoryTransaction = apps.get_model('core', 'InventoryTransaction')

    for order_no in (InventoryTransaction.objects
                     .filter(operation='入库', entry_subtype='采购')
                     .exclude(order_no='')
                     .values_list('order_no', flat=True)
                     .distinct()):
        po = PurchaseOrder.objects.filter(order_number=order_no).first()
        if po is None:
            po = PurchaseOrder.objects.create(order_number=order_no)
        # Link every matching transaction that isn't already linked.
        (InventoryTransaction.objects
         .filter(order_no=order_no, purchase_order__isnull=True)
         .update(purchase_order=po))


def clear_purchase_orders(apps, schema_editor):
    """Reverse: unlink transactions, then drop all backfilled orders.

    Only orders that carry no editable metadata (i.e. created by the backfill)
    are removed, so manually-edited POs survive a re-apply.
    """
    PurchaseOrder = apps.get_model('core', 'PurchaseOrder')
    InventoryTransaction = apps.get_model('core', 'InventoryTransaction')

    # Null out the FK everywhere first.
    InventoryTransaction.objects.filter(purchase_order__isnull=False).update(purchase_order=None)
    # Delete the bare backfilled POs (no po_number / project_name / amounts).
    (PurchaseOrder.objects
     .filter(po_number='', project_name='', project_code='',
             po_amount_untaxed__isnull=True)
     .delete())


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0074_inventorycategory_unit'),
    ]

    operations = [
        migrations.CreateModel(
            name='PurchaseOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order_number', models.CharField(
                    help_text='必填且唯一；入库-采购时据此匹配订单',
                    max_length=100, unique=True, verbose_name='灌溉订单编号')),
                ('po_number', models.CharField(blank=True, max_length=100, verbose_name='PO号')),
                ('po_amount_untaxed', models.DecimalField(
                    blank=True, decimal_places=2, max_digits=14, null=True, verbose_name='PO未税金额')),
                ('project_name', models.CharField(blank=True, max_length=200, verbose_name='项目名称')),
                ('project_code', models.CharField(blank=True, max_length=100, verbose_name='项目code')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': '采购订单',
                'verbose_name_plural': '采购订单',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddField(
            model_name='inventorytransaction',
            name='purchase_order',
            field=models.ForeignKey(
                blank=True,
                help_text='入库-采购且订单号命中采购订单时自动关联',
                null=True,
                on_delete=models.SET_NULL,
                related_name='transactions',
                to='core.purchaseorder',
                verbose_name='采购订单',
            ),
        ),
        migrations.RunPython(backfill_purchase_orders, clear_purchase_orders),
    ]
