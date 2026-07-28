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
             .select_related('plan__job_plan', 'worker')
             .prefetch_related('zones')
             .order_by('scheduled_date')[:20])
    result = []
    for gwo in tasks:
        # Dispatch stores zones/remark on the GWO itself (no WorkReport shell),
        # so read them directly — work_report is deprecated and always None now.
        zones_qs = list(gwo.zones.all())
        first_codes = [z.code for z in zones_qs[:3]]
        result.append({
            'gwo_id': gwo.id,
            'pm_number': gwo.plan.pm_number,
            'job_plan_name': gwo.plan.job_plan.name if gwo.plan.job_plan_id else '',
            'remark': gwo.remark or '',
            'scheduled_date': gwo.scheduled_date.strftime('%Y-%m-%d'),
            'zone_count': len(zones_qs),
            'zone_preview': '、'.join(first_codes),
            'overdue': gwo.scheduled_date < today,
        })
    return result


def notify_followup_crew(parent, child, author_worker, action, remark):
    """Notify all managers + field workers that a 疑难/待修 follow-up was filed.

    Recipients = every active manager (ManagerProfile.user) ∪ every active
    field worker (Worker.user with a linked account), EXCLUDING the follow-up
    author so they don't get a notification for their own action.

    The notification carries the story (parent ticket) reference and a short
    summary so the crew knows "this ticket is being followed up on" without
    opening the page. ``link`` deep-links to the parent's detail page.

    Returns the count of notifications created (0 if no recipients / author
    is the only eligible user).
    """
    from core.models import ManagerProfile, Worker
    from django.contrib.auth import get_user_model
    User = get_user_model()

    # Resolve the author's User so we can exclude them.
    author_user = getattr(author_worker, 'user', None) if author_worker else None

    # Managers: every active ManagerProfile with a linked User.
    manager_users = list(
        ManagerProfile.objects.filter(active=True, user__isnull=False)
        .values_list('user_id', flat=True))
    # Field workers: every active Worker with a linked User.
    worker_users = list(
        Worker.objects.filter(active=True, user__isnull=False)
        .values_list('user_id', flat=True))

    recipient_ids = set(manager_users) | set(worker_users)
    if author_user is not None:
        recipient_ids.discard(author_user.id)
    if not recipient_ids:
        return 0

    # Build the human-readable summary. Truncate the remark the way the story
    # timeline does (400 chars) so the popup stays readable.
    ticket = parent.display_number
    author_name = (author_worker.full_name if author_worker else '未知')
    action_label = '已修复（待经理确认）' if action == 'fixed' else '继续跟进'
    short_remark = (remark or '').strip()
    if len(short_remark) > 120:
        short_remark = short_remark[:117] + '…'

    title = f'{author_name} 跟进了工单 {ticket}'
    body_parts = [f'状态：{action_label}']
    if short_remark:
        body_parts.append(f'跟进内容：{short_remark}')
    body = '\n'.join(body_parts)
    link = f'/work-reports/{parent.id}/'

    created = 0
    recipients = User.objects.filter(id__in=recipient_ids)
    for u in recipients:
        if notify(u, 'followup', title, body, link):
            created += 1
    return created
