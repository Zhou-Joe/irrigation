"""Add unit field to InventoryCategory."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0073_inventorycategory_node_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventorycategory',
            name='unit',
            field=models.CharField(
                blank=True, default='', help_text='库存计量单位，如 个/m/瓶',
                max_length=10, verbose_name='单位',
            ),
        ),
    ]
