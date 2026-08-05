"""Shared service for Excel report generation and email dispatch.

Single source of truth for the "report_type → builder" mapping and the
frequency/custom-range date-window logic. Three callers share it:

  * the ``send_report_email`` management command (scheduled cron dispatch),
  * the ``report_export_api`` token-auth endpoint (external platforms / AI),
  * the ``send_report_email`` LangChain tool (in-app AI assistant).

Previously the resolution table and date helpers lived inside the management
command as private helpers, which forced the test-send view to instantiate the
command and call its private methods. Moving them here keeps each caller thin.

``build_report(report_type, start, end, user)`` is the key entry point for the
API path: it builds from *explicit* dates (passed by the request) rather than
deriving them from a frequency, so external callers can ask for any window.
"""

from datetime import date, timedelta
from io import BytesIO

from django.utils import timezone

XLSX_CT = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

# All supported report types (mirrors EmailReportConfig.REPORT_CHOICES keys).
REPORT_TYPES = [
    'work_reports', 'irrigation', 'projects', 'inventory_catalog',
    'inventory_txn', 'purchase_orders', 'zones',
]

# report_type → human label, kept in sync with excel_exports builders and the
# command's _resolve_builder table. Used for email subjects and API error text.
REPORT_TYPE_LABELS = {
    'work_reports': '维修工单记录',
    'irrigation': '灌溉运行报表',
    'projects': '项目管理',
    'inventory_catalog': '库存目录',
    'inventory_txn': '库存出入库流水',
    'purchase_orders': '采购订单',
    'zones': '区域/地块目录',
}

# Report types that ignore dates entirely (no date column to filter on, OR the
# date isn't a daily-log semantic — projects are a long-lived portfolio filtered
# by start_date, not a daily record, so a "last 30 days" window doesn't apply).
# This keeps the API path consistent with the cron path (Command._build_report),
# which intentionally passes no date params to these builders.
DATELESS_REPORT_TYPES = {'zones', 'inventory_catalog', 'purchase_orders', 'projects'}


def resolve_builder(report_type):
    """Return ``(build_fn, label)`` for a report_type, or ``(None, None)``.

    The import is lazy so this module stays import-light and a broken
    ``excel_exports`` never blocks Django from booting.
    """
    from core import excel_exports as ex
    table = {
        'work_reports': (ex.build_work_reports_excel, '维修工单记录'),
        'irrigation': (ex.build_irrigation_report_excel, '灌溉运行报表'),
        'projects': (ex.build_project_export_excel, '项目管理'),
        'inventory_catalog': (ex.build_inventory_catalog_excel, '库存目录'),
        'inventory_txn': (ex.build_inventory_transactions_excel, '库存出入库流水'),
        'purchase_orders': (ex.build_purchase_order_excel, '采购订单'),
        'zones': (ex.build_zone_export_excel, '区域/地块目录'),
    }
    return table.get(report_type, (None, None))


def parse_iso_date(s):
    """Parse a ``YYYY-MM-DD`` string into a ``date``; return ``None`` if empty/invalid."""
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def date_window(frequency, today=None, data_range_days=None):
    """Resolve the data date window for a frequency (or a custom range).

    Returns ``(start, end)`` as date objects. The caller is responsible for
    coercing these into whatever form its builder needs (compact timestamp
    strings for irrigation, ISO strings for inventory_txn, etc.).

    If ``data_range_days`` is set it overrides the frequency default: the window
    is send-day minus N days → yesterday (send-day itself has no data yet).
    e.g. N=7 → today-7 .. today-1.
    """
    today = today or timezone.localdate()
    # Custom range wins over the frequency default.
    if data_range_days:
        end = today - timedelta(days=1)
        start = today - timedelta(days=data_range_days)
        return start, end
    if frequency == 'daily':
        d = today - timedelta(days=1)        # yesterday
        return d, d
    if frequency == 'weekly':
        this_monday = today - timedelta(days=today.weekday())
        last_monday = this_monday - timedelta(days=7)
        last_sunday = last_monday + timedelta(days=6)
        return last_monday, last_sunday
    if frequency == 'monthly':
        first_this_month = today.replace(day=1)
        last_day_prev = first_this_month - timedelta(days=1)
        first_prev = last_day_prev.replace(day=1)
        return first_prev, last_day_prev
    return today, today


