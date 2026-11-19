"""Translate valve geometry in a drawing into a north-up map symbol pose."""
import math
from collections import defaultdict


def insert_frame(insert):
    matrix = insert.matrix44()
    frame = []
    for axis in ((1, 0, 0), (0, 1, 0)):
        vector = matrix.transform_direction(axis)
        length = math.hypot(vector.x, vector.y)
        if not math.isfinite(length) or length < 1e-12:
            return None
        frame.append([vector.x / length, vector.y / length])
    return frame


def outline_axis(paths):
    """Principal axis of linework, weighted by length rather than DXF vertex density."""
    if not paths:
        return None
    ox, oy = paths[0][0]
    length = sx = sy = xx = xy = yy = 0.
    for path in paths:
        for p, q in zip(path, path[1:]):
            dx, dy = q[0] - p[0], q[1] - p[1]
            weight = math.hypot(dx, dy)
            mx, my = p[0] - ox + dx / 2, p[1] - oy + dy / 2
            length += weight
            sx += weight * mx
            sy += weight * my
            xx += weight * (mx * mx + dx * dx / 12)
            yy += weight * (my * my + dy * dy / 12)
            xy += weight * (mx * my + dx * dy / 12)
    if not length:
        return None
    xx -= sx * sx / length
    yy -= sy * sy / length
    xy -= sx * sy / length
    # Near-round outlines have no repeatable long axis (including tessellation noise).
    if xx + yy <= 0 or math.hypot(xx - yy, 2 * xy) < .15 * (xx + yy):
        return None
    angle = math.atan2(2 * xy, xx - yy) / 2
    return [[math.cos(angle), math.sin(angle)]]


def map_pose(project, x, y, frame):
    if not frame:
        return None
    try:
        origin = project(x, y, 12)
        cosine = math.cos(math.radians(origin['lat']))
        vectors = []
        for dx, dy in frame:
            tip = project(x + dx, y + dy, 12)
            vector = ((tip['lng'] - origin['lng']) * cosine, origin['lat'] - tip['lat'])
            if math.hypot(*vector) < 1e-12:
                return None
            vectors.append(vector)
    except (ValueError, OverflowError):
        return None
    vx, vy = vectors[0]
    angle = math.degrees(math.atan2(vy, vx))
    if len(vectors) == 1:
        return {'angle': round((angle + 90) % 180 - 90, 2), 'source': 'axis', 'mirrored': False}
    ux, uy = vectors[1]
    det = vx * uy - vy * ux
    if abs(det) < 1e-6 * math.hypot(vx, vy) * math.hypot(ux, uy):
        return None
    return {'angle': round(angle, 2), 'source': 'block', 'mirrored': det > 0}


def batch_poses(source, project, source_ids):
    """Resolve both new imports and historical batches without altering their geometry."""
    if not source_ids:
        return {}
    blocks = {v['source_id']: v for v in source.get('valves', []) if v.get('source_id') in source_ids}
    shapes = {s['id']: s for s in source.get('recognized_shapes', []) if s.get('id') in source_ids}
    paths = defaultdict(list)
    legacy = {sid for sid, v in blocks.items() if not v.get('cad_frame')}
    layers = source.get('layers', {})
    if legacy:
        for name, bucket in layers.items():
            if name.startswith('块·'):
                for entity, path in zip(bucket.get('entities', []), bucket.get('polys', [])):
                    sid = '/'.join(entity.get('source_id', '').split('/')[:2])
                    if sid in legacy and len(path) >= 2:
                        paths[sid].append(path)
    for sid, shape in shapes.items():
        for ref in shape.get('source_refs', []):
            polys = layers.get(ref['layer'], {}).get('polys', [])
            index = ref['index']
            if 0 <= index < len(polys) and len(polys[index]) >= 2:
                paths[sid].append(polys[index])
    poses = {}
    for sid, device in (blocks | shapes).items():
        frame = device.get('cad_frame') or outline_axis(paths[sid])
        pose = map_pose(project, device['x'], device['y'], frame)
        if pose:
            poses[sid] = pose
    return poses
