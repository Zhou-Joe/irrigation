"""Drawing-independent valve candidates and reusable, normalized shape examples.

Coordinates, rotation, reflection and axis scales are removed before comparison.
Matching proposes source entities; only reviewed selections become valve assets.
The original CAD geometry is always retained.
"""
import hashlib
import json
import math
import re
from collections import defaultdict

import numpy as np

SAMPLE_POINTS = 64
MATCH_ERROR = .12
MAX_SAMPLE_PARTS = 20
MAX_CANDIDATES = 600
SYMBOL_PREFIX = '符号·'

CODE_TYPES = {
    'WD': 'washdown', 'WASHDOWN': 'washdown', '冲洗阀': 'washdown',
    'GV': 'gate', 'GATE': 'gate', '闸阀': 'gate', '蝶阀': 'gate',
    'AV': 'angle', '角阀': 'angle', 'QCV': 'qcv', '取水阀': 'qcv',
    'SV': 'solenoid', 'CF': 'solenoid', '电磁阀': 'solenoid',
    'PB': 'pullbox', '拉线箱': 'pullbox',
}


def text_type(text):
    value = re.sub(r'\s+', '', str(text or '')).upper()
    if value in CODE_TYPES:
        return CODE_TYPES[value]
    hit = re.fullmatch(r'(WD|GV|AV|QCV|SV|CF|PB)[-_]?\d+(?:[-/]\d+)?', value)
    return CODE_TYPES.get(hit[1]) if hit else None


def inline_text(label):
    """Short text within a block belongs to its symbol, including identifiers."""
    text = str(label.get('text') or '').strip()
    return bool(label.get('block') and 0 < len(text) <= 16 and '\n' not in text)


def bounds(paths):
    points = [p for path in paths for p in path]
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]


def _span(box):
    return math.hypot(box[2]-box[0], box[3]-box[1])


def _clean_paths(paths):
    result = []
    for path in paths:
        points = []
        for point in path:
            if len(point) != 2 or any(isinstance(v, bool) for v in point):
                raise ValueError('图形坐标无效')
            value = tuple(float(v) for v in point)
            if not all(math.isfinite(v) for v in value):
                raise ValueError('图形坐标必须是有限数值')
            if not points or value != points[-1]:
                points.append(value)
        if len(points) >= 2:
            result.append(points)
    if not result or sum(len(path) for path in result) > 3000:
        raise ValueError('请圈选完整、清晰的单个阀门图形')
    return result


def _sample(paths):
    lengths = [sum(math.dist(a,b) for a,b in zip(path,path[1:])) for path in paths]
    total = sum(lengths)
    if total <= 1e-12:
        raise ValueError('图形尺寸为零')
    base = max(SAMPLE_POINTS, len(paths)*3)
    counts = [max(3, round(base*length/total)) for length in lengths]
    sampled = []
    for path, length, count in zip(paths, lengths, counts):
        if length <= 0:
            continue
        points = np.asarray(path, dtype=float)
        distance = np.concatenate(([0.], np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))))
        at = np.linspace(0, length, count)
        sampled.extend(zip(np.interp(at,distance,points[:,0]), np.interp(at,distance,points[:,1])))
    return np.asarray(sampled)


def _features(paths):
    points = _sample(paths)
    center = points.mean(axis=0)
    centered = points-center
    covariance = centered.T@centered/len(centered)
    values, axes = np.linalg.eigh(covariance)
    if values[-1] <= 1e-20 or values[0] < values[-1]*.002:
        raise ValueError('样本只有直线，请圈选完整阀门符号')
    # Whitening allows elongated and compact versions of the same drawing style.
    normalized = (centered@axes)/np.sqrt(values)
    radial = np.linalg.norm(normalized,axis=1)
    subset = normalized[np.linspace(0,len(normalized)-1,min(32,len(normalized)),dtype=int)]
    distances = np.linalg.norm(subset[:,None,:]-subset[None,:,:],axis=2)
    descriptor = np.concatenate((np.quantile(radial,[.1,.25,.5,.75,.9]),
                                  np.quantile(distances,[.1,.25,.5,.75,.9])))
    return {'points':normalized, 'descriptor':descriptor, 'center':center,
            'scale':math.sqrt(float(values.sum())), 'bounds':bounds(paths)}


