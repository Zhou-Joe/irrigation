# -*- coding: utf-8 -*-
"""Weekly team report generator — server-side port of the weekly-report skill.

One entry point: ``build_weekly_report(d0, d1, out_dir)`` runs the whole
deterministic pipeline in-process (ORM data -> photo pick/crop -> matplotlib
charts -> template-clone docx) and returns a summary dict whose ``file`` entry
matches the SSE file-event schema used by core.ai_views.

Format invariants mirror the skill exactly (template clone, numId=1/49 bullets,
ListParagraph, keepNext section heads, 1371600x1828800 EMU photo tiles with
space runs, charts 5900000 EMU wide, jpg Content-Types default, photo rels
from rId103). Do NOT "simplify" the XML recipes — they reproduce the official
Weekly Report template byte-for-byte in structure.
"""
from core.ai_storage import artifact_url
import json
import os
import re
import shutil
import zipfile
from collections import Counter, defaultdict
from datetime import date, timedelta

from django.conf import settings
from django.db.models import Count, Sum

TEMPLATE = os.path.join(os.path.dirname(__file__), 'assets', 'weekly_report_template.docx')

# Photo groups: keyword -> work-item name_zh fragments (order matters: earlier
# groups claim shared photos first; global dedup across groups).
GROUPS = {
    'nozzle': ['黑弯头断', '弯头断在三通里', '喷头盖掉/松/坏', '喷嘴无机物堵', '喷嘴螺蛳苗堵',
               '壳体裂/掉', '喷嘴丢/坏', '喷芯掉或坏', '喷头断/掉', '堵/调喷嘴/取消喷头',
               '恢复锁闭的喷嘴', '高度', '加高', '降低', '移位', '定位'],
    'drip': ['滴灌无水/漏水'],
    'valve': ['电磁阀及阀箱', '保险丝烧', '可控硅坏/异常输出', '绝缘接地测试', '测试绝缘', '测试通断', '取水阀'],
    'project': ['灌溉项目', '安装', '喷嘴安装', '管道冲洗', '材料准备', '材料分类', '接头标记'],
    'inspect': ['维保定期检查', '计划性维修', '功能正常', '该浇没浇'],
}
GROUP_ORDER = ['nozzle', 'drip', 'valve', 'project', 'inspect']
GROUP_LEAD = {
    'nozzle': 'Sprinkler & nozzle repairs',
    'drip': 'Drip irrigation repairs',
    'valve': 'Valve & electrical repairs',
    'project': 'Irrigation projects & installation',
    'inspect': 'Inspections & planned maintenance',
}
PER_GROUP, PM_N = 6, 9

ITEM_EN = {
    '黑弯头断': 'broken black elbows', '弯头断在三通里': 'elbows snapped inside tees',
    '喷嘴无机物堵': 'nozzles clogged by debris', '喷嘴螺蛳苗堵': 'nozzles clogged by snails/seedlings',
    '喷头盖掉/松/坏': 'loose or damaged sprinkler caps', '壳体裂/掉': 'cracked or detached housings',
    '喷嘴丢/坏': 'missing or damaged nozzles', '喷芯掉或坏': 'broken spray cores',
    '喷头断/掉': 'broken or popped sprinklers', '堵/调喷嘴/取消喷头': 'nozzle cleaning/adjustment & removals',
    '恢复锁闭的喷嘴': 'restored shut-off nozzles', '高度': 'height corrections',
    '加高': 'riser extensions', '降低': 'sprinkler lowering',
    '移位': 'relocations', '定位': 're-alignment',
    '滴灌无水/漏水': 'drip-line no-water/leak faults',
    '电磁阀及阀箱': 'solenoid valves & valve boxes', '保险丝烧': 'blown fuses',
    '可控硅坏/异常输出': 'failed TRIAC outputs', '绝缘接地测试': 'insulation & grounding tests',
    '测试绝缘': 'insulation tests', '测试通断': 'continuity tests', '取水阀': 'water take-off valves',
    '维保定期检查': 'scheduled maintenance inspections', '计划性维修': 'planned repairs',
    '功能正常': 'function-verified checks', '该浇没浇': 'missed-watering checks',
    '灌溉项目': 'project tasks', '安装': 'installations', '喷嘴安装': 'nozzle installations',
    '管道冲洗': 'pipeline flushing', '材料准备': 'material preparation',
    '材料分类': 'material sorting', '接头标记': 'fitting tagging',
}
JOBPLAN_EN = {
    '喷头水检重点区域': 'sprinkler water-check (key areas)',
    '喷头水检一般位置': 'sprinkler water-check (general areas)',
    '喷头水检次要位置': 'sprinkler water-check (secondary areas)',
    '喷头目检重点区域': 'sprinkler visual-check (key areas)',
    '喷头目检一般位置': 'sprinkler visual-check (general areas)',
    '喷头目检次要位置': 'sprinkler visual-check (secondary areas)',
    '超级重点区目检': 'super-key-area visual inspection',
    '超级重点区水检': 'super-key-area water-check',
    '电动主阀检查': 'electric main-valve checks',
    'POC滤网清洗': 'POC strainer cleaning',
    '隔离阀开关检查': 'isolation-valve operation checks',
    '主阀检查': 'main-valve checks',
}

