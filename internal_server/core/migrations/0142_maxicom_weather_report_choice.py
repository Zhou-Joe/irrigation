from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0141_account_email')]
    operations = [migrations.AlterField(
        model_name='emailreportconfig', name='report_type',
        field=models.CharField(blank=True, choices=[
            ('work_reports', '维修工单记录'), ('difficult_workorders', '疑难问题跟进报表'),
            ('irrigation', '灌溉运行报表'), ('maxicom_weather', '灌溉气象日报'),
            ('projects', '项目管理'), ('inventory_catalog', '库存目录'),
            ('inventory_txn', '库存出入库流水'), ('purchase_orders', '采购订单'),
            ('zones', '区域/地块目录')], max_length=40, verbose_name='报表'))]
