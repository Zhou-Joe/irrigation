"""Send scheduled Excel-report emails based on EmailReportConfig rows.

Run daily via the email_cron.sh wrapper (mirrors pm_dispatch_cron.sh). Each
active EmailReportConfig is evaluated: if its frequency matches today
(daily = every day, weekly = the configured weekday, monthly = the configured
month day), the matching report's Excel is built via core.excel_exports,
attached to an EmailMessage, and sent over SMTP to the configured recipients.

Frequency → date window mapping:
  daily   → yesterday's data
  weekly  → last week (Mon–Sun)
  monthly → last month (1st–last day)

Robustness: each config is independent — a failure building/sending one report
is caught and recorded on that config's last_status without aborting the others.
When SMTP is unconfigured (EMAIL_HOST empty) the command logs a skip and exits,
so dev / unset environments never crash.

Usage:
    python manage.py send_report_email            # send today's due reports
    python manage.py send_report_email --dry-run  # print what WOULD be sent, no email
    python manage.py send_report_email --config-id 3   # force one config (ignores frequency)
"""

from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.utils import timezone

from core.models import EmailReportConfig
# Shared resolution + date-window logic lives in the service layer so the
# command, the token-auth API, the AI tool, and the test-send view all use one
# source of truth. Backward-compat aliases are re-exported at the bottom of
# this module for callers that imported the underscore-prefixed names directly.
from core.report_export import (
    resolve_builder as _resolve_builder,
    date_window as _date_window,
    period_label as _period_label,
    build_all_attachments as _build_all_attachments,
    render_subject_body as _render_subject_body,
    REPORT_TYPE_LABELS as _REPORT_TYPE_LABELS,
    XLSX_CT,
)


def _is_due_now(cfg, now=None):
    """Should this config fire at this moment?

    Two conditions must both hold:
      1. Day-of-cycle matches the frequency (daily=any day, weekly=cfg.weekday,
         monthly=cfg.month_day) — same as the old _is_due_today.
      2. The current hour equals cfg.send_hour (null/blank → 7, preserving the
         pre-hourly-cron default). This only matters once the production cron
         runs hourly (see email_cron.sh); a daily 07:00 cron still fires every
         config whose send_hour is null/7, exactly as before.

    All hour/weekday/day comparisons use Beijing time (TIME_ZONE=Asia/Shanghai).
    timezone.now() returns a UTC-aware datetime; convert with localtime() before
    reading .hour/.weekday()/.day so a config set to 23:00 fires at 23:00 Beijing
    (not 23:00 UTC = 07:00 Beijing).
    """
    now = now or timezone.now()
    now = timezone.localtime(now)   # → Asia/Shanghai for correct hour/day reads
    # --- day-of-cycle gate ---
    if cfg.frequency == 'daily':
        day_ok = True
    elif cfg.frequency == 'weekly':
        wd = cfg.weekday if cfg.weekday is not None else 0   # default Monday
        day_ok = now.weekday() == wd
    elif cfg.frequency == 'monthly':
        md = cfg.month_day if cfg.month_day is not None else 1  # default 1st
        day_ok = now.day == md
    else:
        day_ok = False
    if not day_ok:
        return False
    # --- hour gate ---
    hour = cfg.send_hour if cfg.send_hour is not None else 7
    return now.hour == hour


def _is_due_today(cfg, today=None):
    """Back-compat shim: the day-of-cycle check only (ignores send_hour).

    Kept so any caller/importer that still references _is_due_today keeps
    working. The dispatch loop uses _is_due_now (hour-aware) instead.
    """
    now = timezone.now() if today is None else None
    base = now or timezone.now()
    if today is not None:
        # Caller passed a date; honor the day-of-cycle against that date but
        # still ignore the hour (legacy semantics).
        if cfg.frequency == 'daily':
            return True
        if cfg.frequency == 'weekly':
            wd = cfg.weekday if cfg.weekday is not None else 0
            return today.weekday() == wd
        if cfg.frequency == 'monthly':
            md = cfg.month_day if cfg.month_day is not None else 1
            return today.day == md
        return False
    return _is_due_now(cfg, base)