# matplotlib has no CJK glyphs in the default font -> chart labels must be EN.
ZONE_EN = {
    '梦幻世界': 'Fantasyland', '明日世界': 'Tomorrowland', '宝藏湾': 'Treasure Cove',
    '奇想花园': 'Gardens of Imagination', '主入口': 'Main Entrance', '城堡': 'Castle',
    '矮人矿山': 'Seven Dwarfs Mine', '西游客停车场': 'West Guest Parking',
    '小飞象': 'Dumbo', '小勇者营地': 'Campground', '漂流': 'Roaring Rapids',
    '晶彩奇航': 'Voyage', '林间剧场': 'Forest Theatre', '动物城': 'Zootopia',
    '烟花区': 'Fireworks Area', '迷宫': 'Maze', '苗圃乔木': 'Nursery Trees',
    '西大湖': 'West Lake', '南大湖': 'South Lake', '北门': 'North Gate',
    '北泵站': 'North Pump Station', '探索路': 'Explorer Path', '奇妙路': 'Wonder Road',
    '神奇路': 'Magic Road', '申迪北路': 'Shendi North Rd', '申迪南路': 'Shendi South Rd',
    '申迪西路': 'Shendi West Rd', '宝藏湾大草坪': 'Treasure Cove Lawn',
    '后场宝藏湾路边': 'Backstage (Treasure Cove)', '后场606A': 'Backstage 606A',
}
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def _zone_en(z):
    z = (z or '').strip()
    if not z:
        return None
    if z in ('TD', 'BOH'):
        return z
    if z in ZONE_EN:
        return ZONE_EN[z]
    for pref, en in [('酒店', 'Hotel'), ('后场', 'Backstage'), ('巡游道', 'Parade Route'),
                     ('花园', 'Garden'), ('宝藏湾', 'Treasure Cove'), ('明日世界', 'Tomorrowland')]:
        if z.startswith(pref):
            return en
    return None  # unmapped zones stay out of the EN chart


def last_full_week(today=None):
    """(monday, sunday) of the previous complete Mon-Sun week."""
    today = today or date.today()
    this_mon = today - timedelta(days=today.weekday())
    return this_mon - timedelta(days=7), this_mon - timedelta(days=1)


def _irr_day(ts):
    """Local irrigation day for a compact UTC runtime timestamp."""
    from core.irrig_time import irrigation_day_for_utc
    try:
        return irrigation_day_for_utc(ts)
    except ValueError:
        return None


# ── 1. data ───────────────────────────────────────────────────────────────

def _week_data(d0, d1):
    from core.models import (WorkReport, WorkReportEntry, GeneratedWorkOrder,
                             MaxicomRuntime, MaxicomFlowDaily, WeatherData)
    d = {'d0': d0, 'd1': d1}
    wr = WorkReport.objects.filter(date__gte=d0, date__lte=d1)
    agg = wr.aggregate(n=Count('id'), th=Sum('team_hours'), tph=Sum('third_party_hours'))
    d['reports'] = agg['n'] or 0
    d['team_hours'] = agg['th'] or 0
    d['third_hours'] = agg['tph'] or 0

    entries = WorkReportEntry.objects.filter(work_report__date__gte=d0, work_report__date__lte=d1)
    d['entries'] = entries.count()
    sec = Counter()
    for r in entries.values('work_item__section').annotate(c=Count('id')):
        if r['work_item__section']:
            sec[r['work_item__section']] = r['c']
    d['sec'] = sec
    item_c = Counter()
    for r in entries.values('work_item__name_zh').annotate(c=Count('id')):
        if r['work_item__name_zh']:
            item_c[r['work_item__name_zh']] = r['c']
    d['item_counts'] = item_c

    zone_c = Counter()
    for r in wr.exclude(zone_names='').values_list('zone_names', flat=True):
        for z in (p.strip() for p in (r or '').split(',')):
            if z:
                zone_c[z] += 1
    d['zone_counts'] = zone_c

    d['workers'] = wr.values('worker').distinct().count()

    gwo = GeneratedWorkOrder.objects.filter(scheduled_date__gte=d0, scheduled_date__lte=d1)
    d['pm'] = {r['status']: r['c'] for r in gwo.values('status').annotate(c=Count('id'))}
    pm_done = []
    for g in gwo.filter(status='completed').select_related('plan__job_plan', 'crew').order_by('scheduled_date'):
        pm_done.append((g.plan.job_plan.name, str(g.crew) if g.crew_id else '', g.scheduled_date))
    d['pm_done'] = pm_done

    # runtime per irrigation day
    from core.irrig_time import irrigation_day_utc_bounds
    f14, t14 = irrigation_day_utc_bounds(d0, d1)
    day_min = Counter()
    sites = set()
    runs = 0
    for ts, sid, rt in MaxicomRuntime.objects.filter(
            timestamp__gte=f14, timestamp__lte=t14).values_list('timestamp', 'site_id', 'run_time'):
        k = _irr_day(ts)
        if k is None:
            continue
        day_min[k] += (rt or 0)
        runs += 1
        sites.add(sid)
    d['day_min'] = day_min
    d['runs'] = runs
    d['sites'] = len(sites)

    # flow per irrigation day (flow_day is a YYYYMMDD string)
    day_lit = Counter()
    for fd, lit in MaxicomFlowDaily.objects.filter(
            flow_day__gte=d0.strftime('%Y%m%d'), flow_day__lte=d1.strftime('%Y%m%d')
    ).values_list('flow_day', 'liters'):
        try:
            day_lit[date(int(fd[:4]), int(fd[4:6]), int(fd[6:8]))] += (lit or 0)
        except ValueError:
            pass
    d['day_lit'] = day_lit
    d['flow_max_day'] = max(day_lit) if day_lit else None

    # weather
    wx = {}
    for w in WeatherData.objects.filter(date__gte=d0, date__lte=d1):
        hourly = w.hourly_data or []
        temps = [h.get('temp') for h in hourly if h.get('temp') is not None]
        if temps:
            wx[w.date] = (min(temps), max(temps), round(sum((h.get('precip') or 0) for h in hourly), 1))
    d['wx'] = wx
    return d


# ── 2. photos ─────────────────────────────────────────────────────────────

def _parse_photos(ph):
    if isinstance(ph, str):
        try:
            v = json.loads(ph)
            return v if isinstance(v, list) else []
        except Exception:
            return []
    return ph or []


