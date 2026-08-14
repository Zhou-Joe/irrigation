# Confirm-gated stock backfill: under the original confirm_status design, stock
# was deducted at submission for every actual txn (pending included). The new
# invariant is "only a confirmed actual txn has ever moved stock", so reverse
# the applied delta for any existing pending/removed actual txn. Production is
# unaffected: 0119 grandfathers every pre-deploy row to 'confirmed' before this
# runs, so the filter only matches post-deploy unconfirmed rows (dev/test data).

from django.db import migrations
from django.db.models import F


def reverse_unconfirmed_stock(apps, schema_editor):
    InventoryTransaction = apps.get_model('core', 'InventoryTransaction')
    InventoryTransactionLine = apps.get_model('core', 'InventoryTransactionLine')
    InventoryCategory = apps.get_model('core', 'InventoryCategory')
    qs = InventoryTransaction.objects.filter(
        consumption_mode='actual', confirm_status__in=['pending', 'removed'],
    )
    for txn in qs:
        direction = 1 if txn.operation == '入库' else -1
        for ln in InventoryTransactionLine.objects.filter(transaction=txn):
            InventoryCategory.objects.filter(pk=ln.category_id).update(
                current_stock=F('current_stock') - direction * ln.quantity,
            )


def reapply_unconfirmed_stock(apps, schema_editor):
    # Reverse of the above (restore old deduct-at-submit behavior) in case the
    # migration is rolled back.
    InventoryTransaction = apps.get_model('core', 'InventoryTransaction')
    InventoryTransactionLine = apps.get_model('core', 'InventoryTransactionLine')
    InventoryCategory = apps.get_model('core', 'InventoryCategory')
    qs = InventoryTransaction.objects.filter(
        consumption_mode='actual', confirm_status__in=['pending', 'removed'],
    )
    for txn in qs:
        direction = 1 if txn.operation == '入库' else -1
        for ln in InventoryTransactionLine.objects.filter(transaction=txn):
            InventoryCategory.objects.filter(pk=ln.category_id).update(
                current_stock=F('current_stock') + direction * ln.quantity,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0119_inventorytxn_confirm_status'),
    ]

    operations = [
        migrations.RunPython(reverse_unconfirmed_stock, reapply_unconfirmed_stock),
    ]
