from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0134_business_operations_guardrails')]

    operations = [
        migrations.CreateModel(name='MaxicomFlowSensor', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('mdb_index', models.IntegerField(unique=True)),
            ('name', models.CharField(max_length=255)),
            ('source_site_index', models.IntegerField(db_index=True)),
            ('source_site_number', models.IntegerField(blank=True, null=True)),
            ('source_site_name', models.CharField(blank=True, max_length=255)),
            ('controller_number', models.IntegerField(blank=True, null=True)),
            ('channel', models.IntegerField(blank=True, null=True)),
            ('is_active', models.BooleanField(default=True)),
            ('is_enabled', models.BooleanField(default=True)),
            ('coverage_start', models.CharField(blank=True, max_length=14)),
            ('coverage_end', models.CharField(blank=True, max_length=14)),
        ]),
        migrations.CreateModel(name='MaxicomSensorDaily', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('flow_day', models.CharField(db_index=True, max_length=8)),
            ('microliters', models.BigIntegerField()),
            ('sample_count', models.PositiveIntegerField()),
            ('samples', models.BinaryField(editable=False)),
            ('sensor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='daily', to='core.maxicomflowsensor')),
        ], options={'constraints': [models.UniqueConstraint(fields=('sensor', 'flow_day'), name='uniq_sensor_flow_day')]}),
    ]