def _pick_photos(d0, d1):
    """{group: [abs paths]} — global dedup, 6/group (PM 9), trimmed to a
    multiple of 3 so every photo grid stays rectangular."""
    from core.models import WorkReport, GeneratedWorkOrder
    media = settings.MEDIA_ROOT
    picked, used = defaultdict(list), set()
    reports = list(WorkReport.objects.filter(date__gte=d0, date__lte=d1)
                   .exclude(photos__in=[None, '[]', '']).order_by('-date')
                   .select_related('worker')
                   .prefetch_related('entries__work_item'))
    for g in GROUP_ORDER:
        for r in reports:
            if len(picked[g]) >= PER_GROUP:
                break
            items = [e.work_item.name_zh for e in r.entries.all() if e.work_item_id]
            hits = [it for it in items if any(kw in (it or '') for kw in GROUPS[g])]
            if not hits:
                continue
            meta = {'date': r.date.isoformat(),
                    'worker': r.worker.full_name if r.worker_id else '',
                    'zones': (r.zone_names or '')[:60],
                    'items': hits[:3]}
            for p in _parse_photos(r.photos):
                full = os.path.join(media, str(p).lstrip('/'))
                if os.path.exists(full) and full not in used and len(picked[g]) < PER_GROUP:
                    used.add(full)
                    picked[g].append({'path': full, 'meta': meta})
    pm = []
    for gr in GeneratedWorkOrder.objects.filter(scheduled_date__gte=d0, scheduled_date__lte=d1,
                                                status='completed').select_related('plan__job_plan', 'crew'):
        po = getattr(gr, 'pm_order', None)
        if not po:
            continue
        meta = {'date': gr.scheduled_date.isoformat(),
                'worker': po.worker.full_name if po.worker_id else '',
                'zones': (po.zone_names or '')[:60],
                'items': [gr.plan.job_plan.name]}
        for p in _parse_photos(po.photos):
            full = os.path.join(media, str(p).lstrip('/'))
            if os.path.exists(full) and full not in used and len(pm) < PM_N:
                used.add(full)
                pm.append({'path': full, 'meta': meta})

    def trim3(lst):
        return lst[:len(lst) - (len(lst) % 3)] if len(lst) >= 3 else []
    out = {g: trim3(picked[g]) for g in GROUP_ORDER}
    out['pm'] = trim3(pm)
    return out


# ── 3. resize ─────────────────────────────────────────────────────────────

def _resize(groups, workdir):
    from PIL import Image, ImageOps
    out = os.path.join(workdir, 'pics')
    os.makedirs(out, exist_ok=True)
    man = {}
    for g, lst in groups.items():
        man[g] = []
        for i, rec in enumerate(lst):
            src = rec['path'] if isinstance(rec, dict) else rec
            try:
                im = Image.open(src)
                im = ImageOps.exif_transpose(im).convert('RGB')
                target = 3.0 / 4.0
                w, h = im.size
                if w / h > target:
                    nw = int(h * target)
                    x0 = (w - nw) // 2
                    im = im.crop((x0, 0, x0 + nw, h))
                elif w / h < target:
                    nh = int(w / target)
                    y0 = (h - nh) // 2
                    im = im.crop((0, y0, w, y0 + nh))
                w, h = im.size
                scale = min(900.0 / w, 1200.0 / h, 1.0)
                im = im.resize((int(w * scale), int(h * scale)))
                dst = os.path.join(out, '%s_%d.jpg' % (g, i + 1))
                im.save(dst, 'JPEG', quality=80)
                man[g].append({'id': '%s_%d' % (g, i + 1), 'file': dst,
                               'w': im.size[0], 'h': im.size[1],
                               'meta': rec.get('meta', {}) if isinstance(rec, dict) else {}})
            except Exception:
                continue
    return man


# ── 4. charts ─────────────────────────────────────────────────────────────

