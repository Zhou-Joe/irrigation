from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0131_pm_deadlines_and_dispatch_runs')]

    operations = [
        migrations.AddField(
            model_name='maintenanceplan', name='rotation_anchor',
            field=models.DateField(null=True, blank=True, editable=False),
        ),
        migrations.AddField(
            model_name='maintenanceplan', name='rotation_slot',
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
        migrations.AddField(
            model_name='maintenanceplan', name='rotation_size',
            field=models.PositiveIntegerField(default=1, editable=False),
        ),
        migrations.AddField(
            model_name='maintenanceplan', name='rotation_cycle',
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
    ]
