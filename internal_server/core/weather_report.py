"""Nine-column Maxicom weather workbook following the supplied annual template."""
import calendar
import io
from datetime import date, datetime, timedelta

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins

from .maxicom_weather import weather_report_data

FIELDS = ('min_temp', 'max_temp', 'humidity', 'solar_radiation', 'wind_run', 'rainfall', 'et')
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
HEADER = '1B4332'
INK = '243A30'
RULE = Border(left=Side(style='thin', color='D6E0D8'), right=Side(style='thin', color='D6E0D8'),
              top=Side(style='thin', color='D6E0D8'), bottom=Side(style='thin', color='D6E0D8'))


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError('天气报表日期需使用 YYYY-MM-DD。') from None


def _literal(cell, value):
    cell.value = value
    if isinstance(value, str):
        cell.data_type = 's'


def _sheet_name(book, name, year):
    import re
    name = re.sub(r'[\\/*?:\[\]]', '_', str(name or '气象站')).strip("'")
    stem = f'{name[:26]}_{year}'
    value, index = stem, 2
    while value in book.sheetnames:
        tail = f'_{index}'
        value = f'{name[:26-len(tail)]}_{year}{tail}'
        index += 1
    return value


def _header(sheet, station, year):
    sheet.sheet_view.showGridLines = False
    sheet.sheet_properties.tabColor = HEADER
    sheet.merge_cells('A1:I1')
    caption = station if len(station) <= 72 else station[:69] + '…'
    _literal(sheet['A1'], f'SHDR Irrigation Weather Station\'s Data（{year}）  {caption}')
    sheet['A1'].font = Font(name='Arial', size=13, bold=True, color=HEADER)
    sheet['A1'].alignment = Alignment(vertical='center', wrap_text=True)
    sheet.row_dimensions[1].height = 44 if len(caption) > 40 else 34
    for area in ('A2:A3', 'B2:C2', 'D2:D3', 'E2:E3', 'F2:F3', 'G2:G3', 'H2:H3', 'I2:I3'):
        sheet.merge_cells(area)
    values = {'A2': 'Date', 'B2': 'Temperature (°C)', 'B3': 'Low', 'C3': 'High',
              'D2': 'Humidity (%)', 'E2': 'Solar Radiation (Ly)', 'F2': 'Wind Run (Km)',
              'G2': 'Rainfall (mm)', 'H2': 'ET0 (mm)', 'I2': 'Mark'}
    for address, value in values.items():
        _literal(sheet[address], value)
    for row in sheet.iter_rows(min_row=2, max_row=3, max_col=9):
        for cell in row:
            cell.fill = PatternFill('solid', fgColor=HEADER)
            cell.font = Font(name='Arial', size=10, bold=True, color='FFFFFF')
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.border = RULE
    sheet.row_dimensions[2].height = 29
    sheet.row_dimensions[3].height = 22
    for column, width in zip('ABCDEFGHI', (18, 12, 12, 15, 20, 17, 17, 15, 52)):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = 'B4'
    sheet.print_title_rows = '1:3'
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_margins = PageMargins(left=.25, right=.25, top=.35, bottom=.35, header=.15, footer=.15)
    sheet.oddFooter.center.text = '第 &P 页，共 &N 页'


def _style_row(sheet, row, *, fill='FFFFFF', bold=False, color=INK):
    for cell in sheet.iter_rows(min_row=row, max_row=row, max_col=9).__next__():
        cell.font = Font(name='Arial', size=10, bold=bold, color=color)
        cell.fill = PatternFill('solid', fgColor=fill)
        cell.border = RULE
        cell.alignment = Alignment(horizontal='left' if cell.column == 9 else 'center',
                                   vertical='center', wrap_text=cell.column == 9)
        if 2 <= cell.column <= 8:
            cell.number_format = '0.00' if cell.column >= 7 else '0.0'
    sheet.row_dimensions[row].height = 24


def _summary(sheet, row, label, ranges, records, cache, *, average=False, yearly=False):
    _literal(sheet.cell(row, 1), label)
    for column, field in enumerate(FIELDS, 2):
        letter = get_column_letter(column)
        source = ','.join(f'{letter}{first}:{letter}{last}' for first, last in ranges)
        operation = 'AVERAGE' if average else 'SUM'
        sheet.cell(row, column, f'=IF(COUNT({source})=0,"",{operation}({source}))')
        values = [record.get(field) for record in records if isinstance(record.get(field), (int, float))]
        value = (sum(values) / len(values) if average else sum(values)) if values else ''
        cache[(sheet.title, f'{letter}{row}')] = value
    _style_row(sheet, row, fill=HEADER if yearly else 'E7F0E9', bold=True,
               color='FFFFFF' if yearly else HEADER)
    sheet.row_dimensions[row].height = 26