def _charts(D, workdir):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    from PIL import Image

    days_idx = sorted(set(D['day_min']) | set(D['day_lit']) | set(D['wx']))
    days = ['%s %d' % (MONTHS[k.month - 1], k.day) for k in days_idx]
    flow_m3 = [round(D['day_lit'].get(k, 0) / 1000.0, 1) for k in days_idx]
    runtime_h = [round(D['day_min'].get(k, 0) / 60.0, 1) for k in days_idx]
    tmin = [D['wx'].get(k, (None,))[0] for k in days_idx]
    tmax = [D['wx'].get(k, (None, None))[1] for k in days_idx]
    prcp = [D['wx'].get(k, (0, 0, 0))[2] for k in days_idx]

    C_BAR, C_LINE, C_RAIN = '#8CA6B8', '#C0896E', '#6E93B5'
    plt.rcParams.update({'font.size': 9, 'axes.edgecolor': '#999999', 'axes.linewidth': 0.8,
                         'axes.spines.top': False, 'axes.spines.right': False})

    def save(fig, name):
        fig.savefig(os.path.join(workdir, name))
        plt.close(fig)

    tot_flow = sum(flow_m3)
    tot_min = sum(D['day_min'].values())
    t1 = ('Irrigation Water Use & Station Runtime (%s %d-%d, %d) | week total %s m3 / %s station-min'
          % (MONTHS[D['d0'].month - 1], D['d0'].day, D['d1'].day, D['d1'].year,
             '{:,.0f}'.format(tot_flow), '{:,}'.format(tot_min)))
    fig, ax1 = plt.subplots(figsize=(8.3, 2.0), dpi=200)
    ax1.bar(days, flow_m3, color=C_BAR, width=0.62)
    ax1.set_ylabel('m3', color='#5B7285')
    ax1.set_ylim(0, (max(flow_m3) or 1) * 1.15)
    ax2 = ax1.twinx()
    ax2.spines['right'].set_visible(True)
    ax2.plot(days, runtime_h, color=C_LINE, marker='o', lw=1.6, ms=4)
    ax2.set_ylabel('hours', color=C_LINE)
    ax2.set_ylim(0, (max(runtime_h) or 1) * 1.25)
    ax1.set_title(t1, fontsize=10, loc='left', pad=8)
    fig.tight_layout()
    save(fig, 'chart1.png')

    rain_tot = sum(prcp)
    rain_days = sum(1 for p in prcp if p > 0)
    t2 = ('Weather (Open-Meteo, 31.15N 121.67E) | %s'
          % (('rain %.1f mm on %d day(s)' % (rain_tot, rain_days)) if rain_tot else 'no rain this week'))
    fig, ax = plt.subplots(figsize=(8.3, 2.35), dpi=200)
    if any(v is not None for v in tmax):
        tt = [v if v is not None else 0 for v in tmax]
        tb = [v if v is not None else 0 for v in tmin]
        ax.plot(days, tt, color=C_LINE, marker='o', lw=1.6, ms=4)
        ax.plot(days, tb, color=C_BAR, marker='s', lw=1.6, ms=4)
        ax.fill_between(days, tb, tt, color=C_BAR, alpha=0.18)
        ax.set_ylim(min(tb) - 5, max(tt) + 4)
    ax.set_ylabel('deg C')
    axr = ax.twinx()
    axr.spines['right'].set_visible(True)
    axr.bar(days, prcp, color=C_RAIN, width=0.5, alpha=0.85)
    axr.set_ylabel('rain mm', color=C_RAIN)
    axr.set_ylim(0, max(max(prcp) * 4 if prcp else 0, 20))
    ax.set_title(t2, fontsize=10, loc='left', pad=8)
    fig.tight_layout()
    save(fig, 'chart2.png')

    zc = Counter()
    for zh, n in D['zone_counts'].items():
        en = _zone_en(zh)
        if en:
            zc[en] += n
    zones = [z for z, _ in zc.most_common(8)]
    counts = [zc[z] for z in zones]
    t3 = ('Work-order entries by zone (%d reports / %d entries; routine %d, project %d, warehouse %d)'
          % (D['reports'], D['entries'], D['sec'].get('routine_maint', 0),
             D['sec'].get('irrigation_project', 0), D['sec'].get('warehouse', 0)))
    fig, ax = plt.subplots(figsize=(8.3, 2.35), dpi=200)
    y = np.arange(len(zones))[::-1]
    ax.barh(y, counts, color=C_BAR, height=0.62)
    ax.set_yticks(y)
    ax.set_yticklabels(zones, fontsize=8.5)
    for yi, v in zip(y, counts):
        ax.text(v + 0.3, yi, str(v), va='center', fontsize=8.5, color='#555555')
    ax.set_xlim(0, (max(counts) or 1) * 1.15)
    ax.set_title(t3, fontsize=10, loc='left', pad=8)
    ax.spines['left'].set_visible(False)
    ax.tick_params(axis='y', length=0)
    fig.tight_layout()
    save(fig, 'chart3.png')

    man = {}
    for n in ['chart1', 'chart2', 'chart3']:
        w, h = Image.open(os.path.join(workdir, n + '.png')).size
        man[n] = {'file': n + '.png', 'w': w, 'h': h}
    return man


# ── 5. content blocks ─────────────────────────────────────────────────────

def _fmt_dayspan(D):
    a, b = D['d0'], D['d1']
    if a.month == b.month:
        return '%s %d – %d' % (MONTHS[a.month - 1], a.day, b.day)
    return '%s %d – %s %d' % (MONTHS[a.month - 1], a.day, MONTHS[b.month - 1], b.day)


def _group_text(D, g):
    """English past-tense summary of the week's entries inside one photo group."""
    hits = []
    for name, cnt in D['item_counts'].most_common():
        if any(kw in (name or '') for kw in GROUPS[g]):
            hits.append((cnt, name))
    total = sum(c for c, _ in hits)
    parts = ['%d %s' % (c, ITEM_EN.get(n, n)) for c, n in sorted(hits, reverse=True)[:5]]
    body = '; '.join(parts) if parts else 'see work-order entries for details'
    return total, body


def _content(D, man):
    blocks = [
        {'type': 'section', 'text': 'IRRIGATION&WEATHER DATA'},
        {'type': 'chart', 'key': 'chart1'},
        {'type': 'chart', 'key': 'chart2'},
    ]
    tot_flow = sum(D['day_lit'].values()) / 1000.0
    flows = [v for v in D['day_lit'].values() if v]
    rains = [(k, v[2]) for k, v in D['wx'].items() if v[2] > 0]
    temps = [(v[0], v[1]) for v in D['wx'].values()]
    wx_s = ''
    if temps:
        wx_s = 'weather %.1f–%.1f °C, %s' % (
            min(t[0] for t in temps), max(t[1] for t in temps),
            ('rain %s mm on %s' % (round(sum(r[1] for r in rains), 1),
                                   ', '.join('%s %d' % (MONTHS[k.month - 1], k.day) for k, _ in rains)))
            if rains else 'no rain')
    blocks.append({'type': 'item', 'lead': 'Weekly irrigation: ', 'text':
                   '%s m³ total water use (daily %s–%s m³); %s station-run minutes across %s runs at %s sites; %d work reports logged (%.1f team hours + %.1f third-party hours, %d workers).%s'
                   % ('{:,.0f}'.format(tot_flow),
                      '{:,.0f}'.format(min(flows) / 1000.0) if flows else '0',
                      '{:,.0f}'.format(max(flows) / 1000.0) if flows else '0',
                      '{:,}'.format(sum(D['day_min'].values())), '{:,}'.format(D['runs']),
                      D['sites'], D['reports'], D['team_hours'], D['third_hours'], D['workers'],
                      (' ' + wx_s + '.') if wx_s else '')})

    blocks.append({'type': 'section', 'text': 'Non-Plan Maintenance'})
    for g in GROUP_ORDER:
        total, body = _group_text(D, g)
        if total == 0 and not man.get(g):
            continue
        blocks.append({'type': 'item', 'lead': GROUP_LEAD[g] + ': ',
                       'text': '%d cases in total — %s.' % (total, body)})
        if man.get(g):
            blocks.append({'type': 'photos', 'group': g})
    blocks.append({'type': 'chart', 'key': 'chart3'})

    blocks.append({'type': 'section', 'text': 'Plan Maintenance (PM)'})
    pm = D['pm']
    blocks.append({'type': 'item', 'lead': 'PM dispatch: ', 'text':
                   '%d work orders scheduled this week — %d completed, %d dispatched, %d overdue, %d skipped.'
                   % (sum(pm.values()), pm.get('completed', 0), pm.get('dispatched', 0),
                      pm.get('overdue', 0), pm.get('skipped', 0))})
    if D['pm_done']:
        jp = Counter(JOBPLAN_EN.get(name, name) for name, _, _ in D['pm_done'])
        blocks.append({'type': 'item', 'lead': 'Completed PM: ', 'text':
                       '; '.join('%d x %s' % (c, n) for n, c in jp.most_common(6)) + '.'})
    if man.get('pm'):
        blocks.append({'type': 'photos', 'group': 'pm'})

    return {'dateRange': '(%d %s %d – %s %d)' % (D['d0'].year, MONTHS[D['d0'].month - 1], D['d0'].day,
                                                 MONTHS[D['d1'].month - 1], D['d1'].day),
            'blocks': blocks}


