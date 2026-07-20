"""Level (evenly spread) PM start_dates within each frequency group.

Problem: every PM seeded from the same ``start_date`` produces identical
rrule occurrences, so all PMs in a frequency group come due on the SAME day
(e.g. 166 每3周 plans all on 2026-08-02). A large ``lead_days`` only generates
them earlier — it does not spread them.

This command phases each PM's ``start_date`` evenly across one cycle so the
due dates flatten out. For a group of N plans with a cycle of P days, plan i
(sorted by id for determinism) gets offset ≈ round(i·P/N) days from the
group's anchor (its min start_date). The generation engine is untouched —
this works for both the daily cron and 立即生成.

Idempotent-ish: deterministic given the same plan set, so re-running with no
membership change reproduces the same dates. Adding plans shifts the even
spacing, so re-level only after bulk additions (a few new PMs can be slotted
manually). Already-generated work orders are never moved — only future
occurrences change (consistent with the form's
"改后仅影响未来派发，已生成工单不变").

Usage:
    python manage.py level_pm_schedule                 # dry-run (preview)
    python manage.py level_pm_schedule --apply         # write new start_dates
    python manage.py level_pm_schedule --preview-days 120
"""

from collections import defaultdict, Counter
from datetime import timedelta

from dateutil.rrule import rrule, DAILY, WEEKLY, MONTHLY

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import MaintenancePlan

FREQ = {'days': DAILY, 'weeks': WEEKLY, 'months': MONTHLY}
# Average length of each unit in days — only used to size the spread window.
DAYS_PER_UNIT = {'days': 1, 'weeks': 7, 'months': 30.437}


class Command(BaseCommand):
    help = ('Spread PM start_dates evenly within each frequency group so '
            'due dates do not cluster on one day (dry-run by default).')

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Write the new start_dates (default: dry-run preview).')
        parser.add_argument('--exclude-units', nargs='*', default=['days'],
                            help='frequency_units to skip (default: days).')
        parser.add_argument('--preview-days', type=int, default=90,
                            help='Days of projected daily load to print in dry-run.')

    def handle(self, *args, **opts):
        today = timezone.localdate()
        do_apply = opts['apply']
        skip = set(opts['exclude_units'])
        preview_days = opts['preview_days']

        # ── Group all non-excluded plans by (frequency_value, frequency_unit) ─
        groups = defaultdict(list)
        for p in MaintenancePlan.objects.all():
            if p.frequency_unit in skip or p.frequency_unit not in FREQ:
                continue
            if not p.start_date:
                continue
            groups[(p.frequency_value, p.frequency_unit)].append(p)

        def _next_due(plan, start):
            """First rrule occurrence on/after today, anchored at `start`."""
            occ = list(rrule(FREQ[plan.frequency_unit],
                             interval=plan.frequency_value,
                             dtstart=start,
                             until=today + timedelta(days=400)))
            for x in occ:
                d = x.date() if hasattr(x, 'date') else x
                if d >= today:
                    return d
            return None

        # ── Compute the leveled start_date for every plan ───────────────────
        changes = []  # (plan, old_start, new_start)
        for (fv, fu), plans in groups.items():
            period = max(1, int(round(fv * DAYS_PER_UNIT[fu])))
            plans.sort(key=lambda p: p.id)
            anchor = min(p.start_date for p in plans)
            n = len(plans)
            for i, p in enumerate(plans):
                offset = round(i * period / n) if n else 0
                if offset >= period:
                    offset = period - 1
                new_start = anchor + timedelta(days=offset)
                if new_start != p.start_date:
                    changes.append((p, p.start_date, new_start))

        self.stdout.write(self.style.SUCCESS(
            f'{"APPLY" if do_apply else "DRY RUN"} — {len(changes)} of '
            f'{sum(len(v) for v in groups.values())} non-daily plans would be '
            f'rescheduled (across {len(groups)} frequency groups).'))

        # ── Per-group before/after peak load ────────────────────────────────
        self.stdout.write('\nPer-group load (active plans only):')
        self.stdout.write(f'  {"frequency":<12}{"N":>5}{"cycle(d)":>10}'
                          f'{"BEFORE peak":>16}{"AFTER peak":>16}{"AFTER avg/d":>13}')
        active = [p for p in MaintenancePlan.objects.filter(active=True)
                  if p.frequency_unit not in skip and p.frequency_unit in FREQ and p.start_date]
        new_start_by_id = {c[0].id: c[2] for c in changes}
        for (fv, fu), plans in sorted(groups.items()):
            period = max(1, int(round(fv * DAYS_PER_UNIT[fu])))
            act = [p for p in plans if p.active]
            if not act:
                continue
            before = Counter(_next_due(p, p.start_date) for p in act)
            after = Counter(_next_due(p, new_start_by_id.get(p.id, p.start_date)) for p in act)
            b_peak = before.most_common(1)[0] if before else (None, 0)
            a_peak = after.most_common(1)[0] if after else (None, 0)
            horizon = max((d for d in after if d), default=today)
            span = (horizon - today).days or 1
            avg = sum(after.values()) / span if span else 0
            label = f'每{fv}{ {"days":"天","weeks":"周","months":"月"}[fu] }'
            self.stdout.write(
                f'  {label:<12}{len(act):>5}{period:>10}'
                f'{b_peak[1]:>10}{("/"+str(b_peak[0])[-5:]) if b_peak[0] else "":>6}'
                f'{a_peak[1]:>10}{("/"+str(a_peak[0])[-5:]) if a_peak[0] else "":>6}'
                f'{avg:>10.1f}')

        # ── Daily-load histogram (AFTER) for the preview window ─────────────
        by_day_after = Counter()
        by_day_before = Counter()
        for p in active:
            bd = _next_due(p, p.start_date)
            ad = _next_due(p, new_start_by_id.get(p.id, p.start_date))
            if bd:
                by_day_before[bd] += 1
            if ad:
                by_day_after[ad] += 1
        peak_before = max(by_day_before.values() or [0])
        peak_after = max(by_day_after.values() or [0])
        self.stdout.write(
            f'\nOverall next-cycle daily load (next {preview_days}d, active plans):')
        self.stdout.write(f'  BEFORE peak day = {peak_before} work orders')
        self.stdout.write(f'  AFTER  peak day = {peak_after} work orders '
                          f'({(1 - peak_after / peak_before) * 100:.0f}% flatter)' if peak_before
                          else '  AFTER  peak day = 0')

        # Weekly buckets keep the histogram readable.
        self.stdout.write('\nAFTER load by week (count of due PMs landing in that week):')
        for w in range(0, preview_days, 7):
            wk_start = today + timedelta(days=w)
            cnt = sum(c for d, c in by_day_after.items()
                      if wk_start <= d < wk_start + timedelta(days=7))
            bar = '█' * min(40, cnt)
            self.stdout.write(f'  {wk_start.isoformat()}  {cnt:>4}  {bar}')

        if not do_apply:
            self.stdout.write(self.style.WARNING(
                '\nDry-run only — no start_dates changed. Re-run with --apply to write.'))
            return

        # ── Apply ───────────────────────────────────────────────────────────
        with transaction.atomic():
            for plan, _old, new_start in changes:
                MaintenancePlan.objects.filter(id=plan.id).update(start_date=new_start)
        self.stdout.write(self.style.SUCCESS(
            f'\nApplied: {len(changes)} start_dates leveled.'))
