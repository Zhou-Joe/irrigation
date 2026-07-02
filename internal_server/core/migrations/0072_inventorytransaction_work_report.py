"""Generated for the 工单→材料出库 关联特性.

Adds a nullable FK on InventoryTransaction → WorkReport so an outbound
transaction created from inside a work order can be traced back to it.
SET_NULL: deleting the work order preserves the inventory ledger."""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0071_inventory_min_stock_main_material'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventorytransaction',
            name='work_report',
            field=models.ForeignKey(
                blank=True,
                help_text='工单内登记的材料消耗会生成此关联的出库单',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='material_consumptions',
                to='core.workreport',
                verbose_name='关联工单',
            ),
        ),
    ]