# ── 6. docx assembly (template clone) ─────────────────────────────────────

def _build(C, CH, MAN, workdir, out_path):
    WORK = os.path.join(workdir, '_docx_work')
    if os.path.exists(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)
    zipfile.ZipFile(TEMPLATE).extractall(WORK)

    media = os.path.join(WORK, 'word', 'media')
    for f in os.listdir(media):
        os.remove(os.path.join(media, f))
    IMG = {}
    for key, rec in CH.items():
        name = {'chart1': 'image1.png', 'chart2': 'image2.png', 'chart3': 'image3.png'}[key]
        shutil.copy(os.path.join(workdir, rec['file']), os.path.join(media, name))
        cx = 5900000
        IMG[key] = (name, cx, int(cx * rec['h'] / rec['w']))
    MAXW, MAXH = 1371600, 1828800
    GROUP_KEYS, ID2KEY, n = {}, {}, 4
    for g, lst in MAN.items():
        GROUP_KEYS[g] = []
        for rec in lst:
            name = 'image%d.jpg' % n
            shutil.copy(rec['file'], os.path.join(media, name))
            IMG['p%d' % n] = (name, MAXW, MAXH)
            GROUP_KEYS[g].append('p%d' % n)
            if rec.get('id'):
                ID2KEY[rec['id']] = 'p%d' % n
            n += 1
    NPHOTO = n

    ctp = os.path.join(WORK, '[Content_Types].xml')
    ct = open(ctp, encoding='utf-8').read()
    if 'Extension="jpg"' not in ct:
        ct = ct.replace('<Default Extension="png"',
                        '<Default Extension="jpg" ContentType="image/jpeg"/><Default Extension="png"')
        open(ctp, 'w', encoding='utf-8').write(ct)

    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" Target="../customXml/item1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>'
            '<Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/webSettings" Target="webSettings.xml"/>'
            '<Relationship Id="rId6" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/>'
            '<Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes" Target="endnotes.xml"/>'
            '<Relationship Id="rId38" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>'
            '<Relationship Id="rId39" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
            '<Relationship Id="rId40" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable" Target="fontTable.xml"/>'
            '<Relationship Id="rId41" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>'
            '<Relationship Id="rId100" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>'
            '<Relationship Id="rId101" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image2.png"/>'
            '<Relationship Id="rId102" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image3.png"/>')
    for i in range(4, NPHOTO):
        rels += ('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image%d.jpg"/>'
                 % (102 + i - 3, i))
    rels += '</Relationships>'
    open(os.path.join(WORK, 'word', '_rels', 'document.xml.rels'), 'w', encoding='utf-8').write(rels)

    hp = os.path.join(WORK, 'word', 'header1.xml')
    hdr = open(hp, encoding='utf-8').read()
    date_p = ('<w:p><w:pPr><w:pStyle w:val="Header"/><w:ind w:right="440"/>'
              '<w:rPr><w:rFonts w:cs="Andalus"/><w:b/><w:color w:val="000000"/><w:sz w:val="32"/><w:szCs w:val="44"/></w:rPr></w:pPr>'
              '<w:r><w:rPr><w:rFonts w:cs="Andalus"/><w:b/><w:color w:val="000000"/><w:sz w:val="32"/><w:szCs w:val="44"/></w:rPr>'
              '<w:t xml:space="preserve">                    %s</w:t></w:r></w:p>' % C['dateRange'])
    hdr, k = re.subn(r'<w:p [^>]*><w:pPr><w:pStyle w:val="Header"/></w:pPr></w:p>', date_p, hdr, count=1)
    if k == 0:
        hdr = hdr.replace('</w:hdr>', date_p + '</w:hdr>')
    open(hp, 'w', encoding='utf-8').write(hdr)

    orig = open(os.path.join(WORK, 'word', 'document.xml'), encoding='utf-8').read()
    di = orig.index('<w:document')
    root_open = orig[di:orig.index('>', di) + 1]
    sect = re.search(r'<w:sectPr.*?</w:sectPr>', orig, re.S).group(0)

    def esc(t):
        return t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    def run(text, bold=False):
        rpr = ('<w:rPr><w:b/><w:color w:val="000000"/></w:rPr>' if bold
               else '<w:rPr><w:color w:val="000000"/></w:rPr>')
        return '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, esc(text))

    def drawing(rid, did, cx, cy, name):
        return ('<w:r><w:rPr><w:noProof/></w:rPr><w:drawing>'
                '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" distT="0" distB="0" distL="0" distR="0"><wp:extent cx="%d" cy="%d"/>'
                '<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:docPr id="%d" name="%s"/>'
                '<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/></wp:cNvGraphicFramePr>'
                '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                '<pic:nvPicPr><pic:cNvPr id="%d" name="%s"/><pic:cNvPicPr/></pic:nvPicPr>'
                '<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
                '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
                '</wp:inline></w:drawing></w:r>') % (cx, cy, did, name, did, name, rid, cx, cy)

    def img_para(key):
        name, cx, cy = IMG[key]
        num = int(name[5:-4])
        rid = 'rId%d' % (99 + num)
        return ('<w:p><w:pPr><w:pStyle w:val="ListParagraph"/></w:pPr>'
                + drawing(rid, 100 + num, cx, cy, name) + '</w:p>')

    def photo_para(keys):
        runs = ''
        for i, k in enumerate(keys):
            name, cx, cy = IMG[k]
            num = int(k[1:])
            if i:
                runs += '<w:r><w:t xml:space="preserve"> </w:t></w:r>'
            runs += drawing('rId%d' % (102 + num - 3), 200 + num, cx, cy, name)
        return '<w:p><w:pPr><w:pStyle w:val="ListParagraph"/></w:pPr>' + runs + '</w:p>'

    body = ['<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>'
            + run('Irrigation Management', bold=True) + '</w:p>']
    placed = set()
    for b in C['blocks']:
        t = b['type']
        if t == 'section':
            body.append('<w:p><w:pPr><w:pStyle w:val="ListParagraph"/><w:keepNext/>'
                        '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="49"/></w:numPr></w:pPr>'
                        + run(b['text'], bold=True) + '</w:p>')
        elif t == 'item':
            body.append('<w:p><w:pPr><w:pStyle w:val="ListParagraph"/></w:pPr>'
                        + run(b['lead'], bold=True) + run(b['text']) + '</w:p>')
        elif t == 'chart':
            body.append(img_para(b['key']))
        elif t == 'photos':
            keys = ([ID2KEY[i] for i in b['ids'] if i in ID2KEY] if b.get('ids')
                    else GROUP_KEYS.get(b.get('group'), []))
            keys = [k for k in keys if k not in placed]
            if keys:
                placed.update(keys)
                body.append(photo_para(keys))
        else:
            raise ValueError('unknown block type: %s' % t)

    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + root_open
           + '<w:body>' + ''.join(body) + sect + '</w:body></w:document>')
    open(os.path.join(WORK, 'word', 'document.xml'), 'w', encoding='utf-8').write(doc)

    if os.path.exists(out_path):
        os.remove(out_path)
    zf = zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED)
    names = ['[Content_Types].xml']
    for root, dirs, files in os.walk(WORK):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), WORK).replace('\\', '/')
            if rel not in names:
                names.append(rel)
    for rel in names:
        zf.write(os.path.join(WORK, rel.replace('/', os.sep)), rel)
    zf.close()
    shutil.rmtree(WORK)
    # intermediates (charts + cropped pics) stay out of the AI workspace
    for n in ('chart1.png', 'chart2.png', 'chart3.png'):
        try:
            os.remove(os.path.join(workdir, n))
        except OSError:
            pass
    shutil.rmtree(os.path.join(workdir, 'pics'), ignore_errors=True)
    return os.path.getsize(out_path)


