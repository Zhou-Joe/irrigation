"""Traceable water totals and targeted XLSX formula-result caches.

The caller supplies sensor classifications and actual runtime cell addresses;
this module neither guesses source Site ownership nor queries business data.
Only configured blank runtime cells mean zero. Missing coverage stays visible.
"""
from __future__ import annotations

import io
import math
import posixpath
import re
from decimal import Decimal
from numbers import Real
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils.cell import absolute_coordinate, column_index_from_string, quote_sheetname
from openpyxl.worksheet.page import PageMargins

from .irrig_time import _compact_datetime


SUMMARY_SHEET = '用水量汇总'
SENSOR_SHEET = '传感器水量'
FLOW_M3_H = Decimal('37')
GROUP_NAMES = {'irrigation':'灌溉', 'cleaning':'清洗', 'toilet':'冲厕', None:'未分类'}
RUNTIME_KEYS = ('3-5-15', '38-1-6', '38-1-13')
_CELL = re.compile(r'\$?([A-Za-z]{1,3})\$?([1-9][0-9]{0,6})\Z')
_MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
        return None
    result = Decimal(str(value))
    return result if result.is_finite() else None


def _reference(workbook, sheet, coordinate):
    if not isinstance(sheet, str) or sheet not in workbook.sheetnames or not isinstance(coordinate, str):
        return None
    match = _CELL.fullmatch(coordinate)
    if not match or column_index_from_string(match[1]) > 16384 or int(match[2]) > 1048576:
        return None
    normalized = match[1].upper() + match[2]
    return quote_sheetname(sheet) + '!' + absolute_coordinate(normalized), workbook[sheet][normalized]


def _sensor_rows(workbook, rows):
    result, seen = [], set()
    for row in rows:
        number = row.get('row')
        reference = _reference(workbook, SENSOR_SHEET, f'E{number}') if type(number) is int else None
        # A shared physical source is already one source-sheet row. Never
        # sum an accidentally repeated reference twice.
        if reference and number in seen:
            continue
        if reference:
            seen.add(number)
        value = _number(reference[1].value) if reference else None
        complete = bool(row.get('complete')) and bool(row.get('enabled', True)) and value is not None
        status = '实际记录' if complete else '部分记录' if value is not None else '已停用' if not row.get('enabled', True) else '未覆盖'
        result.append({**row, 'group':row.get('group') if row.get('group') in GROUP_NAMES else None,
                       'reference':reference[0] if reference else None,
                       'numeric':value, 'covered':complete, 'status':status})
    return result


def _sensor_refs(rows):
    """Compress only consecutive, explicitly listed rows into bounded ranges."""
    numbers = sorted({row['row'] for row in rows if row['reference']})
    chunks = []
    for number in numbers:
        if chunks and number == chunks[-1][-1] + 1:
            chunks[-1].append(number)
        else:
            chunks.append([number])
    prefix = quote_sheetname(SENSOR_SHEET) + '!'
    return ','.join(prefix + f'$E${chunk[0]}' + (f':$E${chunk[-1]}' if len(chunk) > 1 else '') for chunk in chunks)


def _sensor_total(rows):
    refs = _sensor_refs(rows)
    known = [row['numeric'] for row in rows if row['numeric'] is not None]
    complete = bool(rows) and all(row['covered'] for row in rows)
    status = '实际记录' if complete else '部分记录' if known else '未覆盖'
    if not refs:
        return {'formula':'="—"', 'value':'—', 'status':status, 'condition':'FALSE', 'sum':'0', 'rows':rows}
    condition = f'COUNT({refs})={len(rows)}' if complete else f'COUNT({refs})>0'
    return {'formula':f'=IF({condition},SUM({refs})/1000,"—")',
            'value':sum(known, Decimal(0)) / 1000 if known else '—',
            'status':status, 'condition':condition, 'sum':f'SUM({refs})/1000', 'rows':rows}