class Command(BaseCommand):
    help = 'Send scheduled Excel-report emails (driven by EmailReportConfig).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print what would be sent without actually emailing.')
        parser.add_argument(
            '--config-id', type=int, default=None,
            help='Force-run a single config by id (ignores frequency/is_active).')

    def handle(self, *args, **options):
        dry = options['dry_run']
        force_id = options['config_id']

        # SMTP gate: needs either a DB-configured EmailSmtpSetting or an env
        # EMAIL_HOST. Without SMTP there's nothing to actually send.
        from core.smtp_utils import is_smtp_configured
        if not dry and not is_smtp_configured():
            self.stdout.write(self.style.WARNING(
                'SMTP 未配置 — 请在「用户管理 → 邮件报表」tab 配置 SMTP，'
                '或在环境变量设置 EMAIL_HOST。'))
            return

        qs = EmailReportConfig.objects.all()
        if force_id:
            qs = qs.filter(pk=force_id)
        else:
            qs = qs.filter(is_active=True)

        # Use Beijing time for the dispatch instant: _is_due_now's hour/weekday/
        # day gate and the per-report "前N天" windows are all in Asia/Shanghai.
        # timezone.now() is UTC-aware; localtime() converts before .date()/.hour.
        now = timezone.localtime(timezone.now())
        today = now.date()
        configs = list(qs.order_by('frequency', 'name'))
        self.stdout.write(f'Email report dispatch: {len(configs)} config(s), '
                          f'now={now.strftime("%Y-%m-%d %H:%M")} (Beijing), dry_run={dry}')

        sent, skipped, failed = 0, 0, 0
        for cfg in configs:
            # Day-of-cycle + send-hour gate (skipped when forcing one config by id).
            if not force_id and not _is_due_now(cfg, now):
                hour = cfg.send_hour if cfg.send_hour is not None else 7
                self.stdout.write(
                    f'  [skip] {cfg.name} ({cfg.frequency}, hour={hour}) — not due now')
                skipped += 1
                continue

            recipients = cfg.recipient_list
            if not recipients:
                msg = '无收件人邮箱'
                self._record(cfg, 'failed: ' + msg, dry)
                self.stdout.write(self.style.ERROR(f'  [fail] {cfg.name}: {msg}'))
                failed += 1
                continue

            # Resolve the effective report-type list (multi-select, with
            # legacy single-report_type fallback). Each becomes one attachment.
            report_types = cfg.effective_report_types()
            if not report_types:
                msg = '未选择报表类型'
                self._record(cfg, 'failed: ' + msg, dry)
                self.stdout.write(self.style.ERROR(f'  [fail] {cfg.name}: {msg}'))
                failed += 1
                continue

            # Build every selected report (one attachment each). Each date-
            # windowed report carries its OWN start/end in report_windows
            # (relative to the send instant); ccu_ids scopes irrigation.
            attachments = _build_all_attachments(
                report_types, cfg.frequency, today,
                report_windows=cfg.report_windows or None,
                ccu_ids=cfg.ccu_ids or None,
            )
            built = [(f, b, lbl) for (f, b, lbl) in attachments
                     if f is not None and not lbl.startswith('FAILED:')]
            failures = [lbl for (_, _, lbl) in attachments if lbl.startswith('FAILED:')]
            if not built:
                msg = '生成报表失败: ' + '; '.join(failures)
                self._record(cfg, 'failed: ' + msg[:200], dry)
                self.stdout.write(self.style.ERROR(f'  [fail] {cfg.name}: {msg}'))
                failed += 1
                continue

            period = self._period_label(cfg.frequency, today, cfg.data_range_days)
            report_labels = [lbl for (_, _, lbl) in built]
            subject, body = _render_subject_body(cfg, report_labels, period)

            if dry:
                self.stdout.write(self.style.WARNING(
                    f'  [dry] {cfg.name} → {recipients} | {len(built)} attachment(s): '
                    f'{[f for (f, _, _) in built]} | subject="{subject}"'))
                if failures:
                    self.stdout.write(self.style.ERROR(
                        f'        partial failures: {failures}'))
                continue

            try:
                from core.smtp_utils import get_email_connection, resolve_from_email
                msg = EmailMessage(
                    subject=subject, body=body,
                    from_email=resolve_from_email(), to=recipients,
                    connection=get_email_connection(),
                )
                for fname, buf, _ in built:
                    msg.attach(fname, buf.getvalue(), XLSX_CT)
                msg.send(fail_silently=False)
                self._record(cfg, 'success', dry)
                self.stdout.write(self.style.SUCCESS(
                    f'  [ok] {cfg.name} → {len(recipients)} recipient(s) '
                    f'({len(built)} attachment(s))'))
                sent += 1
            except Exception as e:
                self._record(cfg, f'failed: 发送失败 {e}', dry)
                self.stdout.write(self.style.ERROR(f'  [fail] {cfg.name}: 发送失败 {e}'))
                failed += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done. sent={sent} skipped={skipped} failed={failed}'))

    # ── helpers ──

    def _build_report(self, report_type, build_fn, frequency, today, data_range_days=None):
        """Call the right builder with frequency-appropriate params.

        Dispatches on ``report_type`` (the validated EmailReportConfig choice),
        NOT on ``build_fn.__name__`` — the choice string is stable across
        renames, while a function rename would otherwise silently fall through
        to the no-arg branch and produce today-only / 30-day data instead of the
        scheduled window.

        irrigation needs compact timestamp strings (its data is keyed on a
        14-char timestamp field); work_reports needs a user for role scoping;
        inventory_txn takes ISO date strings; the rest take no params.
        """
        start, end = _date_window(frequency, today, data_range_days)
        if report_type == 'irrigation':
            # Compact YYYYMMDDHHMM strings — irrigation-day window (D-1 22:00
            # -> D 21:59, see core.irrig_time); calendar days would split
            # overnight runs across two report days.
            from core.irrig_time import irrigation_day_bounds
            df, dt = irrigation_day_bounds(start, end)
            return build_fn(df, dt)
        if report_type == 'work_reports':
            from django.contrib.auth import get_user_model
            User = get_user_model()
            # Scheduled email has no per-user scope — export as a manager
            # (full visibility) using the first superuser. This matches the
            # admin download path, which sees all reports.
            admin = (User.objects.filter(is_superuser=True).first() or User.objects.first())
            return build_fn(start, end, admin)
        if report_type == 'inventory_txn':
            return build_fn(start.isoformat(), end.isoformat())
        # zone / inventory_catalog / projects / purchase_orders → no date params.
        return build_fn()

    def _period_label(self, frequency, today, data_range_days=None):
        return _period_label(frequency, today, data_range_days)

    def _record(self, cfg, status, dry):
        if dry:
            return
        cfg.last_sent_at = timezone.now()
        cfg.last_status = status[:200]
        cfg.save(update_fields=['last_sent_at', 'last_status'])