# ── entry point ───────────────────────────────────────────────────────────

def build_weekly_report(d0, d1, out_dir):
    """Run the full pipeline; returns the SSE file-event dict + stats."""
    os.makedirs(out_dir, exist_ok=True)
    D = _week_data(d0, d1)
    if D['reports'] == 0 and sum(D['day_min'].values()) == 0:
        return {'error': '该周期没有任何工单或灌溉运行数据，无法生成周报'}
    groups = _pick_photos(d0, d1)
    man = _resize(groups, out_dir)
    charts = _charts(D, out_dir)
    content = _content(D, man)
    fname = 'Weekly+Report-%s-%s.docx' % (d0.strftime('%m%d'), d1.strftime('%m%d'))
    out_path = os.path.join(out_dir, fname)
    size = _build(content, charts, man, out_dir, out_path)

    warnings = []
    if D['flow_max_day'] and D['d1'] > D['flow_max_day']:
        warnings.append('浇水量数据只到 %s（Maxicom 导入滞后），周期末几天流量可能偏小' % D['flow_max_day'])
    return {
        'file': {'name': fname, 'size': size,
                 'url': artifact_url(os.path.basename(out_dir.rstrip('/')), fname)},
        'period': [d0.isoformat(), d1.isoformat()],
        'stats': {
            '工单数': D['reports'], '灌溉组工时': D['team_hours'], '第三方工时': D['third_hours'],
            '运行分钟': sum(D['day_min'].values()), '浇水量m3': round(sum(D['day_lit'].values()) / 1000.0),
            'PM状态': D['pm'],
        },
        'photos': {g: len(v) for g, v in man.items() if v},
        'warnings': warnings,
    }


# ── 7. LLM editorial mode: material digest + build-from-blocks ────────────

_ZONE_CODE_RE = re.compile(r'(?<![\d-])(\d{1,2}-\d{1,2}(?:-\d{1,3})?)(?![\d-])')


def _zone_lookup(codes):
    """code -> 通用名称/上级层级 (boss-readable). Zone codes like 11-3-15 mean
    nothing to management; always resolve to the common name."""
    from core.models import Zone, Satellite
    out = {}
    three = {c for c in codes if c.count('-') == 2}
    two = {c for c in codes if c.count('-') == 1}
    zones = {z.code: z for z in Zone.objects.filter(code__in=three).select_related('patch')}
    sats = {s.code: s for s in Satellite.objects.filter(code__in=two)}
    for c in three:
        z = zones.get(c)
        if z:
            zh = z.name or (str(z.patch) if z.patch_id else '') or c
            out[c] = {'zh': zh, 'en': _zone_en(zh) or zh, 'parent': str(z.patch) if z.patch_id else ''}
        else:
            out[c] = None
    for c in two:
        s = sats.get(c)
        if s:
            zh = s.name or (str(s.patch) if s.patch_id else '') or c
            out[c] = {'zh': zh, 'en': _zone_en(zh) or zh, 'parent': str(s.patch) if s.patch_id else ''}
    # drop unresolvable codes (keep them listed so the LLM knows to avoid them)
    return {k: v for k, v in out.items() if v}