def period_label(frequency, today, data_range_days=None):
    """Human-readable window label for an email subject (e.g. ``2026年7月``)."""
    start, end = date_window(frequency, today, data_range_days)
    if frequency == 'monthly':
        return f'{start.year}年{start.month}月'
    if start == end:
        return start.strftime('%Y-%m-%d')
    return f'{start.strftime("%Y-%m-%d")} 至 {end.strftime("%Y-%m-%d")}'


def build_report(report_type, start=None, end=None, user=None, ccu_ids=None):
    """Build an Excel report for an *explicit* date window.

    Unlike the command's frequency-driven path, this takes ``start``/``end``
    dates directly (as ``date`` objects) so external callers (API, AI tool) can
    request any window. ``start``/``end`` default to the last 30 days when both
    are omitted, matching the dashboard's default export range.

    Each report type gets the parameter shape its builder expects:

      * ``irrigation``      → compact ``YYYYMMDDHHMM`` strings (00:00–23:59);
                              ``ccu_ids`` optionally restricts the CCU subset
      * ``work_reports``    → ``(start, end, user)``; ``user`` defaults to the
                              first superuser so the export has full visibility
      * ``inventory_txn``   → ISO date strings
      * ``projects``        → ``date_from``/``date_to`` keyword args
      * ``zones`` / ``inventory_catalog`` / ``purchase_orders`` → no date args

    Returns ``(filename, BytesIO)``. Raises ``ValueError`` for an unknown
    report_type (the caller decides how to surface that).
    """
    build_fn, label = resolve_builder(report_type)
    if build_fn is None:
        raise ValueError(f'未知报表类型 {report_type}')

    # Dateless reports ignore the window entirely.
    if report_type in DATELESS_REPORT_TYPES:
        return build_fn()

    # Default to last 30 days when no window supplied (matches dashboard).
    if start is None and end is None:
        end = timezone.localdate()
        start = end - timedelta(days=30)
    elif start is None:
        start = end - timedelta(days=30)
    elif end is None:
        end = start

    if report_type == 'irrigation':
        df = start.strftime('%Y%m%d') + '0000'
        dt = end.strftime('%Y%m%d') + '2359'
        return build_fn(df, dt, ccu_ids=ccu_ids)
    if report_type == 'work_reports':
        if user is None:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            # No per-user scope → export as a superuser (full visibility),
            # matching the scheduled-dispatch path and the admin download.
            user = (User.objects.filter(is_superuser=True).first()
                    or User.objects.first())
        return build_fn(start, end, user)
    if report_type == 'inventory_txn':
        return build_fn(start.isoformat(), end.isoformat())
    # Defensive: any other report_type that resolves a builder but isn't
    # listed above falls through to dateless behaviour (projects is now in
    # DATELESS_REPORT_TYPES above, so it's handled there, not here).
    return build_fn()


