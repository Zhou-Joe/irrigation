"""Add removed_project JSONField to WorkReport.

Records project associations removed via 移除关联 (keyed by project id) so the
order can be shown in the project's 已移除工单 list and restored later. The field
starts empty (default dict); existing reports have nothing removed yet.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0115_workreport_project_confirmed'),
    ]

    operations = [
        migrations.AddField(
            model_name='workreport',
            name='removed_project',
            field=models.JSONField(
                blank=True, default=dict, verbose_name='已移除项目关联'),
        ),
    ]