def _distance(reference, target):
    if np.linalg.norm(reference['descriptor']-target['descriptor']) > .55:
        return 1.
    a, b = reference['points'], target['points']
    best, best_angle, best_sign = 10., 0., 1
    def error(angle, sign):
        cosine, sine = math.cos(angle), math.sin(angle)
        rotated = a@np.array([[sign*cosine,sign*sine],[-sine,cosine]])
        distance = np.sum((rotated[:,None,:]-b[None,:,:])**2,axis=2)
        return max(float(distance.min(axis=0).mean()),float(distance.min(axis=1).mean()))**.5
    for sign in (1,-1):
        for index in range(24):
            angle = index*math.pi/12
            score = error(angle,sign)
            if score < best:
                best, best_angle, best_sign = score, angle, sign
    for step in (-6,-4,-2,2,4,6):
        best = min(best,error(best_angle+math.radians(step),best_sign))
    return best


def shape_error(reference_paths, target_paths):
    try:
        return _distance(_features(_clean_paths(reference_paths)),_features(_clean_paths(target_paths)))
    except (ValueError, np.linalg.LinAlgError):
        return 1.


def _component_error(reference, target):
    def linear(path):
        length=sum(math.dist(a,b) for a,b in zip(path,path[1:]))
        return length>0 and math.dist(path[0],path[-1])/length>.995
    if linear(reference) and linear(target):
        return 0.
    return shape_error([reference],[target])


def make_template(paths, name, valve_type, labels=()):
    paths = _clean_paths(paths)
    if len(paths) > MAX_SAMPLE_PARTS:
        raise ValueError('一个样本最多包含 20 个图形，请缩小圈选范围')
    feature = _features(paths)
    # Plain elbows are indistinguishable from the pipe itself.
    vertices = sum(len(path)-1 for path in paths)
    box = feature['bounds']; span = _span(box)
    closed = any(math.dist(path[0],path[-1]) < span*.025 for path in paths)
    if vertices < 4 and not closed:
        raise ValueError('样本只有直线或普通弯头，请圈入完整阀门标识')
    center, scale = feature['center'], feature['scale']
    geometry = [[[round((x-center[0])/scale,7),round((y-center[1])/scale,7)] for x,y in path] for path in paths]
    hints = [lb['text'].strip() for lb in labels if text_type(lb.get('text')) and
             box[0] <= lb['x'] <= box[2] and box[1] <= lb['y'] <= box[3]]
    digest = hashlib.sha256(json.dumps(geometry,separators=(',',':')).encode()).hexdigest()
    return {'name':name, 'valve_type':valve_type, 'geometry':geometry,
            'text_hint':hints[0] if hints else '', 'fingerprint':digest, 'version':1}


def source_records(layers, *, include_blocks=False):
    records = []
    for layer, bucket in layers.items():
        if not include_blocks and layer.startswith(('块·',SYMBOL_PREFIX)):
            continue
        for index, points in enumerate(bucket.get('polys',[])):
            if len(points)<2:
                continue
            entities = bucket.get('entities') or []
            entity = entities[index] if index<len(entities) else {}
            box = bounds([points])
            if _span(box) <= 1e-12:
                continue
            records.append({'layer':layer,'index':index,'source_id':entity.get('source_id',''),
                            'points':points,'bounds':box,'span':_span(box)})
    return records


def sample_from_refs(layers, refs):
    if not isinstance(refs,list) or not 1 <= len(refs) <= MAX_SAMPLE_PARTS:
        raise ValueError('请圈选 1 到 20 个组成阀门的图形')
    records = {(r['layer'],r['index']):r for r in source_records(layers,include_blocks=True)}
    selected = []
    for ref in refs:
        if not isinstance(ref,dict) or not isinstance(ref.get('layer'),str) or type(ref.get('index')) is not int:
            raise ValueError('样本图形无效，请重新圈选')
        key = (ref.get('layer'),ref['index'])
        if key not in records or key in selected:
            raise ValueError('样本与当前图纸不一致，请重新圈选')
        selected.append(key)
    return [records[key]['points'] for key in selected]


def _inside_labels(box, labels):
    margin = _span(box)*.08
    return [lb for lb in labels if not lb.get('block') and len(lb.get('text','').strip())<=24 and
            box[0]-margin <= lb['x'] <= box[2]+margin and box[1]-margin <= lb['y'] <= box[3]+margin]


def block_hints(valves, labels):
    """Classify an opaque block name using its own text/attributes, not another block."""
    by_instance=defaultdict(list)
    for label in labels:
        if label.get('block'):
            by_instance['/'.join(label.get('source_id','').split('/')[:2])].append(label)
    result=defaultdict(list)
    for valve in valves:
        texts=[lb['text'] for lb in by_instance.get(valve.get('source_id',''),[])]
        texts.extend(valve.get('attrs',{}).values())
        for text in texts:
            kind=text_type(text)
            if kind:result[valve['block']].append({'type':kind,'text':str(text).strip()})
    return result


