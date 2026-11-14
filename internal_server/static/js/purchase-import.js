/* PO import remains an editable draft until the existing Save action succeeds. */
let poImportDocument = null;
let poImportRevision = 0;
const poImportFields = {name:'物料名称',code:'物料编码',quantity:'数量',unit_price:'未税单价',supplier:'供应商',unit:'计价单位',po_number:'PO号',order_number:'灌溉订单编号'};
function poImportPartLabel(part) { return part.path + (part.code ? ' [' + part.code + ']' : ''); }
window.poImportReset = function () {
  poImportRevision++; poImportDocument = null;
  document.getElementById('poImportFile').value = '';
  document.getElementById('poImportSupplier').value = '';
  for (const id of ['poImportMapping','poImportRows','poImportStatus']) document.getElementById(id).replaceChildren();
  document.getElementById('poImportApply').hidden = true;
};
window.poImportPreview = async function (upload) {
  const status = document.getElementById('poImportStatus'), body = new FormData(), revision = ++poImportRevision;
  if (upload) {
    const file = document.getElementById('poImportFile').files[0];
    if (!file) { status.textContent = '请先选择 PO 表格'; return; }
    body.set('file', file);
  } else {
    if (!poImportDocument) return;
    body.set('token', poImportDocument.token);
    const mapping = {};
    document.querySelectorAll('[data-po-import-field]').forEach(select => { if (select.value !== '') mapping[select.dataset.poImportField] = Number(select.value); });
    body.set('mapping', JSON.stringify(mapping));
  }
  body.set('supplier', document.getElementById('poImportSupplier').value.trim());
  status.textContent = '正在读取和匹配…'; document.getElementById('poImportApply').hidden = true;
  try {
    const response = await fetch('/purchase-orders/import-preview/', {method:'POST', body,
      headers:{'X-CSRFToken':_poCsrf(), 'X-Requested-With':'XMLHttpRequest', 'Accept':'application/json'}});
    const data = (response.headers.get('content-type') || '').includes('application/json') ? await response.json() : {};
    if (revision !== poImportRevision) return;
    if (!response.ok || !data.success) throw new Error(data.message || '无法读取表格，请检查登录状态及文件格式');
    poImportDocument = data;
    const mappingBox = document.getElementById('poImportMapping'); mappingBox.replaceChildren();
    Object.entries(poImportFields).forEach(([field, title]) => {
      const label = document.createElement('label'); label.style.cssText = 'display:inline-flex;gap:6px;margin:8px;align-items:center;'; label.append(title);
      const select = document.createElement('select'); select.dataset.poImportField = field;
      select.add(new Option('未映射', ''));
      data.columns.forEach((name, index) => select.add(new Option((index + 1) + '. ' + (name || '空表头'), index)));
      select.value = data.mapping[field] === undefined ? '' : String(data.mapping[field]);
      select.addEventListener('change', () => poImportPreview(false)); label.appendChild(select); mappingBox.appendChild(label);
    });
    const esc = _poEsc;
    document.getElementById('poImportRows').innerHTML = '<datalist id="poImportCatalog">' + data.catalog.map(part =>
      '<option value="' + esc(poImportPartLabel(part)) + '"></option>').join('') + '</datalist>' +
      '<table class="iv-price-table" style="min-width:1000px;"><thead><tr><th>导入</th><th>表格物料</th><th>目录匹配（可搜索修改）</th><th>数量</th><th>未税单价</th><th>单位</th><th>供应商</th><th>说明</th></tr></thead><tbody>' +
      data.rows.map((row, index) => {
        const match = data.catalog.find(part => part.id === row.category_id);
        return '<tr data-po-import-row="' + index + '"><td><input data-import-include type="checkbox" checked></td><td>' + esc(row.name || '') + '</td>' +
          '<td><input data-import-match list="poImportCatalog" placeholder="搜索目录物料" value="' + esc(match ? poImportPartLabel(match) : '') + '"></td>' +
          '<td><input data-import-quantity type="number" min="1" step="1" style="width:75px;" value="' + esc(row.quantity ?? '') + '"></td>' +
          '<td><input data-import-price type="number" min="0" step="0.01" style="width:90px;" value="' + esc(row.unit_price ?? '') + '"></td>' +
          '<td><input data-import-unit maxlength="10" style="width:55px;" value="' + esc(row.unit || match?.unit || '') + '"></td>' +
          '<td><input data-import-supplier maxlength="200" value="' + esc(row.supplier || '') + '"></td>' +
          '<td>源行 ' + row.number + '；' + esc(row.errors.join('；') || row.warning || (match ? '唯一匹配，请核对' : '请选择匹配物料')) + '</td></tr>';
      }).join('') + '</tbody></table>';
    status.textContent = '已读取「' + data.sheet + '」的 ' + data.rows.length + ' 条明细。可修改映射、匹配和单价；不需要的行请取消勾选。尚未保存订单。';
    const apply = document.getElementById('poImportApply'); apply.hidden = false; apply.disabled = false;
  } catch (error) { if (revision === poImportRevision) status.textContent = error.message; }
};
window.poImportApply = function () {
  if (!poImportDocument || document.getElementById('poImportApply').disabled) return;
  const status = document.getElementById('poImportStatus'), imported = [];
  try {
    for (const row of document.querySelectorAll('[data-po-import-row]')) {
      if (!row.querySelector('[data-import-include]').checked) continue;
      const value = name => row.querySelector('[data-import-' + name + ']').value.trim();
      const part = poImportDocument.catalog.find(item => poImportPartLabel(item) === value('match'));
      if (!part) throw new Error('请为每条勾选明细选择实际目录物料');
      const quantity = Number(value('quantity')), price = value('price'), supplier = value('supplier'), unit = value('unit') || part.unit;
      if (!Number.isSafeInteger(quantity) || quantity <= 0 || quantity > 2147483647) throw new Error(part.name + '：数量须为正整数');
      if (!/^(?:0|[1-9]\d{0,9})(?:\.\d{1,2})?$/.test(price)) throw new Error(part.name + '：请填写非负未税单价，最多两位小数');
      if (unit.length > 10 || supplier.length > 200) throw new Error(part.name + '：单位或供应商过长');
      imported.push({id:part.id, name:part.name, path:part.path, quantity, unit, unit_price:price, supplier});
    }
    if (!imported.length) throw new Error('请至少勾选一条采购明细');
    const cart = _poPlannedCart.map(item => ({...item}));
    for (const item of imported) {
      const old = cart.find(existing => existing.id === item.id);
      if (old) {
        if (Number(old.unit_price) !== Number(item.unit_price) || (old.supplier || '') !== item.supplier || old.unit !== item.unit)
          throw new Error(item.name + '：草稿中已有不同价格、单位或供应商，请先核对，不能自动合并');
        old.quantity += item.quantity;
        if (!Number.isSafeInteger(old.quantity) || old.quantity > 2147483647) throw new Error(item.name + '：合并数量过大');
      } else cart.push({...item});
    }
    _poPlannedCart = cart; _poRenderPlanned();
    for (const field of ['po_number','order_number']) {
      const input = document.getElementById('poF' + field);
      if (!input.value.trim() && poImportDocument.metadata[field]) input.value = poImportDocument.metadata[field];
    }
    document.getElementById('poImportApply').disabled = true;
    status.textContent = '已填入 ' + imported.length + ' 条明细到订单草稿。请核对后点击订单的保存按钮。';
  } catch (error) { status.textContent = error.message; }
};