def _station_year(book, station, year, start, end, source_note, cache):
    sheet = book.create_sheet(_sheet_name(book, station['name'], year))
    _header(sheet, station['name'], year)
    records_by_day = station.get('days', {})
    if not any(day.year == year for day in records_by_day):
        _literal(sheet['A1'], sheet['A1'].value + '（所选范围无实际记录）')
    first_day, last_day = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
    cursor, row = first_day, 4
    all_ranges, all_records = [], []
    while cursor <= last_day:
        month = cursor.month
        month_end = min(date(year, month, calendar.monthrange(year, month)[1]), last_day)
        first_row, records = row, []
        while cursor <= month_end:
            source = records_by_day.get(cursor)
            record = source or {}
            sheet.cell(row, 1, cursor)
            sheet.cell(row, 1).number_format = 'yyyy-mm-dd'
            for column, field in enumerate(FIELDS, 2):
                sheet.cell(row, column, record.get(field))
            note = record.get('notes') or ('缺少当日气象记录' if source is None else '')
            _literal(sheet.cell(row, 9), note)
            _style_row(sheet, row, fill='F3F7F3' if month % 2 else 'FFFFFF')
            if note:
                sheet.cell(row, 9).font = Font(name='Arial', size=9, color='976029')
                sheet.row_dimensions[row].height = 32 if len(note) > 35 else 24
            records.append(record)
            row += 1
            cursor += timedelta(days=1)
        last_row = row - 1
        all_ranges.append((first_row, last_row))
        all_records.extend(records)
        _summary(sheet, row, f'{MONTHS[month-1]} Total', [(first_row, last_row)], records, cache)
        row += 1
        _summary(sheet, row, f'{MONTHS[month-1]} Average', [(first_row, last_row)], records, cache, average=True)
        row += 1
    _summary(sheet, row, 'Year Total', all_ranges, all_records, cache, yearly=True)
    row += 1
    _summary(sheet, row, 'Year Average', all_ranges, all_records, cache, average=True, yearly=True)
    row += 2
    notes = [f'报表范围：{start:%Y-%m-%d} 至 {end:%Y-%m-%d}。年、月统计仅覆盖本次所选日期；缺测留空，不作 0。',
             '温湿度累加仅按原模板统计；平均值按各指标实际有值的每日记录计算，年均值不平均各月均值。', source_note]
    if station.get('notice'):
        notes.insert(0, station['notice'])
    if len(station['name']) > 72:
        notes.insert(0, '气象站：' + station['name'])
    for note in notes:
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
        _literal(sheet.cell(row, 1), note)
        sheet.cell(row, 1).font = Font(name='Arial', size=9, color='5A6F60')
        sheet.cell(row, 1).alignment = Alignment(vertical='center', wrap_text=True)
        sheet.row_dimensions[row].height = 30
        row += 1
    sheet.print_area = f'A1:I{row-1}'
    return sheet


def build_maxicom_weather_excel(start=None, end=None):
    """Return (filename, BytesIO); each station/year keeps its own actual data."""
    end = _date(end) if end is not None else timezone.localdate() - timedelta(days=1)
    start = _date(start) if start is not None else end - timedelta(days=29)
    if start > end:
        raise ValueError('天气报表开始日期不能晚于结束日期。')
    if (end - start).days > 3660:
        raise ValueError('天气报表每次最多导出十年，请缩小日期范围。')
    data = weather_report_data(start, end)
    stations = data.get('stations') or [{'name': '气象数据', 'days': {},
        'notice': data.get('notice') or '所选日期没有 Maxicom 实际气象记录，空白不表示 0。'}]
    book = Workbook()
    book.remove(book.active)
    cache = {}
    for station in stations:
        for year in range(start.year, end.year + 1):
            _station_year(book, station, year, start, end, data.get('source_note', ''), cache)
    book.active = 0
    # Runtime builders use openpyxl consistently with the application's existing
    # mail exports; formula caches are filled for clients that do not recalculate.
    from .irrigation_water_summary import save_workbook_with_cached_formulas
    buffer = io.BytesIO()
    save_workbook_with_cached_formulas(book, buffer, cache)
    buffer.seek(0)
    return f'maxicom_weather_{start:%Y%m%d}_{end:%Y%m%d}.xlsx', buffer