def build_all_attachments(report_types, frequency, today, report_windows=None,
                          ccu_ids=None):
    """Build every selected report as an Excel attachment for ONE email.

    Returns a list of ``(filename, BytesIO, label)`` tuples — one per report
    type — that the caller loops over to ``msg.attach(...)``.

    ``report_windows`` is a ``{report_type: {days_start,[hour_start],days_end,
    [hour_end]}}`` map — each date-windowed report's own start/end, expressed
    RELATIVE to the send instant:
      * irrigation       → hour-precise: [send_now - days_start days, hour_start:00]
                                         to [send_now - days_end days, hour_end:59]
                           (compact YYYYMMDDHHMM strings)
      * work_reports     → day-granular (its data has no hour): date objects
                           [today - days_start, today - days_end]
      * inventory_txn    → day-granular ISO date strings
      * dateless types   → no window (zones/inventory_catalog/purchase_orders/projects)

    A failure building one report does NOT abort the others: it's skipped and
    noted in the returned list as a sentinel (label prefixed with 'FAILED:').
    The caller decides whether to send with partial attachments or fail loud.
    """
    from core.management.commands.send_report_email import Command
    report_windows = report_windows or {}
    now = timezone.now()
    cmd = Command()   # stateless helper container for _build_report
    out = []
    for rt in report_types:
        build_fn, label = resolve_builder(rt)
        if build_fn is None:
            out.append((None, None, f'FAILED:{rt}:未知报表类型'))
            continue
        try:
            win = report_windows.get(rt) or {}
            if rt == 'irrigation':
                # Hour-precise window relative to the send instant.
                ds = int(win.get('days_start', 1)); hs = int(win.get('hour_start', 0))
                de = int(win.get('days_end', 0)); he = int(win.get('hour_end', 23))
                start_dt = (now - timedelta(days=ds)).replace(hour=hs, minute=0, second=0, microsecond=0)
                end_dt = (now - timedelta(days=de)).replace(hour=he, minute=59, second=0, microsecond=0)
                df = start_dt.strftime('%Y%m%d%H%M')
                dt = end_dt.strftime('%Y%m%d%H%M')
                fname, buf = build_fn(df, dt, ccu_ids=ccu_ids)
            elif rt == 'work_reports':
                # Day-granular: WorkReport.date is a DateField, hours are ignored.
                ds = int(win.get('days_start', 1)); de = int(win.get('days_end', 0))
                start_d = today - timedelta(days=ds)
                end_d = today - timedelta(days=de)
                fname, buf = build_fn(start_d, end_d, _dispatch_user())
            elif rt == 'inventory_txn':
                ds = int(win.get('days_start', 7)); de = int(win.get('days_end', 1))
                start_d = today - timedelta(days=ds)
                end_d = today - timedelta(days=de)
                fname, buf = build_fn(start_d.isoformat(), end_d.isoformat())
            else:
                # Dateless types (zones/inventory_catalog/purchase_orders/projects).
                fname, buf = build_fn()
            out.append((fname, buf, label))
        except Exception as e:
            out.append((None, None, f'FAILED:{rt}:{e}'))
    return out


def _dispatch_user():
    """Resolve the user for the work_reports builder (full visibility)."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return (User.objects.filter(is_superuser=True).first() or User.objects.first())


def render_subject_body(cfg, report_labels, period):
    """Resolve the email subject + body for a config, honoring custom text.

    ``cfg.email_subject`` / ``cfg.email_body`` (if non-empty) are used as
    templates with ``{name}``/``{types}``/``{period}`` placeholders filled;
    otherwise the built-in default text is used. ``report_labels`` is the
    joined display string of the selected report types (e.g. "维修工单记录、灌溉").
    """
    types_str = '、'.join(report_labels) if report_labels else '报表'
    name = getattr(cfg, 'name', '') or ''
    subj_tmpl = (cfg.email_subject or '').strip()
    body_tmpl = (cfg.email_body or '').strip()
    if subj_tmpl:
        subject = subj_tmpl.format(name=name, types=types_str, period=period)
    else:
        subject = f'【{types_str}】{period} 报表 — {name}'
    if body_tmpl:
        body = body_tmpl.format(name=name, types=types_str, period=period)
    else:
        body = (f'您好，\n\n这是系统自动发送的定时报表。\n'
                f'报表类型：{types_str}\n频率：{cfg.get_frequency_display()}\n'
                f'数据范围：{period}\n\n请见附件。')
    return subject, body
