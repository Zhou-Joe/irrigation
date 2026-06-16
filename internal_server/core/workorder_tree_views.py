"""Views for the refactored 现场作业记录 (work order) form.

Server-rendered, mobile-first single-page form driven by the WorkItem
template tree (seeded from 工单记录格式.md). One view handles create + edit:
header fields are written to WorkReport, every filled node becomes a
WorkReportEntry row. See
docs/superpowers/specs/2026-06-16-workorder-form-refactor-design.md.
"""

import json
import os
from datetime import date, datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from core.models import (
    InfoSource, Patch, Project, WorkCategory, Worker, WorkItem,
    WorkReport, WorkReportEntry, Zone,
)


# ── serialization ──────────────────────────────────────────────────────────

def serialize_workitem_tree():
    """Emit the 12-section WorkItem tree as nested JSON (depth-first)."""
    qs = (WorkItem.objects.filter(active=True)
          .order_by('section', 'order', 'code')
          .values('id', 'code', 'name_zh', 'parent_id', 'value_type',
                  'unit', 'is_project_scoped', 'status_options'))
    nodes = {n['id']: {**n, 'name': n['name_zh'], 'children': []} for n in qs}
    roots = []
    for n in qs:
        node = nodes[n['id']]
        pid = n['parent_id']
        if pid in nodes:
            nodes[pid]['children'].append(node)
        else:
            roots.append(node)
    return roots


def serialize_projects():
    return [
        {'id': p.id, 'name': p.name, 'category': p.category,
         'category_display': p.get_category_display()}
        for p in Project.objects.filter(active=True).order_by('category', 'name')
    ]


def serialize_existing_entries(report):
    """Pre-fill list for edit mode (JS indexes by work_item id)."""
    return [
        {'work_item': e.work_item_id, 'project': e.project_id,
         'count': e.count, 'status': e.status, 'text_value': e.text_value,
         'photos': e.photos or []}
        for e in report.entries.all()
    ]


# ── photo + hours helpers ───────────────────────────────────────────────────

def _save_photo(report, uploaded):
    """Persist one uploaded file under media/workorder_photos/<report_id>/."""
    subdir = f'workorder_photos/{report.id}'
    name = default_storage.get_available_name(os.path.join(subdir, uploaded.name))
    return default_storage.save(name, uploaded)


def _collect_entry_photos(request):
    """Map work_item_id → [uploaded files] from field names like ``ep_<id>``."""
    photos = {}
    for field, files in request.FILES.lists():
        if not field.startswith('ep_'):
            continue
        try:
            wid = int(field[3:])
        except ValueError:
            continue
        photos.setdefault(wid, []).extend(files)
    return photos


def _calc_hours(start, end, headcount):
    """Work-hours = headcount × duration, rounded to nearest 0.5h."""
    if not start or not end or headcount <= 0:
        return 0.0
    today = date.today()
    base = datetime.combine(today, start)
    end_dt = datetime.combine(today, end)
    if end_dt < base:                      # overnight shift wraps to next day
        end_dt = datetime.combine(today + timedelta(days=1), end)
    hours = (end_dt - base).total_seconds() / 3600
    return round(hours * headcount * 2) / 2


# ── view ────────────────────────────────────────────────────────────────────

@login_required(login_url='core:login')
def workorder_tree_form(request, report_id=None):
    report = None
    if report_id:
        report = get_object_or_404(WorkReport, pk=report_id)

    if request.method == 'POST':
        return _handle_save(request, report)
    return _handle_render(request, report)


def _handle_render(request, report):
    tree = serialize_workitem_tree()
    ctx = {
        'tree_json': json.dumps(tree, ensure_ascii=False),
        'projects_json': json.dumps(serialize_projects(), ensure_ascii=False),
        'locations': Patch.objects.filter(active=True).order_by('order'),
        'work_categories': WorkCategory.objects.filter(active=True).order_by('order'),
        'info_sources': InfoSource.objects.filter(active=True).order_by('order'),
        'zones': Zone.objects.order_by('code'),
        'grouped_zones': _build_grouped_zones(Zone.objects.order_by('code')),
        'today': date.today().isoformat(),
        'report': report,
        'existing_json': json.dumps(serialize_existing_entries(report), default=str)
                         if report else '{}',
        'report_photos_json': json.dumps(report.photos or []) if report else '[]',
        'header_json': json.dumps(_report_header_dict(report), ensure_ascii=False)
                        if report else '{}',
    }
    return render(request, 'core/workorder_tree_form.html', ctx)


