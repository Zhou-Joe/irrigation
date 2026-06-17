"""Cache-invalidation signals for the dashboard.

The dashboard view caches several rarely-changing builders (pipelines, plant
names, landmarks, patches, map style) behind TTL keys (see core.views._cached).
To keep that data fresh on edit — without waiting out the TTL — these receivers
delete the relevant key whenever its source model is saved or deleted.

The mapping is centralized in CACHE_KEY_BY_MODEL so it stays in one place.
"""

from django.db.models.signals import post_save, post_delete


def _build_key_index():
    """Inverted index: model class → list of cache keys.

    Built lazily (models must be ready) and keyed by the model class itself, so
    it can never drift from Django's actual model_name/app_label conventions.
    """
    from core.models import Pipeline, Plant, Landmark, ZoneLandmarkAssignment, Patch, MapStyleSettings
    return {
        Pipeline: ['dashboard:pipelines'],
        Plant: ['dashboard:plant_names'],
        Landmark: ['dashboard:landmarks'],
        ZoneLandmarkAssignment: ['dashboard:landmarks'],
        Patch: ['dashboard:patches'],
        MapStyleSettings: ['dashboard:map_style'],
    }


_KEY_INDEX = None  # lazily populated on first signal


def _invalidate_keys(keys):
    """Delete the given cache keys, swallowing cache errors."""
    if not keys:
        return
    try:
        from django.core.cache import cache
    except Exception:
        return
    for k in keys:
        try:
            cache.delete(k)
        except Exception:
            pass


def _on_save_or_delete(sender, **kwargs):
    """Clear dashboard cache keys when a backing model is saved or deleted.

    Bound globally (no sender= filter); the key index short-circuits for models
    we don't cache on. Also catches subclasses via isinstance.
    """
    global _KEY_INDEX
    if _KEY_INDEX is None:
        _KEY_INDEX = _build_key_index()
    keys = _KEY_INDEX.get(sender)
    # Fall back to a subclass match (e.g. proxy/polymorphic senders).
    if keys is None:
        for model, k in _KEY_INDEX.items():
            try:
                if issubclass(sender, model):
                    keys = k
                    break
            except TypeError:
                pass
    if keys:
        _invalidate_keys(keys)


def _connect():
    """Register the receiver strongly (weak=False + dispatch_uid).

    Without weak=False Django stores only a weakref to the handler, which can be
    garbage-collected and silently stop firing — exactly the bug this avoids.
    dispatch_uid makes the connect idempotent (safe to call from ready()).
    """
    post_save.connect(_on_save_or_delete, weak=False, dispatch_uid='dashboard_cache_invalidate')
    post_delete.connect(_on_save_or_delete, weak=False, dispatch_uid='dashboard_cache_invalidate_delete')


_connect()
