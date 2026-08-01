"""Create EmailSmtpSetting (singleton) for UI-configured SMTP.

Lets admins configure the mail server from the 用户管理 → 邮件报表 tab instead
of editing server env vars. core.smtp_utils reads it with an env-var fallback.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0108_emailreportconfig'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailSmtpSetting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('host', models.CharField(blank=True, help_text='如 smtp.qq.com', max_length=200, verbose_name='SMTP 服务器')),
                ('port', models.IntegerField(default=465, verbose_name='端口')),
                ('username', models.CharField(blank=True, max_length=200, verbose_name='账号')),
                ('password', models.TextField(blank=True, verbose_name='密码')),
                ('use_ssl', models.BooleanField(default=True, verbose_name='使用 SSL')),
                ('use_tls', models.BooleanField(default=False, verbose_name='使用 TLS')),
                ('from_email', models.CharField(blank=True, help_text='留空则用账号邮箱', max_length=200, verbose_name='发件人地址')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'SMTP 配置',
                'verbose_name_plural': 'SMTP 配置',
            },
        ),
    ]
