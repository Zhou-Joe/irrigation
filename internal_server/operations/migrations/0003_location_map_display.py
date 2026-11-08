from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('operations', '0002_pestworkdata')]

    operations = [
        migrations.AddField(
            model_name='location',
            name='map_display',
            field=models.CharField(choices=[('auto', '自动（边界优先，无边界用图钉）'),
                                             ('pin', '图钉标注（无需精确边界）')],
                                   default='auto', max_length=12),
        ),
    ]
