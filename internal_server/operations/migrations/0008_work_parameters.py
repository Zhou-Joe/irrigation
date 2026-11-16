from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('operations', '0007_team_feedback')]
    operations = [
        migrations.AddField(model_name='location', name='parameters', field=models.JSONField(default=list, blank=True)),
        migrations.AddField(model_name='referencenode', name='parameters', field=models.JSONField(default=list, blank=True)),
        migrations.AddField(model_name='pestworkdata', name='parameters', field=models.JSONField(default=dict, blank=True)),
    ]
