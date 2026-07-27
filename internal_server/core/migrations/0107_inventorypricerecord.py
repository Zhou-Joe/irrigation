# Generated for inventory part price-history feature.

import datetime
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0106_zone_heatmap_excluded'),
    ]

    operations = [
        migrations.CreateModel(
            name='InventoryPriceRecord',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(default=datetime.date.today, verbose_name='采购日期')),
                ('supplier', models.CharField(blank=True, max_length=200, verbose_name='供应商')),
                ('unit_price', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='单价')),
                ('unit', models.CharField(blank=True, help_text='留空则继承部件的 unit', max_length=10, verbose_name='单位')),
                ('is_current', models.BooleanField(default=False, help_text='勾选后此记录作为该部件的当前价格；同部件仅一条有效', verbose_name='设为当前价格')),
                ('note', models.CharField(blank=True, max_length=200, verbose_name='备注')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='price_records', to='core.inventorycategory', verbose_name='部件')),
            ],
            options={
                'verbose_name': '采购价格记录',
                'verbose_name_plural': '采购价格记录',
                'ordering': ['-date', '-id'],
            },
        ),
    ]
