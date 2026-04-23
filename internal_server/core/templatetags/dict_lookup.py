from django import template

register = template.Library()


@register.filter
def dict_lookup(d, key):
    """
    Custom template filter to lookup a value in a dictionary by key.
    Usage: {{ mydict|dict_lookup:key }}
    """
    return d.get(key, [])