def builtin_templates():
    bowtie = [[[-1,-.6],[1,.6],[1,-.6],[-1,.6],[-1,-.6]]]
    return [dict(make_template(bowtie,'对称三角阀门',''),id='builtin:bowtie')]


def _round_outline(paths):
    if len(paths)!=1:return False
    path=paths[0];span=_span(bounds(paths))
    if len(path)<8 or math.dist(path[0],path[-1])>span*.025:return False
    circle=[[[math.cos(i*math.pi/24),math.sin(i*math.pi/24)] for i in range(49)]]
    return shape_error(circle,paths)<.08


def recognize(layers, labels, templates=()):
    """Return reviewable candidates, preserving source identity and original paths."""
    from shapely.geometry import LineString, Point, box as shape_box
    from shapely.strtree import STRtree
    records = source_records(layers)
    if not records:
        return []
    geometries = [LineString(record['points']) for record in records]
    tree = STRtree(geometries)
    compiled = []
    for template in [*builtin_templates(),*templates]:
        try:
            paths = _clean_paths(template['geometry'])
            compiled.append((dict(template,ambiguous_round=_round_outline(paths)),paths,_features(paths)))
        except (ValueError,KeyError,np.linalg.LinAlgError):
            continue
    found = []
    features = {}
    def feature(index):
        if index not in features:
            try:features[index] = _features([records[index]['points']])
            except (ValueError,np.linalg.LinAlgError):features[index] = None
        return features[index]
    def proposal(indices, template, error, text_labels):
        chosen = [records[i] for i in sorted(indices)]
        paths = [r['points'] for r in chosen]
        box = bounds(paths)
        x,y = ((box[0]+box[2])/2,(box[1]+box[3])/2)
        refs = [{key:r[key] for key in ('layer','index','source_id')} for r in chosen]
        token = hashlib.sha256(json.dumps([refs,template.get('fingerprint','text')],sort_keys=True).encode()).hexdigest()[:24]
        hint = next((lb['text'] for lb in text_labels if text_type(lb['text'])), '')
        kind = text_type(hint) or template.get('valve_type') or ''
        score = max(0.,1.-error*.9)
        missing_text=bool(template.get('text_hint') and not any(text_type(lb['text'])==template.get('valve_type') for lb in text_labels))
        if missing_text:score=min(score,.72)
        nearby=False
        span=_span(box)
        for other in tree.query(shape_box(x-span,y-span,x+span,y+span)):
            other=int(other)
            if other not in indices and geometries[other].length>span*1.5 and geometries[other].distance(Point(x,y))<span*.8:
                nearby=True;break
        ambiguous_round=bool(template.get('ambiguous_round') and not hint)
        if ambiguous_round:score=min(score,.78)
        if not nearby and not hint:score=min(score,.85)
        found.append({'id':'shape:'+token,'source_kind':'polyline','template_id':str(template.get('id','text')),
            'template_name':template['name'],'valve_type_guess':kind,'include_guess':bool(kind) and not missing_text and not ambiguous_round,
            'confidence':round(score,3),'source_refs':refs,'x':x,'y':y,'bounds':box,
            'text':hint or next((lb['text'] for lb in text_labels),''),
            'label_refs':[lb['source_id'] for lb in text_labels if lb.get('source_id')],
            'nearby_line':nearby,
            'reason':'图形相似，标识待核对' if missing_text else '圆形图案，请核对用途' if ambiguous_round else '内部文字与图形' if hint else '已保存图形样本' if not str(template.get('id','')).startswith('builtin:') else '常见阀门图形'})
    for index,record in enumerate(records):
        points = record['points']; span = record['span']
        text_labels = _inside_labels(record['bounds'],labels)
        hinted = [lb for lb in text_labels if text_type(lb.get('text'))]
        center=((record['bounds'][0]+record['bounds'][2])/2,(record['bounds'][1]+record['bounds'][3])/2)
        if len(hinted)==1 and len(points)>=4 and math.dist(points[0],points[-1]) <= span*.03 and (
                math.dist(center,(hinted[0]['x'],hinted[0]['y']))<span*.25) and (
                not hinted[0].get('height') or span<hinted[0]['height']*25):
            proposal([index],{'id':'text','name':hinted[0]['text']+' 标识','valve_type':text_type(hinted[0]['text'])},0.,text_labels)
        current = feature(index)
        for template,paths,reference in compiled:
            if current is not None:
                error = _distance(reference,current)
                if error <= MATCH_ERROR:
                    proposal([index],template,error,text_labels)
            if len(paths)<2:
                continue
            # Composite symbols: gather nearby complete components, not long pipes
            # that merely pass through the example's bounding area.
            anchor = max(paths,key=lambda p:_span(bounds([p])))
            anchor_span = _span(bounds([anchor]))
            if not anchor_span:
                continue
            if _component_error(anchor,points)>.10:
                continue
            radius = span/anchor_span*_span(reference['bounds'])*1.25
            cx,cy = ((record['bounds'][0]+record['bounds'][2])/2,(record['bounds'][1]+record['bounds'][3])/2)
            nearby = []
            for other in tree.query(shape_box(cx-radius,cy-radius,cx+radius,cy+radius)):
                other = int(other); b = records[other]['bounds']
                if b[0]>=cx-radius and b[2]<=cx+radius and b[1]>=cy-radius and b[3]<=cy+radius:
                    nearby.append(other)
            if not 2<=len(nearby)<=MAX_SAMPLE_PARTS:
                continue
            candidate_paths = [records[i]['points'] for i in nearby]
            error = shape_error(paths,candidate_paths)
            if error<=MATCH_ERROR:
                proposal(nearby,template,error,_inside_labels(bounds(candidate_paths),labels))
    result, used = [],set()
    for item in sorted(found,key=lambda v:(-v['confidence'],-bool(v['text']),v['id'])):
        keys = {(ref['layer'],ref['index']) for ref in item['source_refs']}
        if not keys.intersection(used):
            result.append(item);used.update(keys)
        if len(result)>=MAX_CANDIDATES:
            break
    return sorted(result,key=lambda v:v['id'])


