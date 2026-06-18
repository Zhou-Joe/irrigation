from django import template

register = template.Library()

VIDEO_EXTS = {'.mp4', '.mov', '.m4v', '.webm', '.ogg', '.ogv', '.avi', '.mkv'}


@register.filter
def is_video(path):
    """Return True if the media path looks like a video file."""
    if not path:
        return False
    p = str(path).lower()
    return any(p.endswith(ext) for ext in VIDEO_EXTS)
