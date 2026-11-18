from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0146_announcement_business_team_crew_business_team_and_more')]
    operations = [
        migrations.AddField(model_name='purchaseorder', name='purchase_date',
                            field=models.DateField(blank=True, null=True, verbose_name='采购日期')),
    ]
