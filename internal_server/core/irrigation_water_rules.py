"""Manager-specified physical-meter allocation, independent of Excel row order.

Confirmed against the 2026-11-12 sensor sheet: rows8–48 low/high and17FS,
rows49–75 irrigation FS, and row18 toiletFS. Site99 bench meters contribute
to the all-meter reading only. Never infer a business use from channel alone.
"""

LOW_HIGH_SITES = frozenset((1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15))
CLEANING_SITES = frozenset((3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15))
OTHER_IRRIGATION = {
    35: (15, 16, 17, 18), 36: (11, 12), 37: (15, 16, 17, 18),
    38: (15, 16, 17, 18, 19), 39: (15, 16, 17, 18),
    40: (15, 16), 43: (15, 16), 44: (15, 16), 45: (15, 16),
}


def classify_sensor(site_number, channel):
    if site_number in LOW_HIGH_SITES and channel in (15, 16):
        return 'irrigation'
    if channel in OTHER_IRRIGATION.get(site_number, ()):
        return 'irrigation'
    if site_number in CLEANING_SITES and channel == 17:
        return 'cleaning'
    if (site_number, channel) == (5, 18):
        return 'toilet'
    return None
