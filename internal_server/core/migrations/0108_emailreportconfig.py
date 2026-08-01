"""Create EmailReportConfig for scheduled email reports.

Stores admin-configured (report × frequency × recipients) rows read by the
send_report_email management command (run daily via email_cron.sh). Each row
drives one scheduled Excel attachment email.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0107_inventorypricerecord'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailReportConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='配置名称')),
                ('report_type', models.CharField(
                    choices=[
                        ('work_reports', '维修工单记录'),
                        ('irrigation', '灌溉运行报表'),
                        ('projects', '项目管理'),
                        ('inventory_catalog', '库存目录'),
                        ('inventory_txn', '库存出入库流水'),
                        ('purchase_orders', '采购订单'),
                        ('zones', '区域/地块目录'),
                    ],
                    max_length=40, verbose_name='报表')),
                ('frequency', models.CharField(
                    choices=[('daily', '每日'), ('weekly', '每周'), ('monthly', '每月')],
                    default='daily', max_length=10, verbose_name='频率')),
                ('recipients', models.TextField(
                    help_text='多个邮箱用逗号或换行分隔', verbose_name='收件人邮箱')),
                ('is_active', models.BooleanField(default=True, verbose_name='启用')),
                ('last_sent_at', models.DateTimeField(blank=True, null=True, verbose_name='最后发送时间')),
                ('last_status', models.CharField(blank=True, max_length=200, verbose_name='最后状态')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='email_report_configs', to='auth.user', verbose_name='创建人')),
            ],
            options={
                'verbose_name': '邮件报表配置',
                'verbose_name_plural': '邮件报表配置',
                'ordering': ['frequency', 'name'],
            },
        ),
    ]
