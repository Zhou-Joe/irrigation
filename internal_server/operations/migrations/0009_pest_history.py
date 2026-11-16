import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('operations', '0008_work_parameters')]

    operations = [
        migrations.CreateModel(name='PestHistoryImport', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('dataset', models.SlugField(max_length=64)),
            ('source_name', models.CharField(max_length=255)),
            ('source_sha256', models.CharField(max_length=64)),
            ('input_digest', models.CharField(max_length=64)),
            ('provenance', models.JSONField(default=dict)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('team', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='history_imports', to='operations.team')),
        ], options={'constraints': [models.UniqueConstraint(fields=('team', 'dataset', 'source_sha256'), name='ops_history_source_batch')]}),
        migrations.CreateModel(name='PestHistoryRecord', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('dataset', models.SlugField(max_length=64)),
            ('source_key', models.CharField(max_length=100)),
            ('content_digest', models.CharField(max_length=64)),
            ('source_sheet', models.CharField(max_length=128)),
            ('source_row', models.PositiveIntegerField()),
            ('observations', models.JSONField(default=dict)),
            ('original', models.JSONField(default=dict)),
            ('batch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='records', to='operations.pesthistoryimport')),
            ('report', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='history_source', to='core.workreport')),
            ('team', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='history_records', to='operations.team')),
        ], options={'constraints': [models.UniqueConstraint(fields=('team', 'dataset', 'source_key'), name='ops_history_external_record')]}),
    ]
