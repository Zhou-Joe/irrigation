import uuid
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('core','0138_workreport_business_team')]
    operations = [
        migrations.AddField(model_name='emailsmtpsetting',name='delivery_method',field=models.CharField(choices=[('smtp','SMTP'),('workflow','Microsoft 365 Workflow')],default='smtp',max_length=16,verbose_name='发送方式')),
        migrations.AddField(model_name='emailsmtpsetting',name='workflow_url',field=models.TextField(blank=True,verbose_name='Workflow HTTP 链接')),
        migrations.AddField(model_name='emailsmtpsetting',name='download_base_url',field=models.URLField(blank=True,max_length=500,verbose_name='报表下载站点')),
        migrations.CreateModel(name='EmailReportFile',fields=[
            ('id',models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False,serialize=False)),
            ('filename',models.CharField(max_length=255)),
            ('token_hash',models.CharField(max_length=64)),
            ('created_at',models.DateTimeField(auto_now_add=True)),
            ('expires_at',models.DateTimeField(db_index=True)),
        ]),
    ]