def review_selections(candidates, specs, valid_types):
    if specs is None:specs={}
    if not isinstance(specs,dict):raise ValueError('多段线设备映射无效')
    lookup={item['id']:item for item in candidates}
    selected=[];used=set()
    for key,spec in specs.items():
        if not isinstance(spec,dict) or type(spec.get('include',False)) is not bool:
            raise ValueError('多段线设备映射无效')
        if not spec.get('include'):continue
        if key not in lookup:raise ValueError('识别结果已变化，请刷新并重新核对设备')
        if spec.get('valve_type') not in valid_types:
            raise ValueError('请为选中的多段线阀门选择设备类型')
        item=dict(lookup[key],valve_type=spec['valve_type'])
        refs={(ref['layer'],ref['index']) for ref in item['source_refs']}
        if refs.intersection(used):raise ValueError('同一图形不能重复导入为多个设备')
        used.update(refs);selected.append(item)
    return selected


def pipe_geometry(layers, layer_specs, selected):
    """Remove only reviewed glyphs and bridge a clear two-port gap in the same layer."""
    from shapely.geometry import LineString, Point
    removed={(ref['layer'],ref['index']) for item in selected for ref in item['source_refs']}
    result={name:[path for index,path in enumerate(bucket['polys']) if (name,index) not in removed]
            for name,bucket in layers.items()}
    for item in selected:
        center=(item['x'],item['y']);span=_span(item['bounds'])
        glyph=LineString([p for ref in item['source_refs'] for p in layers[ref['layer']]['polys'][ref['index']]])
        ports=[];through=False
        for layer,paths in result.items():
            if layer.startswith(('块·',SYMBOL_PREFIX)) or not layer_specs.get(layer,{}).get('include'):continue
            for path in paths:
                line=LineString(path)
                if line.distance(Point(center))<span*.05:
                    through=True;break
                for endpoint,neighbor in ((path[0],path[1]),(path[-1],path[-2])):
                    distance=math.dist(endpoint,center)
                    if distance<=span*.85 and math.dist(neighbor,center)>distance and glyph.distance(Point(endpoint))<=span*.12:
                        if not any(math.dist(endpoint,p['point'])<span*.03 for p in ports):
                            ports.append({'layer':layer,'point':list(endpoint)})
            if through:break
        item['connection']='through' if through else 'nearby'
        if not through and len(ports)==2 and ports[0]['layer']==ports[1]['layer']:
            a,b=ports[0]['point'],ports[1]['point']
            dot=(a[0]-center[0])*(b[0]-center[0])+(a[1]-center[1])*(b[1]-center[1])
            if dot<=.25*math.dist(a,center)*math.dist(b,center):
                bridge={'layer':ports[0]['layer'],'points':[a,list(center),b]}
                result[bridge['layer']].append(bridge['points']);item['bridge']=bridge;item['connection']='bridge'
    return result


def load_templates():
    from .models import DxfValveShapeTemplate
    return [dict(row.definition,id=str(row.pk)) for row in DxfValveShapeTemplate.objects.filter(active=True).order_by('pk')]
