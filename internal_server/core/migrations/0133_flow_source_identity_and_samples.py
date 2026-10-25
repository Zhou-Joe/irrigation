from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0132_pm_rotation')]

    operations = [
        migrations.AlterField(
            model_name='maxicomflowzone', name='site',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='flow_zones', to='core.patch')),
        migrations.AddField(model_name='maxicomflowzone', name='source_site_index',
                            field=models.IntegerField(blank=True, null=True, db_index=True)),
        migrations.AddField(model_name='maxicomflowzone', name='source_site_number',
                            field=models.IntegerField(blank=True, null=True)),
        migrations.AddField(model_name='maxicomflowzone', name='source_site_name',
                            field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name='maxicomflowzone', name='source_counter',
                            field=models.IntegerField(blank=True, null=True)),
        migrations.AddField(model_name='maxicomflowzone', name='is_active',
                            field=models.BooleanField(default=True)),
        migrations.AddField(model_name='maxicomflowdaily', name='samples',
                            field=models.BinaryField(blank=True, editable=False, null=True)),
    ]