def material_digest(d0, d1):
    """Everything the LLM editor needs to decide report content (compact JSON)."""
    from core.models import WorkReport, WorkReportEntry, Project
    D = _week_data(d0, d1)

    entries = []
    for name, cnt in D['item_counts'].most_common(60):
        sec = ''
        for e in WorkReportEntry.objects.filter(work_item__name_zh=name,
                                                work_report__date__gte=d0,
                                                work_report__date__lte=d1).values('work_item__section')[:1]:
            sec = e['work_item__section'] or ''
        entries.append({'zh': name, 'en': ITEM_EN.get(name, ''), 'count': cnt, 'section': sec})

    sample_texts, seen_t = [], set()
    for e in (WorkReportEntry.objects
              .exclude(text_value='')
              .filter(work_report__date__gte=d0, work_report__date__lte=d1)
              .select_related('work_report', 'work_item')
              .order_by('-work_report__date')[:80]):
        t = (e.text_value or '').strip()
        if t and t not in seen_t:
            seen_t.add(t)
            sample_texts.append({'date': e.work_report.date.isoformat(),
                                 'item': e.work_item.name_zh if e.work_item_id else '',
                                 'text': t[:140]})
        if len(sample_texts) >= 14:
            break

    notable = []
    for r in (WorkReport.objects.filter(date__gte=d0, date__lte=d1)
              .select_related('worker').order_by('-team_hours')[:8]):
        notable.append({'date': r.date.isoformat(),
                        'worker': r.worker.full_name if r.worker_id else '',
                        'zones': (r.zone_names or '')[:120],
                        'hours': r.team_hours or 0,
                        'note': ((r.work_content or r.remark or '').strip())[:140]})

    flags = []
    for r in (WorkReport.objects.filter(date__gte=d0, date__lte=d1)
              .filter(is_difficult=True) | WorkReport.objects.filter(date__gte=d0, date__lte=d1)
              .filter(is_pending_repair=True)).select_related('worker').order_by('-date')[:15]:
        flags.append({'date': r.date.isoformat(), 'worker': r.worker.full_name if r.worker_id else '',
                      'zones': (r.zone_names or '')[:80],
                      'difficult': r.is_difficult, 'pending': r.is_pending_repair,
                      'note': ((r.work_content or r.remark or '').strip())[:140]})

    pm_done = [{'job_plan': name, 'en': JOBPLAN_EN.get(name, name), 'crew': crew,
                'date': d.isoformat()} for name, crew, d in D['pm_done'][:20]]

    proj_touched = sorted({p['project__name'] for p in
                           WorkReportEntry.objects.filter(work_report__date__gte=d0,
                                                          work_report__date__lte=d1)
                           .exclude(project__isnull=True).values('project__name')})
    proj_started = [p.name for p in Project.objects.filter(start_date__gte=d0, start_date__lte=d1)]
    proj_ending = [p.name for p in Project.objects.filter(planned_end_date__gte=d0,
                                                          planned_end_date__lte=d1)]

    zones = [{'zh': z, 'en': _zone_en(z) or '', 'count': n}
             for z, n in D['zone_counts'].most_common(20)]

    # every zone CODE mentioned anywhere this week -> common-name lookup
    blob = ' '.join([z for z in D['zone_counts']]
                    + [t.get('text', '') for t in sample_texts]
                    + [n.get('note', '') + ' ' + n.get('zones', '') for n in notable]
                    + [f.get('note', '') + ' ' + f.get('zones', '') for f in flags])
    codes = set(_ZONE_CODE_RE.findall(blob))
    zone_lookup = _zone_lookup(codes)

    photo_pool = []
    for g, lst in _pick_photos(d0, d1).items():
        for i, rec in enumerate(lst):
            m = rec['meta']
            photo_pool.append({'id': '%s_%d' % (g, i + 1), 'group': g,
                               'date': m.get('date', ''), 'worker': m.get('worker', ''),
                               'zones': m.get('zones', ''), 'items': m.get('items', [])})

    flow_days = {k.isoformat(): v for k, v in D['day_lit'].items()}
    run_days = {k.isoformat(): v for k, v in D['day_min'].items()}
    wx = {k.isoformat(): v for k, v in D['wx'].items()}
    return {
        'period': [d0.isoformat(), d1.isoformat()],
        'stats': {'reports': D['reports'], 'team_hours': D['team_hours'],
                  'third_party_hours': D['third_hours'], 'workers': D['workers'],
                  'entries_total': D['entries'],
                  'sections': dict(D['sec']), 'pm_status': D['pm'],
                  'runtime_minutes_total': sum(D['day_min'].values()),
                  'flow_liters_total': sum(D['day_lit'].values())},
        'daily': {'runtime_min': run_days, 'flow_liters': flow_days, 'weather': wx},
        'work_items': entries,
        'sample_entry_texts': sample_texts,
        'notable_reports': notable,
        'difficult_pending': flags,
        'pm_completed': pm_done,
        'projects': {'touched': proj_touched, 'started': proj_started, 'ending_this_week': proj_ending},
        'zones': zones,
        'photo_pool': photo_pool,
        'photo_note': '每张候选照片带 id/来源(date/worker/zones/items)。照片必须放在它佐证的那个条目正文之下：'
                      '{"type":"photos","ids":["nozzle_1","drip_2","pm_3"]} 按条目精选（数量须为3的倍数，'
                      '同一张不会被重复排版）；或 {"type":"photos","group":"nozzle"} 整组引用。'
                      '挑选依据 = 条目叙述的区域/日期/工作项 与照片 meta 匹配。',
        'zone_lookup': zone_lookup,
        'writing_guide': [
            '读者是老板: 条目 = lead(以": "结尾,渲染加粗) + text(英文/过去式/量化,数字来自本素材),'
            'text 最多两句、直接给结论和数字, 不写过程细节',
            '章节名沿用模板: IRRIGATION&WEATHER DATA / Non-Plan Maintenance / Plan Maintenance (PM);'
            '可自行增加 Highlights / System Upgrade 等章节突出本周特色工作',
            'chart1+chart2 放 IRRIGATION&WEATHER DATA 摘要条目之前; chart3(区域分布)放 Non-Plan 之后',
            '禁止提及班组/crew(组1/组3/crew 1)——老板不关心谁干的, 只关心干了什么; '
            'PM 完成按作业类型汇总计数, 不按班组',
            '区域一律用通用名称或上级名称: 查 zone_lookup(如 11-3-15 -> Tomorrowland); '
            '禁止在正文输出 11-3-15 这类区域编号, 括号注码也不要; 中文物料名用素材 en 映射',
            '先审阅 work_items/sample_entry_texts/notable_reports/difficult_pending,'
            '决定哪些值得单独立条、哪些合并; 有限突出本周特有工作',
            '大多数条目下应附照片: 从 photo_pool 按 meta(区域/日期/工作项) 挑匹配该条目的照片,'
            '用 {"type":"photos","ids":[...]} 紧跟在对应 item 之后(3/6/9张)',
        ],
        'writing_examples': [
            {'good': 'Sprinkler & nozzle repairs: 13 broken black elbows and 5 in-tee elbows '
                     'replaced; 8 clogged nozzles cleaned across Fantasyland and Treasure Cove.'},
            {'good': 'PM execution: 20 work orders completed - 6 electric main-valve checks, '
                     '5 super-key-area inspections and 9 sprinkler water checks; 8 overdue orders '
                     'to be cleared next week.'},
            {'good': 'H1-H3 link restored: the main line between Hotel 1 and Hotel 3 was re-piped '
                     'and commissioned on 16 Oct.'},
            {'bad': 'PM: crews 组1 and 组3 completed 6 electric main-valve checks at zones '
                    '11-3-15, 11-3-16 and 3-2-8 on 13 Oct, with crew 组4 following up...',
             'why': '按班组组织+罗列区域编号+过长, 老板既不关心班组也看不懂编号'},
        ],
    }


