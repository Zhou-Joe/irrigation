from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies=[('core','0136_difficult_workorders_report_choice')]
    operations=[migrations.AddField(model_name='purchaseorderline',name='unit_price',
        field=models.DecimalField('采购单价',max_digits=12,decimal_places=2,null=True,blank=True))]
