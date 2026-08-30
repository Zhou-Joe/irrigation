from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0122_maxicomruntime_station_ts_index'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiteCalibration',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('points', models.JSONField(help_text='[{dxf_x, dxf_y(原始DXF), lat, lng}]，至少 2 点、建议 3 点')),
                ('note', models.CharField(blank=True, max_length=200, verbose_name='备注')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, related_name='dxf_calibrations', to=settings.AUTH_USER_MODEL, verbose_name='操作人')),
            ],
            options={
                'verbose_name': 'DXF站点标定',
                'verbose_name_plural': 'DXF站点标定',
                'ordering': ['-id'],
            },
        ),
    ]
