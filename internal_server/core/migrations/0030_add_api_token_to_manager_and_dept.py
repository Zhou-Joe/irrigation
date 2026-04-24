# Generate unique api_tokens for existing ManagerProfile and DepartmentUserProfile

from django.db import migrations, models
import uuid


def gen_unique_tokens(apps, schema_editor):
    for model_name in ['ManagerProfile', 'DepartmentUserProfile']:
        Model = apps.get_model('core', model_name)
        for obj in Model.objects.all():
            obj.api_token = uuid.uuid4()
            obj.save(update_fields=['api_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0029_auto_20260423_0614'),
    ]

    operations = [
        # Add field without unique constraint first
        migrations.AddField(
            model_name='departmentuserprofile',
            name='api_token',
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name='managerprofile',
            name='api_token',
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        # Populate unique values
        migrations.RunPython(gen_unique_tokens, migrations.RunPython.noop),
        # Now add unique constraint
        migrations.AlterField(
            model_name='departmentuserprofile',
            name='api_token',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name='managerprofile',
            name='api_token',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
