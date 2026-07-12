"""In-app notification helpers.

A thin layer over the ``Notification`` model. Event-producing views call
``notify(...)`` to drop a row for a recipient; the context processor +
base.html popup read ``unread_notifications_for(user)`` to surface them.

Recipient is always a Django ``User`` (not Worker) — department users have no
Worker row, and the popup is keyed on the logged-in request.user.
"""

from django.utils import timezone


def notify(recipient_user, verb, title, body='', link=''):
    """Create one notification for ``recipient_user``.

    Silently skips when ``recipient_user`` is None (e.g. a legacy Worker with no
    linked User, or a ghost submitter) — there's no one to pop up to.

    Returns the created Notification, or None if skipped.
    """
    if recipient_user is None:
        return None
    from .models import Notification
    return Notification.objects.create(
        recipient=recipient_user, verb=verb, title=title[:200],
        body=body or '', link=link or '',
    )


def unread_notifications_for(user, limit=50):
    """Unread notifications for ``user``, newest-first.

    Returns a list of plain dicts ready to serialize for the popup. The popup
    driver only needs id / title / body / link / time, so we project here to
    keep the context payload small (every authenticated page calls this).
    """
    if user is None or not user.is_authenticated:
        return []
    from .models import Notification
    qs = (Notification.objects
          .filter(recipient=user, read_at__isnull=True)
          .order_by('-created_at')[:limit])
    return [
        {
            'id': n.id,
            'verb': n.verb,
            'title': n.title,
            'body': n.body,
            'link': n.link,
            'time': n.created_at.strftime('%Y-%m-%d %H:%M') if n.created_at else '',
        }
        for n in qs
    ]


def mark_read(notification_id, user):
    """Mark a single notification read (我已知晓). Returns True if updated.

    Scoped to ``user`` so one user can't ack another's notification.
    """
    if user is None or not user.is_authenticated:
        return False
    from .models import Notification
    updated = Notification.objects.filter(
        pk=notification_id, recipient=user, read_at__isnull=True
    ).update(read_at=timezone.now())
    return updated > 0


def resubmit_already_notified(water_request):
    """Idempotency guard for the request-resubmit notification.

    Returns True if an unread ``request_resubmitted`` notification already
    exists for this request's approver since the request's last processed_at —
    i.e. the admin hasn't opened the resubmit popup yet, so don't spam a second
    one if the submitter re-edits.
    """
    from .models import Notification
    since = water_request.processed_at or water_request.updated_at
    approver_user = getattr(water_request.approver, 'user', None) if water_request.approver else None
    if approver_user is None:
        return False
    return Notification.objects.filter(
        recipient=approver_user, verb='request_resubmitted',
        read_at__isnull=True, created_at__gte=since,
    ).exists()


def pm_tasks_for_field_worker(user):
    """Today's pending PM tasks visible to a logged-in field worker.

    A task is visible to the whole crew (leader + members), so we match on
    GeneratedWorkOrder.crew against the worker's crews. Returns a list of
    plain dicts (serialized to pm_tasks_json for the notification popup).
    Lives here (rather than views.py) so the context processor can call it
    without importing the large views module.
    """
    from datetime import date as _date
    from .models import Worker, GeneratedWorkOrder
    try:
        worker = Worker.objects.get(user=user, active=True)
    except Worker.DoesNotExist:
        return []
    # Crews this worker belongs to (as member) or leads.
    crew_ids = set(worker.crews.values_list('id', flat=True)) | \
        set(worker.led_crews.values_list('id', flat=True))
    if not crew_ids:
        return []
    from django.utils import timezone as _tz
    today = _tz.localdate()
    tasks = (GeneratedWorkOrder.objects
             .filter(status__in=['dispatched', 'overdue'],
                     crew_id__in=crew_ids, scheduled_date__lte=today)
             .select_related('work_report', 'plan__job_plan')
             .prefetch_related('work_report__zones')
             .order_by('scheduled_date')[:20])
    result = []
    for gwo in tasks:
        report = gwo.work_report
        zones_qs = report.zones.all() if report else None
        zone_count = zones_qs.count() if zones_qs else 0
        first_codes = [z.code for z in zones_qs[:3]] if zones_qs else []
        result.append({
            'gwo_id': gwo.id,
            'report_id': report.id if report else None,
            'pm_number': gwo.plan.pm_number,
            'job_plan_name': gwo.plan.job_plan.name,
            'remark': report.remark if report else '',
            'scheduled_date': gwo.scheduled_date.strftime('%Y-%m-%d'),
            'zone_count': zone_count,
            'zone_preview': '、'.join(first_codes),
            'overdue': gwo.scheduled_date < today,
        })
    return result
