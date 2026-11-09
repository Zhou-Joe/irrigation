import django.db.models.deletion
from django.db import migrations, models

FIELDS=('host','port','username','password','use_ssl','use_tls','from_email')

def preserve_settings(apps,schema_editor):
    alias=schema_editor.connection.alias
    Setting=apps.get_model('core','EmailSmtpSetting');Profile=apps.get_model('core','EmailDeliveryProfile');Report=apps.get_model('core','EmailReportConfig')
    setting,_=Setting.objects.using(alias).get_or_create(pk=1)
    values={name:getattr(setting,name) for name in FIELDS}
    smtp=Profile.objects.using(alias).create(name='原有 SMTP 配置',delivery_method='smtp',use_environment=not bool(setting.host),**values)
    selected=smtp
    if setting.workflow_url or setting.delivery_method=='workflow':
        workflow=Profile.objects.using(alias).create(name='原有 Microsoft 365 Workflow',delivery_method='workflow',workflow_url=setting.workflow_url,download_base_url=setting.download_base_url)
        if setting.delivery_method=='workflow':selected=workflow
    setting.default_profile_id=selected.pk;setting.save(using=alias,update_fields=['default_profile'])
    Report.objects.using(alias).filter(delivery_profile__isnull=True).update(delivery_profile_id=selected.pk)

class Migration(migrations.Migration):
    dependencies=[('core','0139_email_workflow')]
    operations=[
        migrations.CreateModel(name='EmailDeliveryProfile',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('name',models.CharField(max_length=100,unique=True,verbose_name='配置名称')),
            ('delivery_method',models.CharField(choices=[('smtp','SMTP'),('workflow','Microsoft 365 Workflow')],default='smtp',max_length=16,verbose_name='发送方式')),
            ('workflow_url',models.TextField(blank=True,verbose_name='Workflow HTTP 链接')),
            ('download_base_url',models.URLField(blank=True,max_length=500,verbose_name='报表下载站点')),
            ('host',models.CharField(blank=True,max_length=200,verbose_name='SMTP 服务器')),
            ('port',models.IntegerField(default=465,verbose_name='端口')),
            ('username',models.CharField(blank=True,max_length=200,verbose_name='账号')),
            ('password',models.TextField(blank=True,verbose_name='密码')),
            ('use_ssl',models.BooleanField(default=True,verbose_name='使用 SSL')),
            ('use_tls',models.BooleanField(default=False,verbose_name='使用 TLS')),
            ('from_email',models.CharField(blank=True,max_length=200,verbose_name='发件人地址')),
            ('use_environment',models.BooleanField(default=False,verbose_name='沿用服务器邮件设置')),
            ('updated_at',models.DateTimeField(auto_now=True)),
        ]),
        migrations.AddField(model_name='emailsmtpsetting',name='default_profile',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='+',to='core.emaildeliveryprofile')),
        migrations.AddField(model_name='emailreportconfig',name='delivery_profile',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='report_configs',to='core.emaildeliveryprofile',verbose_name='发送配置')),
        migrations.RunPython(preserve_settings,migrations.RunPython.noop),
    ]
