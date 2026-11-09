import django.db.models.deletion
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies=[('core','0140_email_delivery_profiles')]
    operations=[
        migrations.AddField(model_name='registrationrequest',name='email',field=models.EmailField(blank=True,max_length=254,verbose_name='邮箱')),
        migrations.AddField(model_name='registrationrequest',name='email_confirmation_required',field=models.BooleanField(default=False)),
        migrations.AddField(model_name='registrationrequest',name='email_verified_at',field=models.DateTimeField(blank=True,null=True)),
        migrations.CreateModel(name='AccountEmailSetting',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('updated_at',models.DateTimeField(auto_now=True)),
            ('registration_profile',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='+',to='core.emaildeliveryprofile')),
            ('password_reset_profile',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='+',to='core.emaildeliveryprofile')),
        ]),
    ]