def build_with_blocks(d0, d1, blocks, out_dir):
    """Render LLM-authored blocks into the template docx (server validates)."""
    os.makedirs(out_dir, exist_ok=True)
    D = _week_data(d0, d1)
    if D['reports'] == 0 and sum(D['day_min'].values()) == 0:
        return {'error': '该周期没有任何工单或灌溉运行数据，无法生成周报'}
    groups = _pick_photos(d0, d1)
    man = _resize(groups, out_dir)
    charts = _charts(D, out_dir)

    valid, dropped, warnings = [], [], []
    for b in blocks[:100]:
        t = b.get('type')
        if t == 'chart':
            if b.get('key') in charts:
                valid.append({'type': 'chart', 'key': b['key']})
            else:
                dropped.append(str(b))
        elif t == 'photos':
            g, ids = b.get('group'), b.get('ids')
            if ids:
                by_id = {r['id']: g2 for g2, lst in man.items() for r in lst}
                chosen, seen = [], set()
                for pid in ids[:12]:
                    if pid in by_id and pid not in seen:
                        seen.add(pid)
                        chosen.append(pid)
                if len(chosen) % 3:
                    warnings.append('ids %s 非3的倍数，已截取前%d张' % (b.get('ids'), len(chosen) - len(chosen) % 3))
                    chosen = chosen[:len(chosen) - len(chosen) % 3]
                if chosen:
                    valid.append({'type': 'photos', 'ids': chosen})
                else:
                    dropped.append('photos:ids无效')
            elif g in man and man[g]:
                valid.append({'type': 'photos', 'group': g})
            else:
                dropped.append('photos:%s' % g)
        elif t == 'section':
            valid.append({'type': 'section', 'text': str(b.get('text', ''))[:200]})
        elif t == 'item':
            lead = str(b.get('lead', '')).strip()[:200]
            if lead and not lead.endswith((':', '：')):
                lead += ': '
            valid.append({'type': 'item', 'lead': lead,
                          'text': str(b.get('text', ''))[:1500]})
        else:
            dropped.append(str(b)[:80])

    a, b_ = D['d0'], D['d1']
    date_range = ('(%d %s %d – %s %d)' % (a.year, MONTHS[a.month - 1], a.day,
                                          MONTHS[b_.month - 1], b_.day))
    fname = 'Weekly+Report-%s-%s.docx' % (d0.strftime('%m%d'), d1.strftime('%m%d'))
    out_path = os.path.join(out_dir, fname)
    size = _build({'dateRange': date_range, 'blocks': valid}, charts, man, out_dir, out_path)

    if D['flow_max_day'] and D['d1'] > D['flow_max_day']:
        warnings.append('浇水量数据只到 %s（Maxicom 导入滞后）' % D['flow_max_day'])
    if dropped:
        warnings.append('已忽略无效 blocks: %s' % '; '.join(dropped[:5]))
    return {
        'file': {'name': fname, 'size': size,
                 'url': artifact_url(os.path.basename(out_dir.rstrip('/')), fname)},
        'period': [d0.isoformat(), d1.isoformat()],
        'blocks_rendered': len(valid),
        'photos': {g: len(v) for g, v in man.items() if v},
        'warnings': warnings,
    }
