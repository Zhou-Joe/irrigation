from django.db import migrations


def create_workspace(apps, schema_editor):
    business_model = apps.get_model('operations', 'BusinessArea')
    team_model = apps.get_model('operations', 'Team')
    alias = schema_editor.connection.alias
    business, _ = business_model.objects.using(alias).get_or_create(
        code='landscaping', defaults={'name': '绿化'})
    team_model.objects.using(alias).get_or_create(
        code='landscaping', defaults={'business': business, 'name': '绿化团队'})


class Migration(migrations.Migration):
    dependencies = [('operations', '0009_pest_history')]
    operations = [migrations.RunPython(create_workspace, migrations.RunPython.noop)]
