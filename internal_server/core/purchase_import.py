"""PO 表格只读预览、字段映射和物料候选；保存仍使用采购订单现有入口。"""
import csv
import difflib
import io
import json
import logging
import unicodedata
import zipfile
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .inventory_quotes import _catalog, _price
from .inventory_quote_matching import _unit
from .role_utils import get_user_role, ROLE_MANAGER, ROLE_SUPER_ADMIN

FIELDS = {
    'name': ['物料名称', '物料名', '材料名称', '品名', '商品名称', 'description', 'itemdescription', 'material'],
    'code': ['物料编码', '物料编号', '材料编码', 'itemcode', 'partnumber', 'sku'],
    'quantity': ['数量', '采购数量', '订单数量', 'quantity', 'qty'],
    'unit_price': ['未税单价', '不含税单价', '未税价格', '单价', 'unitprice', 'priceexcltax', 'unitpriceexcltax'],
    'supplier': ['供应商', '供应商名称', '供货商', 'supplier', 'vendor'],
    'unit': ['单位', '计量单位', 'unit', 'uom'],
    'po_number': ['po号', 'po编号', '采购订单号', 'ponumber', 'purchaseordernumber'],
    'order_number': ['灌溉订单编号', '灌溉订单号', 'ordernumber'],
}
SALT = 'purchase-order-sheet-v1'


def _norm(value):
    return ''.join(char for char in unicodedata.normalize('NFKC', str(value or '')).casefold() if char.isalnum())


def read_sheet(upload) -> dict:
    """限制文件、行列和单元格大小；只读取值，不执行宏或公式。"""
    if not upload.size or upload.size > 10 * 1024 * 1024:
        raise ValueError('PO 表格不能为空且不能超过10MB')
    data = upload.read(10 * 1024 * 1024 + 1)
    name = upload.name.lower()
    if name.endswith('.xlsx'):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if sum(item.file_size for item in archive.infolist()) > 30 * 1024 * 1024:
                    raise ValueError('表格解压后过大，请拆分后导入')
            from openpyxl import load_workbook
            book = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
            try:
                sheet = book.worksheets[0]
                sheet_name = sheet.title
                if sheet.max_row > 531 or sheet.max_column > 24:
                    raise ValueError('表格最多支持500条明细和24列，请缩小范围或拆分文件')
                values = list(sheet.iter_rows(min_row=1, max_row=532, max_col=24, values_only=True))
            finally:
                book.close()
        except (zipfile.BadZipFile, KeyError, OSError):
            raise ValueError('无法读取 XLSX，请确认文件格式完整') from None
    elif name.endswith('.csv'):
        try:
            decoded = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            decoded = data.decode('gb18030')
        values = []
        for index, row in enumerate(csv.reader(io.StringIO(decoded))):
            values.append(row)
            if index >= 531:
                raise ValueError('表格最多支持500条明细，请拆分文件')
        sheet_name = 'CSV'
    else:
        raise ValueError('支持 XLSX 或 CSV 格式的 PO 表格')
    if not values:
        raise ValueError('表格没有数据')
    aliases = {_norm(alias) for labels in FIELDS.values() for alias in labels}
    header_index = max(range(min(30, len(values))), key=lambda index: sum(_norm(cell) in aliases for cell in values[index]))
    columns = [str(cell or '').strip() for cell in values[header_index]]
    while columns and not columns[-1]:
        columns.pop()
    if not columns or len(columns) > 24:
        raise ValueError('请选择不超过24列的采购明细表')
    rows = []
    for index, values_row in enumerate(values[header_index + 1:], start=header_index + 2):
        row = [str(value).strip() if value is not None else '' for value in values_row[:len(columns)]]
        row += [''] * (len(columns) - len(row))
        if not any(row):
            continue
        if any(len(cell) > 800 for cell in row):
            raise ValueError(f'第{index}行内容过长，请检查物料明细范围')
        rows.append({'number': index, 'cells': row})
    if not rows or len(rows) > 500:
        raise ValueError('每次请导入1至500条物料明细，超出时拆分文件')
    document = {'columns': columns, 'rows': rows, 'sheet': sheet_name}
    if len(json.dumps(document, ensure_ascii=False)) > 250000:
        raise ValueError('表格内容过多，请拆分文件')
    return document