def _runtime(workbook, raw):
    if not isinstance(raw, dict):
        return {'reference':None, 'value':'—', 'status':'未包含', 'condition':'FALSE', 'formula':'="—"'}
    source = _reference(workbook, raw.get('sheet'), raw.get('cell'))
    if source is None:
        return {'reference':None, 'value':'—', 'status':'未包含', 'condition':'FALSE', 'formula':'="—"'}
    reference, cell = source
    value = _number(cell.value)
    complete = raw.get('complete', True) is not False
    if cell.value is None and complete:
        value = Decimal(0)
    status = '实际记录' if value is not None and complete else '部分记录' if value is not None else '未覆盖'
    condition = f'OR(ISNUMBER({reference}),ISBLANK({reference}))' if complete else f'ISNUMBER({reference})'
    return {'reference':reference, 'value':value if value is not None else '—', 'status':status,
            'condition':condition, 'formula':f'=IF({condition},SUM({reference}),"—")'}


def _runtime_total(items):
    if any(item['status'] == '未包含' for item in items):
        return {'formula':'="—"', 'value':'—', 'status':'未包含'}
    condition = ','.join(item['condition'] for item in items)
    refs = ','.join(item['reference'] for item in items)
    value = (sum((item['value'] for item in items), Decimal(0)) / 60 * FLOW_M3_H
             if all(isinstance(item['value'], Decimal) for item in items) else '—')
    return {'formula':f'=IF(AND({condition}),SUM({refs})/60*$C$17,"—")', 'value':value,
            'status':'未覆盖' if value == '—' else '部分记录' if any(item['status'] == '部分记录' for item in items) else '实际记录'}


def _literal(cell, value):
    cell.value = str(value)
    cell.data_type = 's'


