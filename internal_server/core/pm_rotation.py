"""Initialize stable, evenly spaced PM phases before either dispatch entry point.

Existing phases stay fixed. New plans fill the largest gaps; explicit releveling
is available through level_pm_schedule. Issued work orders are never rewritten.
"""

from collections import defaultdict
from fractions import Fraction

from django.db import transaction
from django.db.models import Max

from .models import MaintenancePlan, GeneratedWorkOrder
from .pm_utils import completion_deadline, cycle_index, occurrence


ROTATION_FIELDS = ('start_date', 'rotation_anchor', 'rotation_slot', 'rotation_size', 'rotation_cycle')


def _new_phases(existing, count):
    """Divide available gaps in proportion to their length, deterministically."""
    phases = sorted(set(existing))
    if not phases:
        return [Fraction(i, count) for i in range(count)]
    gaps = [(phase, (phases[(i + 1) % len(phases)] - phase) % 1 or Fraction(1))
            for i, phase in enumerate(phases)]
    allocations = [0] * len(gaps)
    for _ in range(count):
        i = max(range(len(gaps)), key=lambda i: gaps[i][1] / (allocations[i] + 1))
        allocations[i] += 1
    return sorted((start + length * Fraction(i, n + 1)) % 1
                  for (start, length), n in zip(gaps, allocations)
                  for i in range(1, n + 1))


def _phase_from_date(plan, anchor):
    """Locate an explicitly chosen date in the group's reference cycle."""
    from types import SimpleNamespace
    reference = SimpleNamespace(start_date=anchor, frequency_unit=plan.frequency_unit,
                                frequency_value=plan.frequency_value)
    # cycle_index intentionally returns -1 before the first occurrence; use
    # the plan's next occurrence when the reference anchor is later.
    day = plan.start_date
    if day < anchor:
        from .pm_utils import next_due
        day = next_due(plan, anchor)
    index = cycle_index(reference, day)
    start, end = occurrence(reference, index), occurrence(reference, index + 1)
    return Fraction((day - start).days, (end - start).days)


def initialize_rotation(today, *, apply=False, relevel=False, exclude_units=()):
    """Return projected plans and their previous dates; optionally persist them.

    A changed plan with history begins after its last issued execution cycle.
    This prevents rotated historical dates from being backfilled a second time,
    including work already generated ahead of today by lead_days.
    """
    with transaction.atomic():
        plans = list(MaintenancePlan.objects.select_for_update().filter(
            active=True, job_plan__active=True, frequency_value__gte=1,
            frequency_unit__in=['days', 'weeks', 'months'],
        ).exclude(frequency_unit__in=exclude_units).order_by('id'))
        latest = dict(GeneratedWorkOrder.objects.filter(plan_id__in=[p.pk for p in plans])
                      .values('plan_id').annotate(day=Max('scheduled_date'))
                      .values_list('plan_id', 'day'))
        groups = defaultdict(list)
        for plan in plans:
            groups[(plan.frequency_value, plan.frequency_unit)].append(plan)
        changes = []
        for group in groups.values():
            if len(group) == 1 and group[0].rotation_anchor is not None:
                continue
            pending = group if relevel else [p for p in group if p.rotation_anchor is None]
            if not pending:
                continue
            fixed = [] if relevel else [p for p in group if p.rotation_anchor is not None]
            anchor = min((p.rotation_anchor for p in fixed), default=min(
                p.rotation_anchor or p.start_date for p in group))
            phases = _new_phases([
                Fraction(p.rotation_slot, p.rotation_size)
                if p.rotation_anchor == anchor else _phase_from_date(p, anchor)
                for p in fixed
            ], len(pending))
            for plan, phase in zip(pending, phases):
                old_start = plan.start_date
                old_schedule = tuple(getattr(plan, name) for name in ROTATION_FIELDS)
                same_phase = ((plan.rotation_anchor or old_start) == anchor and
                              Fraction(plan.rotation_slot, plan.rotation_size) == phase)
                plan.rotation_anchor = anchor
                plan.rotation_slot, plan.rotation_size = phase.numerator, phase.denominator
                plan.rotation_cycle = 0 if not same_phase else plan.rotation_cycle
                # Keep a singleton's exact recurrence and its historical backfill.
                if len(group) == 1:
                    plan.rotation_anchor = old_start
                elif not same_phase:
                    lower = old_start
                    if plan.pk in latest:
                        lower = max(lower, today, completion_deadline(plan, latest[plan.pk]))
                    # Locate the first phased occurrence at/after the lower bound.
                    plan.start_date = occurrence(plan, 0)
                    index = max(0, cycle_index(plan, lower))
                    if occurrence(plan, index) < lower:
                        index += 1
                    plan.rotation_cycle = index
                plan.start_date = occurrence(plan, 0)
                if tuple(getattr(plan, name) for name in ROTATION_FIELDS) != old_schedule:
                    changes.append((plan, old_start))
        if apply and changes:
            MaintenancePlan.objects.bulk_update([p for p, _ in changes], ROTATION_FIELDS)
    return plans, changes
