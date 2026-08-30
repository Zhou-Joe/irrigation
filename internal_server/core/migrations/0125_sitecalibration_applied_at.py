from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0124_pipelineimportbatch'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitecalibration',
            name='applied_at',
            field=models.DateTimeField(blank=True, help_text='非空表示该标定已重算过库里全部坐标；重复应用会被拒绝（幂等保护）', null=True, verbose_name='应用到已存管道的时间'),
        ),
    ]
