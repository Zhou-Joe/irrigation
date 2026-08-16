# Aligns Pipeline.pipeline_type / PipeValve.valve_type with the client's CAD
# standard taxonomy (6 line types, 6 valve/device block types). Schema-neutral
# on SQLite — choices only. MPTT drift ops from autodetected state are
# intentionally stripped (same as 0118/0119).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0120_confirm_gated_stock_backfill'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pipeline',
            name='pipeline_type',
            field=models.CharField(choices=[('irrigation', '灌溉主管'), ('flush', '冲洗主管'), ('toilet', '冲厕主管'), ('casing', '过路套管'), ('control', '控制线'), ('comm', '通讯线')], default='irrigation', help_text='线类型：灌溉主管/冲洗主管/冲厕主管/过路套管/控制线/通讯线', max_length=20),
        ),
        migrations.AlterField(
            model_name='pipevalve',
            name='valve_type',
            field=models.CharField(choices=[('solenoid', '电磁阀(Zone自控)'), ('gate', '闸阀(手动)'), ('angle', '角阀(手动)'), ('washdown', '冲洗阀(WD)'), ('qcv', '取水阀(QCV)'), ('pullbox', '拉线箱')], default='solenoid', max_length=20, verbose_name='阀门类型'),
        ),
    ]
