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
    XLSX_CT,
)


def _is_due_today(cfg, today=None):
    """Should this config fire on `today`?

    Reads cfg.weekday (0=Mon..6=Sun, default 0) for weekly and
    cfg.month_day (1-28, default 1) for monthly, so the admin can pick the
    trigger day instead of the hardcoded Monday / 1st.
    """
    today = today or timezone.localdate()
    if cfg.frequency == 'daily':
        return True
    if cfg.frequency == 'weekly':
        wd = cfg.weekday if cfg.weekday is not None else 0   # default Monday
        return today.weekday() == wd
    if cfg.frequency == 'monthly':
        md = cfg.month_day if cfg.month_day is not None else 1  # default 1st
        return today.day == md
    return False


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

        today = timezone.localdate()
        configs = list(qs.order_by('frequency', 'name'))
        self.stdout.write(f'Email report dispatch: {len(configs)} config(s), '
                          f'today={today.isoformat()}, dry_run={dry}')

        sent, skipped, failed = 0, 0, 0
        for cfg in configs:
            # Frequency gate (skipped when forcing one config by id).
            if not force_id and not _is_due_today(cfg, today):
                self.stdout.write(f'  [skip] {cfg.name} ({cfg.frequency}) — not due today')
                skipped += 1
                continue

            recipients = cfg.recipient_list
            if not recipients:
                msg = '无收件人邮箱'
                self._record(cfg, 'failed: ' + msg, dry)
                self.stdout.write(self.style.ERROR(f'  [fail] {cfg.name}: {msg}'))
                failed += 1
                continue

            build_fn, label = _resolve_builder(cfg.report_type)
            if build_fn is None:
                msg = f'未知报表类型 {cfg.report_type}'
                self._record(cfg, 'failed: ' + msg, dry)
                self.stdout.write(self.style.ERROR(f'  [fail] {cfg.name}: {msg}'))
                failed += 1
                continue

            try:
                fname, buf = self._build_report(cfg.report_type, build_fn, cfg.frequency, today, cfg.data_range_days)
            except Exception as e:
                msg = f'生成报表失败: {e}'
                self._record(cfg, 'failed: ' + msg, dry)
                self.stdout.write(self.style.ERROR(f'  [fail] {cfg.name}: {msg}'))
                failed += 1
                continue

            period_label = self._period_label(cfg.frequency, today, cfg.data_range_days)
            subject = f'【{label}】{period_label} 报表 — {cfg.name}'
            body = (f'您好，\n\n这是系统自动发送的定时报表。\n'
                    f'报表类型：{label}\n频率：{cfg.get_frequency_display()}\n'
                    f'数据范围：{period_label}\n\n请见附件。')

            if dry:
                self.stdout.write(self.style.WARNING(
                    f'  [dry] {cfg.name} → {recipients} | {fname} '
                    f'| subject="{subject}"'))
                continue

            try:
                from core.smtp_utils import get_email_connection, resolve_from_email
                msg = EmailMessage(
                    subject=subject, body=body,
                    from_email=resolve_from_email(), to=recipients,
                    connection=get_email_connection(),
                )
                msg.attach(fname, buf.getvalue(), XLSX_CT)
                msg.send(fail_silently=False)
                self._record(cfg, 'success', dry)
                self.stdout.write(self.style.SUCCESS(
                    f'  [ok] {cfg.name} → {len(recipients)} recipient(s) ({fname})'))
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
            # Compact YYYYMMDDHHMM strings — full-day window (00:00–23:59).
            df = start.strftime('%Y%m%d') + '0000'
            dt = end.strftime('%Y%m%d') + '2359'
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