def build_preview(document, mapping=None, default_supplier='') -> dict:
    columns = document['columns']
    if mapping is None:
        mapping = {}
        for field, aliases in FIELDS.items():
            candidates = [index for alias in aliases for index, column in enumerate(columns) if _norm(column) == _norm(alias)]
            if candidates:
                mapping[field] = candidates[0]
    if not isinstance(mapping, dict) or any(key not in FIELDS or type(index) is not int or not 0 <= index < len(columns)
                                             for key, index in mapping.items()):
        raise ValueError('字段映射无效')
    parts = [part for part in _catalog() if part['node_type'] == 'part']
    rows, metadata = [], {}
    for source in document['rows']:
        row = {key: source['cells'][index] for key, index in mapping.items()}
        row.update(number=source['number'], errors=[])
        row['supplier'] = row.get('supplier') or default_supplier.strip()
        if len(row['supplier']) > 200:
            row['errors'].append('供应商名称超过200个字符')
        try:
            quantity = Decimal(row.get('quantity', ''))
            if not quantity.is_finite() or quantity != quantity.to_integral_value() or not 1 <= quantity <= 2147483647:
                raise InvalidOperation
            row['quantity'] = int(quantity)
        except (InvalidOperation, ValueError):
            row['errors'].append('数量须为正整数，请检查数量字段映射')
        try:
            value = _price(row.get('unit_price'), label='未税单价')
            if value is None:
                raise ValueError('请映射未税单价；空白价格不会自动填成0')
            row['unit_price'] = str(value)
        except ValueError as exc:
            row['errors'].append(str(exc))
        if not row.get('name'):
            row['errors'].append('物料名称为空，请检查名称字段映射')
        exact = [part for part in parts if row.get('code') and _norm(part['code']) == _norm(row['code'])]
        if not exact:
            exact = [part for part in parts if _norm(part['name']) == _norm(row.get('name')) or _norm(part['path']) == _norm(row.get('name'))]
        candidates = exact or sorted(parts, key=lambda part: difflib.SequenceMatcher(
            None, _norm(row.get('name')), _norm(part['name'])).ratio(), reverse=True)[:5]
        row['candidates'] = candidates[:5]
        row['category_id'] = exact[0]['id'] if len(exact) == 1 else None
        if row['category_id'] and row.get('unit') and _unit(row['unit']) != _unit(exact[0]['unit']):
            row['category_id'] = None
            row['warning'] = '表格单位与目录单位不同，请核对数量和计价单位'
        for key in ('po_number', 'order_number'):
            if row.get(key):
                metadata.setdefault(key, set()).add(row[key])
        rows.append(row)
    if any(len(values) > 1 for values in metadata.values()):
        raise ValueError('表格包含多个订单编号，请按单张订单拆分后导入')
    return {'columns': columns, 'mapping': mapping, 'rows': rows, 'catalog': parts, 'sheet': document['sheet'],
            'metadata': {key: next(iter(values)) for key, values in metadata.items()}}


@login_required(login_url='core:login')
@require_POST
def preview(request):
    if get_user_role(request.user) not in (ROLE_MANAGER, ROLE_SUPER_ADMIN):
        return JsonResponse({'success': False, 'message': '无权限'}, status=403)
    try:
        if request.FILES.get('file'):
            document = read_sheet(request.FILES['file'])
            token = signing.dumps({'user': request.user.pk, 'document': document}, salt=SALT, compress=True)
            mapping = None
        else:
            token = request.POST.get('token', '')
            saved = signing.loads(token, salt=SALT, max_age=1800)
            if saved['user'] != request.user.pk:
                raise ValueError('此预览不属于当前账号，请重新上传')
            document = saved['document']
            mapping = json.loads(request.POST.get('mapping') or '{}')
        result = build_preview(document, mapping, request.POST.get('supplier', ''))
        return JsonResponse({'success': True, 'token': token, **result})
    except (ValueError, TypeError, signing.BadSignature, UnicodeDecodeError) as exc:
        return JsonResponse({'success': False, 'message': str(exc) or '预览已过期，请重新上传表格'}, status=400)
    except Exception:
        logging.getLogger(__name__).exception('PO spreadsheet preview failed')
        return JsonResponse({'success': False, 'message': '无法读取表格，请检查文件是否损坏或另存为标准 XLSX/CSV 后重试'}, status=400)
