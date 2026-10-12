from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.db import migrations, models


def snapshot_deadlines(apps, schema_editor):
    Order = apps.get_model('core', 'GeneratedWorkOrder')
    orders = Order.objects.using(schema_editor.connection.alias).select_related('plan')
    batch = []
    for order in orders.iterator():
        plan = order.plan
        if plan.frequency_value < 1:
            continue
        if plan.frequency_unit == 'months':
            order.deadline = order.scheduled_date + relativedelta(months=plan.frequency_value)
        elif plan.frequency_unit in ('days', 'weeks'):
            order.deadline = order.scheduled_date + timedelta(
                days=plan.frequency_value * (7 if plan.frequency_unit == 'weeks' else 1))
        else:
            continue
        batch.append(order)
        if len(batch) >= 500:
            Order.objects.using(schema_editor.connection.alias).bulk_update(batch, ['deadline'])
            batch = []
    if batch:
        Order.objects.using(schema_editor.connection.alias).bulk_update(batch, ['deadline'])


class Migration(migrations.Migration):
    dependencies = [('core', '0130_dxf_independent_check_points')]
    operations = [
        migrations.AddField(
            model_name='generatedworkorder', name='deadline',
            field=models.DateField('完成截止日期', null=True, blank=True, db_index=True,
                help_text='派发时保存，修改计划频率不会改变旧工单截止日期。'),
        ),
        migrations.RunPython(snapshot_deadlines, migrations.RunPython.noop),
        migrations.CreateModel(
            name='PMDispatchRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('run_date', models.DateField('调度日期')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('summary', models.JSONField(default=dict)),
                ('details', models.JSONField(default=list)),
            ],
            options={'ordering': ['-created_at', '-id']},
        ),
    ]
