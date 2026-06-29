import json
import os
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

VIDEO_EXTS = {'.mp4', '.mov', '.m4v', '.webm', '.ogg', '.ogv', '.avi', '.mkv'}


@register.filter
def is_video(path):
    """Return True if the media path looks like a video file."""
    if not path:
        return False
    p = str(path).lower()
    return any(p.endswith(ext) for ext in VIDEO_EXTS)


@register.filter
def thumb(path):
    """Derive the thumbnail path for an original media path.

    ``workorder_photos/12/IMG_1234.jpg`` → ``workorder_photos/12/IMG_1234_thumb.jpg``
    Mirrors core.workorder_tree_views.thumb_path so the list page can load the
    tiny thumbnail instead of the multi-MB original.
    """
    if not path:
        return path
    base, _ext = os.path.splitext(str(path))
    return base + '_thumb.jpg'


@register.filter
def to_json(value):
    """Serialize a Python value to a JSON string for safe embedding in a
    <script> block. Use this instead of ``|safe`` on JSONFields — ``str(list)``
    emits single-quoted Python repr, which breaks ``JSON.parse``.

    Output is marked safe and escapes ``<``/``>`` so a value containing
    ``</script>`` can't break out of the script context.
    """
    s = json.dumps(value, ensure_ascii=False)
    s = s.replace('<', '\\u003c').replace('>', '\\u003e')
    return mark_safe(s)
