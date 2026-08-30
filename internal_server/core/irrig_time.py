"""Irrigation-day window helpers.

Maxicom's irrigation day D runs from D-1 22:00 to D 21:59 — overnight
irrigation belongs to the following day. Runtime rows are stored with RAW
timestamps (see import_maxicom_mdb_linux: poll rows and minute-run rows both
keep their true poll/run time), so day-scoped views must use these
boundaries instead of calendar 00:00-23:59 to match the Maxicom UI's daily
totals (verified 2026-08-30: CCU2 SAT 2-6 st11 irrigation day 2026-08-27 =
18+42+108 = 168 min; custom windows 84/25/20/20 min across four stations).
"""
from datetime import timedelta


def irrigation_day_bounds(start, end):
    """(from14, to14) compact timestamps covering irrigation days start..end.

    ``start``/``end`` are datetime.date objects. Day D's irrigation window is
    [D-1 22:00:00, D 21:59:59], so a multi-day range start..end maps to
    [start-1 22:00, end 21:59].
    """
    f = (start - timedelta(days=1)).strftime('%Y%m%d') + '2200'
    t = end.strftime('%Y%m%d') + '2159'
    return f, t