def _report_header_dict(report):
    """Header field values to pre-fill the form in edit mode."""
    zones = list(report.zones.values_list('code', flat=True))
    return {
        'h_date': report.date.isoformat(),
        'h_weather': report.weather,
        'h_shift': report.shift,
        'h_location': report.location_id,
        'h_work_category': report.work_category_id,
        'h_info_source': report.info_source_id,
        'h_zone_names': report.zone_names,
        'h_zones': zones,
        'h_remark': report.remark,
        'h_is_difficult': report.is_difficult,
        'h_is_difficult_resolved': report.is_difficult_resolved,
        'h_team_size': report.team_size,
        'h_third_party_count': report.third_party_count,
        'h_work_start_time': report.work_start_time.strftime('%H:%M') if report.work_start_time else '',
        'h_work_end_time': report.work_end_time.strftime('%H:%M') if report.work_end_time else '',
    }


def _handle_save(request, report):
    try:
        worker = request.user.worker_profile
    except Exception:
        messages.error(request, '当前用户未关联处理人账号')
        return redirect('core:work_reports')

    # Required header fields — browser enforces too; this is the safety net.
    missing = [label for label, key in (
        ('日期', 'date'), ('位置/CCU', 'location'), ('工作分类', 'work_category'))
        if not request.POST.get(key)]
    if missing:
        messages.error(request, '请填写必填项：' + '、'.join(missing))
        return _handle_render(request, report)

    zone_codes = request.POST.getlist('zones')
    zones = list(Zone.objects.filter(code__in=zone_codes))

    start = _parse_time(request.POST.get('work_start_time'))
    end = _parse_time(request.POST.get('work_end_time'))
    team_size = int(request.POST.get('team_size') or 1)
    third_party_count = int(request.POST.get('third_party_count') or 0)

    with transaction.atomic():
        is_new = report is None
        if is_new:
            report = WorkReport(worker=worker)
        report.date = request.POST.get('date') or date.today()
        report.weather = request.POST.get('weather', '')
        report.shift = request.POST.get('shift', '')
        report.location_id = request.POST.get('location') or None
        report.work_category_id = request.POST.get('work_category') or None
        report.info_source_id = request.POST.get('info_source') or None
        report.zone_names = request.POST.get('zone_names', '')
        report.remark = request.POST.get('remark', '')
        report.is_difficult = bool(request.POST.get('is_difficult'))
        report.is_difficult_resolved = bool(request.POST.get('is_difficult_resolved'))
        report.team_size = team_size
        report.third_party_count = third_party_count
        report.work_start_time = start
        report.work_end_time = end
        report.team_hours = _calc_hours(start, end, team_size)
        report.third_party_hours = _calc_hours(start, end, third_party_count)
        # Save first so report.id exists for photo paths.
        report.save()
        report.zones.set(zones)

        # Report-level photos (1.1.12). Replace on each save for v1.
        report_photos = [_save_photo(report, f)
                         for f in request.FILES.getlist('report_photos')]
        if report_photos:
            report.photos = report_photos
            report.save(update_fields=['photos'])

        # Work-content entries.
        entries = json.loads(request.POST.get('entries', '[]') or '[]')
        entry_photos = _collect_entry_photos(request)
        _save_entries(report, entries, entry_photos)

    messages.success(request, f'现场作业记录已保存 (ID: {report.id})')
    if request.POST.get('save_and_new'):
        return redirect('core:workorder_tree_form')
    return redirect('core:work_report_detail', report_id=report.id)


def _save_entries(report, entries, entry_photos):
    """Replace all entries; create one row per node with a real value."""
    report.entries.all().delete()
    for e in entries:
        wid = e.get('work_item')
        if not wid:
            continue
        count = int(e.get('count') or 0)
        status = (e.get('status') or '').strip()
        text_value = (e.get('text_value') or '').strip()
        project_id = e.get('project') or None
        photos = entry_photos.get(int(wid), [])
        if not (count or status or text_value or photos):
            continue
        saved_paths = [_save_photo(report, f) for f in photos]
        WorkReportEntry.objects.update_or_create(
            work_report=report, work_item_id=wid, project_id=project_id,
            defaults={'count': count, 'status': status,
                      'text_value': text_value, 'photos': saved_paths},
        )


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%H:%M').time()
    except ValueError:
        return None


def _build_grouped_zones(zones):
    """Lightweight zone grouping by Patch for the <select optgroup> layout."""
    groups = {}
    order = []
    for z in zones:
        key = z.patch_id
        if key not in groups:
            groups[key] = {'name': z.patch.name if z.patch else '其它',
                           'code': z.patch.code if z.patch else '', 'zones': []}
            order.append(key)
        groups[key]['zones'].append({'name': z.name, 'code': z.code})
    return [groups[k] for k in order]
