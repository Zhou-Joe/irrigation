from django.conf import settings
from django.db import migrations, models


def register_existing_zones(apps,schema_editor):
    if not getattr(settings,'MULTI_TEAM_ENABLED',False):return
    alias=schema_editor.connection.alias
    Team=apps.get_model('operations','Team')
    Location=apps.get_model('operations','Location')
    Zone=apps.get_model('core','Zone')
    teams=Team.objects.using(alias).filter(business__code='irrigation',legacy_irrigation_access=True,
        active=True,business__active=True)
    team=teams.filter(code='irrigation').first() or teams.order_by('pk').first()
    if team is None:return
    linked=set(Location.objects.using(alias).exclude(legacy_zone_id=None).values_list('legacy_zone_id',flat=True))
    codes=set(Location.objects.using(alias).filter(owner_team_id=team.pk).exclude(code='').values_list('code',flat=True))
    locations=[]
    for zone in Zone.objects.using(alias).only('pk','name','code').order_by('pk').iterator():
        if zone.pk in linked:continue
        code=str(zone.code or '')[:100]
        if code in codes:code=''
        if code:codes.add(code)
        locations.append(Location(owner_team_id=team.pk,legacy_zone_id=zone.pk,registry_generated=True,
            name=str(zone.name or zone.code or f'区域 {zone.pk}')[:150],code=code))
    if locations:Location.objects.using(alias).bulk_create(locations,batch_size=500)


class Migration(migrations.Migration):
    dependencies=[('operations','0004_pest_management')]
    operations=[
        migrations.AddField(model_name='location',name='registry_generated',field=models.BooleanField(default=False,db_default=False)),
        migrations.RunPython(register_existing_zones,migrations.RunPython.noop),
    ]
