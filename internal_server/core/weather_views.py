"""实际气象按上海自然日展示；ET₀ 状态与现有报表来源说明一致。"""
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone

from .maxicom_weather import weather_report_data


def daily_rows(start, end):
    data = weather_report_data(start, end)
    rows = []
    for station in data['stations']:
        day = start
        while day <= end:
            values = station['days'].get(day, {})
            rows.append({'date': day, 'station': station['name'], **values,
                         'notes': values.get('notes', '全天缺测，数值留空')})
            day += timedelta(days=1)
    return data, rows


@login_required(login_url='core:login')
def daily_page(request):
    try:
        end = date.fromisoformat(request.GET['end']) if request.GET.get('end') else timezone.localdate() - timedelta(days=1)
        start = date.fromisoformat(request.GET['start']) if request.GET.get('start') else end - timedelta(days=29)
        if start > end or (end - start).days > 365:
            raise ValueError('请选择起止有序、不超过366天的日期范围')
    except ValueError as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=400)
    if request.GET.get('format') == 'xlsx':
        from .weather_report import build_maxicom_weather_excel
        name, stream = build_maxicom_weather_excel(start, end)
        return FileResponse(stream, as_attachment=True, filename=name)
    data, rows = daily_rows(start, end)
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'success': True, 'start': start, 'end': end, 'rows': rows,
            'source_note': data['source_note'], 'et_label': data['et_label'], 'et_method': data['et_method'],
            'et_parameters': [{'station': station['name'], 'mdb_index': station['mdb_index'],
                               'profile': station['et_profile']} for station in data['stations']]})
    return render(request, 'core/weather_daily.html', {'rows': rows, 'source_note': data['source_note'],
        'notice': data.get('notice'), 'start': start, 'end': end, 'et_stations': data['stations']})