def add_water_summary(workbook, date_from, date_to, sensor_rows, runtime_cells, scope_label='全部CCU'):
    """Insert the first sheet and return {(sheet, coordinate): cached result}.

    ``sensor_rows`` references physical-source rows in 传感器水量; classifications
    are explicit irrigation/cleaning/toilet/None. ``runtime_cells`` maps the
    three configured station keys to {sheet, cell, value} or None. Addresses
    must exist in the workbook; an excluded CCU is never inferred as zero.
    Actual source cell values determine cached results, matching Excel SUM.
    """
    if SUMMARY_SHEET in workbook.sheetnames:
        raise ValueError('工作簿已包含用水量汇总，请避免重复添加')
    rows = _sensor_rows(workbook, list(sensor_rows or []))
    runtime_cells = runtime_cells or {}
    runtimes = {key:_runtime(workbook, runtime_cells.get(key)) for key in RUNTIME_KEYS}
    total = _sensor_total(rows)
    irrigation = _sensor_total([row for row in rows if row['group'] == 'irrigation'])
    cleaning = _sensor_total([row for row in rows if row['group'] == 'cleaning'])
    toilet = _sensor_total([row for row in rows if row['group'] == 'toilet'])
    wetland = _runtime_total([runtimes['3-5-15']])
    fountain = _runtime_total([runtimes['38-1-6'], runtimes['38-1-13']])
    net_value = (irrigation['value'] - wetland['value'] - fountain['value']
                 if all(isinstance(item['value'], Decimal) for item in (irrigation, wetland, fountain)) else '—')
    statuses = [item['status'] for item in (irrigation, wetland, fountain)]
    net_status = ('未包含' if '未包含' in statuses else '未覆盖' if net_value == '—'
                  else '部分记录' if '部分记录' in statuses else '实际记录')
    net = {'formula':f'=IF(AND({irrigation["condition"]},ISNUMBER($C$11),ISNUMBER($C$12)),{irrigation["sum"]}-$C$11-$C$12,"—")',
           'value':net_value, 'status':net_status}
    metrics = [
        ('灌溉系统自动记录的用水量汇总', total, '全部列示传感器合计 ÷ 1000', '传感器水量：所有列示行'),
        ('灌溉用水量', net, '灌溉类传感器 ÷ 1000 − 湿地 − 喷泉', '湿地、喷泉任一未包含时不计算净量'),
        ('保洁冲洗用水量', cleaning, '清洗类传感器合计 ÷ 1000', '按已确认的 Site / 通道分类'),
        ('湿地补水量', wetland, '3-5-15 分钟 ÷ 60 × 流量系数', '运行时长估算，系数见 C17'),
        ('喷泉补水量', fountain, '(38-1-6 + 38-1-13) 分钟 ÷ 60 × 系数', '两个站点须同时包含在报表范围内'),
        ('冲厕用水量', toilet, '冲厕类传感器合计 ÷ 1000', '按已确认的 Site / 通道分类'),
    ]
    ws = workbook.create_sheet(SUMMARY_SHEET, 0)
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = '1B4332'
    cached = {}

    def formula(coordinate, expression, value):
        ws[coordinate] = expression
        cached[(ws.title, coordinate)] = float(value) if isinstance(value, Decimal) else value

    ws.merge_cells('A1:G1')
    ws['A1'] = '用水量汇总'
    ws['A1'].font = Font(name='Arial', size=16, bold=True, color='1B4332')
    ws.row_dimensions[1].height = 32
    ws['A2'], ws['D2'] = '查询开始', '查询结束'
    ws.merge_cells('B2:C2'); ws.merge_cells('E2:G2')
    ws['B2'] = _compact_datetime(date_from) if date_from else '未指定'
    ws['E2'] = _compact_datetime(date_to, end=True) if date_to else '未指定'
    ws['B2'].number_format = ws['E2'].number_format = 'yyyy-mm-dd hh:mm:ss'
    ws['A3'] = '统计范围'; ws.merge_cells('B3:G3'); _literal(ws['B3'], scope_label)
    ws.merge_cells('A4:G4')
    ws['A4'] = '上海时间（24小时制）。单位 m³；传感器为实际读数，湿地与喷泉按运行时长估算。'
    notes = []
    ungrouped = [row for row in rows if row['group'] is None]
    if ungrouped:
        identities = [f'Site {row.get("site_number") if row.get("site_number") is not None else row.get("site_key", "?")} / 通道 {row.get("channel", "?")}' for row in ungrouped]
        notes.append(f'未分类传感器 {len(ungrouped)} 个（' + '、'.join(identities[:8]) + ('等，见下方明细' if len(identities) > 8 else '') + '）：计入总用水量，不计入分类小计。')
    if any(metric['status'] != '实际记录' for _, metric, _, _ in metrics):
        notes.append('部分记录仅显示已知小计；“—”表示未覆盖或未包含，不能当作 0。')
    if isinstance(net_value, Decimal) and net_value < 0:
        notes.append('灌溉差额为负，请核对传感器归类、覆盖范围及运行时长。')
    ws.merge_cells('A5:G5')
    _literal(ws['A5'], ' '.join(notes) or '各项均可追溯至本工作簿的实际传感器及运行时长单元格。')
    ws['A5'].fill = PatternFill('solid', fgColor='FFF2D5' if notes else 'F2F6F3')
    ws.row_dimensions[4].height = 25
    ws.row_dimensions[5].height = 42 if notes else 25

    def header(row_number, labels):
        for column, text in enumerate(labels, 1):
            cell = ws.cell(row_number, column, text)
            cell.font = Font(name='Arial', size=10, bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='1B4332')
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.border = Border(right=Side(style='thin', color='FFFFFF'))
        ws.row_dimensions[row_number].height = 27

    header(7, ['序号', '汇总项目', '用水量', '单位', '记录状态', '计算口径', '来源说明'])
    for number, (label, metric, expression, explanation) in enumerate(metrics, 1):
        line = number + 7
        for column, value in ((1, number), (2, label), (4, 'm³'), (5, metric['status']), (6, expression), (7, explanation)):
            ws.cell(line, column, value)
        formula(f'C{line}', metric['formula'], metric['value'])
        ws.cell(line, 3).number_format = '#,##0.00;[Red](#,##0.00)'
        ws.row_dimensions[line].height = 38
        for cell in ws[line]:
            cell.fill = PatternFill('solid', fgColor='F0F5F1' if number % 2 else 'FFFFFF')
            cell.border = Border(bottom=Side(style='hair', color='DFE8E1'))
        ws.cell(line, 3).font = Font(name='Arial', size=15, bold=True, color='1B4332')
        if metric['status'] != '实际记录':
            ws.cell(line, 5).font = Font(name='Arial', size=10, bold=True, color='9A5A0A')

    ws.merge_cells('A15:G15'); ws['A15'] = '计算参数与运行时长明细'
    header(16, ['参数 / 站点', '', '数值', '单位', '记录状态', '来源单元格', '说明'])
    ws.merge_cells('A17:B17'); ws['A17'], ws['C17'], ws['D17'], ws['E17'] = '湿地 / 喷泉流量系数', float(FLOW_M3_H), 'm³/h', '计算参数'
    ws.merge_cells('F17:G17'); ws['F17'] = '当前按 37 m³/h 估算；修改 C17 后，Excel 会重新计算相关用水量。'
    ws['C17'].fill = PatternFill('solid', fgColor='E3EEDF'); ws['C17'].number_format = '0.00'
    ws.row_dimensions[17].height = 31
    for line, key in enumerate(RUNTIME_KEYS, 18):
        runtime = runtimes[key]
        ws.merge_cells(start_row=line, start_column=1, end_row=line, end_column=2)
        ws.cell(line, 1, ('湿地 ' if key == '3-5-15' else '喷泉 ') + key)
        formula(f'C{line}', runtime['formula'], runtime['value'])
        ws.cell(line, 3).number_format = '#,##0.00'
        ws.cell(line, 4, '分钟'); ws.cell(line, 5, runtime['status'])
        _literal(ws.cell(line, 6), runtime['reference'] or '未包含该 CCU / 未配置该站点')
        if runtime['reference']:
            ws.cell(line, 6).hyperlink = '#' + runtime['reference']
        ws.cell(line, 7, '已配置且原单元格空白才按 0' if runtime['status'] == '实际记录' else '不得作为完整时段的 0 分钟')
        ws.row_dimensions[line].height = 31
    ws.merge_cells('A22:G22')
    ws['A22'] = '计算说明：1 m³ = 1000 L；湿地与喷泉为时长估算。总量包含未分类传感器，分类小计不一定与总量相等。'
    ws.row_dimensions[22].height = 30
    ws.merge_cells('A24:G24'); ws['A24'] = '传感器分类与原始读数明细'
    header(25, ['Site', '通道', '传感器名称', '分类', '原始读数（L）', '记录状态', '来源单元格'])
    for line, sensor in enumerate(rows, 26):
        for column, value in ((1, sensor.get('site_number') if sensor.get('site_number') is not None else sensor.get('site_key', '未编号')),
                              (2, sensor.get('channel', '')), (3, sensor.get('name', '')),
                              (4, GROUP_NAMES[sensor['group']]), (6, sensor['status'])):
            if isinstance(value, str):
                _literal(ws.cell(line, column), value)
            else:
                ws.cell(line, column, value)
        reference = sensor['reference']
        formula(f'E{line}', f'=IF(ISNUMBER({reference}),{reference},"—")' if reference else '="—"', sensor['numeric'] if sensor['numeric'] is not None else '—')
        ws.cell(line, 5).number_format = '#,##0.00'
        _literal(ws.cell(line, 7), reference or '无有效来源单元格')
        if reference:
            ws.cell(line, 7).hyperlink = '#' + reference
        for cell in ws[line]:
            cell.fill = PatternFill('solid', fgColor='F0F5F1' if line % 2 == 0 else 'FFFFFF')
        ws.row_dimensions[line].height = 31
    last_row = max(25, 25 + len(rows))
    # Fill common typography only where a larger value/title style is absent.
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            if cell.font.name != 'Arial':
                cell.font = Font(name='Arial', size=10, color='243A30')
            if cell.row not in (7, 16, 25):
                cell.alignment = Alignment(horizontal='right' if cell.column in (3, 5) and cell.data_type == 'f' else 'left', vertical='center', wrap_text=True)
    for line in (15, 24):
        ws.cell(line, 1).font = Font(name='Arial', size=11, bold=True, color='1B4332')
        ws.row_dimensions[line].height = 25
    for column, width in zip('ABCDEFG', (10, 22, 23, 10, 16, 39, 30)):
        ws.column_dimensions[column].width = width
    ws.freeze_panes = 'A8'
    ws.auto_filter.ref = f'A25:G{last_row}'
    ws.print_title_rows = '1:7'; ws.print_area = f'A1:G{last_row}'
    ws.page_setup.orientation = 'landscape'; ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins = PageMargins(left=.25, right=.25, top=.35, bottom=.35, header=.15, footer=.15)
    ws.oddFooter.center.text = '第 &P 页，共 &N 页'
    workbook.active = 0
    return cached


