from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0123_sitecalibration'),
    ]

    operations = [
        migrations.CreateModel(
            name='PipelineImportBatch',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='批次名/DXF文件名')),
                ('imported_at', models.DateTimeField(auto_now_add=True, verbose_name='导入时间')),
                ('note', models.CharField(blank=True, max_length=200, verbose_name='备注')),
                ('imported_by', models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pipeline_import_batches', to=settings.AUTH_USER_MODEL, verbose_name='操作人')),
            ],
            options={
                'verbose_name': '水管导入批次',
                'verbose_name_plural': '水管导入批次',
                'ordering': ['-id'],
            },
        ),
        migrations.AddField(
            model_name='pipeline',
            name='import_batch',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pipelines', to='core.pipelineimportbatch', verbose_name='导入批次'),
        ),
    ]
