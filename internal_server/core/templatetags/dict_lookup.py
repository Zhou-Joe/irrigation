from django import template

register = template.Library()


@register.filter
def dict_lookup(d, key):
    """
    Custom template filter to lookup a value in a dictionary by key.
    Usage: {{ mydict|dict_lookup:key }}
    """
    return d.get(key, [])


@register.filter
def boundary_count(bp):
    """Count the number of closed loops in boundary_points."""
    if not bp:
        return 0
    first = bp[0]
    if isinstance(first, list):
        return len(bp)
    return 1