def save_workbook_with_cached_summary(workbook, buf, cached_values):
    """Restrict the shared serializer to the water-summary worksheet."""
    cache = dict(cached_values or {})
    if any(not isinstance(key, tuple) or len(key) != 2 or key[0] != SUMMARY_SHEET for key in cache):
        raise ValueError('公式缓存只允许用水量汇总的明确单元格')
    return save_workbook_with_cached_formulas(workbook, buf, cache)


def save_workbook_with_cached_formulas(workbook, buf, cached_values):
    """Cache explicitly addressed formula results without touching other parts.

    openpyxl does not calculate formula values. Mobile/email previews often do
    not recalculate either, so a report builder supplies a mapping
    ``{(sheet_title, coordinate): numeric_or_text}``. Workbook calculation
    settings and all unaddressed ZIP parts stay untouched. No archive member is
    extracted to the filesystem. Both water and weather reports can reuse this.
    """
    by_sheet = {}
    for key, value in dict(cached_values or {}).items():
        if (not isinstance(key, tuple) or len(key) != 2 or not isinstance(key[0], str)
                or not isinstance(key[1], str) or not _CELL.fullmatch(key[1])):
            raise ValueError('公式缓存需要明确的工作表名称与单元格地址')
        coordinate = key[1].replace('$', '').upper()
        by_sheet.setdefault(key[0], {})[coordinate] = value
    raw = io.BytesIO(); workbook.save(raw)
    if not by_sheet:
        output = raw.getvalue()
    else:
        patched = io.BytesIO()
        with ZipFile(raw) as source:
            book = ET.fromstring(source.read('xl/workbook.xml'))
            relations = ET.fromstring(source.read('xl/_rels/workbook.xml.rels'))
            targets = {relation.attrib['Id']:relation.attrib['Target'] for relation in relations}
            sheets = {sheet.attrib['name']:sheet for sheet in book.findall(f'{{{_MAIN}}}sheets/{{{_MAIN}}}sheet')}
            modified = {}
            for title, cache in by_sheet.items():
                if title not in sheets:
                    raise ValueError(f'工作簿缺少工作表：{title}')
                target = targets[sheets[title].attrib[f'{{{_REL}}}id']]
                member = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl', target))
                xml = ET.fromstring(source.read(member))
                found = set()
                for cell in xml.iter(f'{{{_MAIN}}}c'):
                    coordinate = cell.attrib.get('r')
                    if coordinate not in cache:
                        continue
                    if cell.find(f'{{{_MAIN}}}f') is None:
                        raise ValueError(f'缓存目标 {title}!{coordinate} 不是公式单元格')
                    value = cache[coordinate]
                    result = cell.find(f'{{{_MAIN}}}v')
                    if result is None:
                        result = ET.SubElement(cell, f'{{{_MAIN}}}v')
                    numeric = _number(value)
                    if numeric is not None:
                        cell.attrib.pop('t', None); result.text = str(numeric)
                    elif isinstance(value, str):
                        cell.set('t', 'str'); result.text = value
                    elif value is None:
                        cell.attrib.pop('t', None); result.text = None
                    else:
                        raise ValueError('公式缓存结果必须是有限数值、字符串或空值')
                    found.add(coordinate)
                if found != set(cache):
                    raise ValueError('部分公式缓存单元格不存在，未输出不完整的工作簿')
                modified[member] = ET.tostring(xml, encoding='utf-8', xml_declaration=True)
            with ZipFile(patched, 'w') as destination:
                for info in source.infolist():
                    destination.writestr(info, modified.get(info.filename, source.read(info.filename)))
        output = patched.getvalue()
    buf.seek(0); buf.truncate(0); buf.write(output); buf.seek(0)
    return buf
