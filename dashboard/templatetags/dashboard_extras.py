# dashboard/templatetags/dashboard_extras.py
from django import template

register = template.Library()


@register.filter(name="get_item")
def get_item(mapping, key):
    """
    Safe dict lookup for templates.
    Usage: {{ mydict|get_item:"some_key" }}
    """
    if isinstance(mapping, dict):
        return mapping.get(key)
    # .items() in a QueryDict-like object still works via .get
    try:
        return mapping.get(key)
    except Exception:
        return None
