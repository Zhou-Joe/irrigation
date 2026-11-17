"""Zone.save paths keep the neutral registry available without granting access."""
import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import Zone

logger=logging.getLogger(__name__)


@receiver(post_save,sender=Zone,dispatch_uid='operations.register_irrigation_zone')
def register_zone(sender,instance,raw=False,using='default',created=False,update_fields=None,**kwargs):
    if raw or not settings.MULTI_TEAM_ENABLED:return
    if not created and update_fields is not None and not {'name','code'}.intersection(update_fields):return
    identifier=instance.pk
    def register_current():
        try:
            current=Zone.objects.using(using).only('pk','name','code').filter(pk=identifier).first()
            if current is None:return
            from .registry import ensure_irrigation_location
            ensure_irrigation_location(current,using=using)
        except Exception:
            # A registry problem must not report a committed irrigation save as
            # failed. The explicit sync command can reconcile a missed reference.
            logger.exception('Irrigation location registration failed for zone %s',identifier)
    transaction.on_commit(register_current,using=using)
