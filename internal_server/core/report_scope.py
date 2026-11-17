from django.db import models
from django.db.models import Q


class IrrigationReportManager(models.Manager):
    """Legacy irrigation queries must never aggregate another business's work."""
    def get_queryset(self):
        return super().get_queryset().filter(
            Q(business_team__isnull=True) | Q(business_team__business__code='irrigation'))
