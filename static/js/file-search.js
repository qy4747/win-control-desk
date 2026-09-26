import { $, el, icon, iconBtn, postWithTimeout, toast } from './core.js';
import { fileConfig, loadFileConfig, openFolderDialog, openFile, copyPath } from './folders.js';

let generation = 0, lastQuery = null, page = 1, hasMore = false;
let sort = 'name', direction = 'ascending';
let resultItems = [], selectedIndex = -1, previewActive = false;
let previewPending = null, previewSending = false;

function previewStatus() {
  $('#filePreviewClose').hidden = !previewActive;
  $('#filePreviewHint').textContent = previewActive
    ? 'QuickLook 联动中 · 在列表按 ↑ / ↓ 切换，Esc 关闭'
    : '选中结果后按空格预览 · 双击文件名打开';
}

async function requestPreview(action, path = '') {
  // Keep the pending open transition while coalescing its destination path.
  if (action === 'switch' && previewPending?.action === 'show') action = 'show';
  previewPending = { action, path };
  if (previewSending) return;
  previewSending = true;
  try {
    // One request at a time; holding an arrow key keeps only the latest selection.
    while (previewPending) {
      const next = previewPending; previewPending = null;
      try {
        const result = await postWithTimeout('/api/files/preview', next, 6000);
        if (!result.ok) throw new Error(result.error);
      } catch (error) {
        if (!previewPending) {
          previewActive = false; previewStatus();
          if (next.action !== 'close') toast(error.message);
        }
      }
    }
  } finally { previewSending = false; }
}

export function stopFilePreview() {
  if (!previewActive) return;
  previewActive = false; previewStatus(); requestPreview('close');
}

function selectResult(index, focus = true, sync = true) {
  if (!resultItems.length) return;
  const nextIndex = Math.max(0, Math.min(index, resultItems.length - 1));
  const changed = nextIndex !== selectedIndex; selectedIndex = nextIndex;
  [...$('#fileResults').children].forEach((row, i) => {
    row.setAttribute('aria-selected', String(i === selectedIndex));
    row.tabIndex = i === selectedIndex ? 0 : -1;
    if (i === selectedIndex && focus) { row.focus({ preventScroll: true }); row.scrollIntoView({ block: 'nearest' }); }
  });
  if (previewActive && sync && changed) requestPreview('switch', resultItems[selectedIndex].path);
}

function showPreview(index = selectedIndex) {
  if (index < 0 || !resultItems[index]) return;
  selectResult(index, true, false); previewActive = true; previewStatus();
  requestPreview('show', resultItems[index].path);
}

function resultKeydown(event) {
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.target.closest('input, select, textarea')) return;
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    if (!resultItems.length) return;
    event.preventDefault(); selectResult(selectedIndex < 0 ? 0 : selectedIndex + (event.key === 'ArrowDown' ? 1 : -1));
  } else if (event.key === 'Escape' && previewActive) {
    event.preventDefault(); stopFilePreview();
  } else if (!event.target.closest('.file-row-actions, th')) {
    if (event.key === ' ' && resultItems.length) {
      event.preventDefault(); if (previewActive) stopFilePreview(); else showPreview(selectedIndex < 0 ? 0 : selectedIndex);
    } else if (event.key === 'Enter' && selectedIndex >= 0 && event.target.tagName === 'TR') {
      event.preventDefault(); openFile(resultItems[selectedIndex].path, 'default');
    }
  }
}

function filters() {
  const form = $('#fileSearchForm');
  const scale = Number(form.elements.sizeUnit.value);
  return { query: form.elements.query.value, folderId: form.elements.folderId.value,
    kind: form.elements.kind.value, extension: form.elements.extension.value.trim(),
    minSize: form.elements.minSize.value === '' ? null : Number(form.elements.minSize.value) * scale,
    maxSize: form.elements.maxSize.value === '' ? null : Number(form.elements.maxSize.value) * scale,
    dateFrom: form.elements.dateFrom.value, dateTo: form.elements.dateTo.value };
}

function bytes(value) {
  if (value == null) return '—';
  const unit = value >= 1073741824 ? 3 : value >= 1048576 ? 2 : value >= 1024 ? 1 : 0;
  return (value / (1024 ** unit)).toLocaleString('zh-CN', { maximumFractionDigits: unit ? 2 : 0 }) + ' ' + ['B', 'KiB', 'MiB', 'GiB'][unit];
}

function empty(message) {
  resultItems = []; selectedIndex = -1;
  const row = el('tr'); const cell = el('td', 'file-empty'); cell.colSpan = 6; cell.textContent = message;
  row.append(cell); $('#fileResults').replaceChildren(row);
}

function pagination(busy = false) {
  $('#filesPrevious').disabled = busy || !lastQuery || page <= 1;
  $('#filesNext').disabled = busy || !lastQuery || !hasMore;
  $('#filesPage').textContent = String(page);
}

async function runSearch(nextPage = 1, newQuery = false) {
  stopFilePreview();
  const request = ++generation;
  if (newQuery || !lastQuery) lastQuery = filters();
  page = nextPage; hasMore = false; pagination(true);
  $('#fileSearchStatus').textContent = '正在搜索…';
  $('#fileEngineStatus').textContent = '查询中';
  $('#fileTableWrap').setAttribute('aria-busy', 'true');
  empty('正在搜索…');
  try {
    if (!fileConfig()) await loadFileConfig();
    if (request !== generation) return;
    const result = await postWithTimeout('/api/files/search', { ...lastQuery, page, sort, direction }, 12000);
    if (request !== generation) return;
    if (!result.ok) throw new Error(result.error);
    hasMore = result.hasMore;
    $('#fileEngineStatus').textContent = 'Everything 已连接';
    $('#fileSearchStatus').textContent = result.items.length ? '第 ' + page + ' 页 · 本页 ' + result.items.length + ' 项' + (result.limited ? ' · 已到分页上限，请缩小范围' : '') : '没有匹配的结果';
    renderResults(result.items);
  } catch (error) {
    if (request !== generation) return;
    $('#fileEngineStatus').textContent = '查询未完成';
    $('#fileSearchStatus').textContent = error.message;
    empty(error.message);
  } finally {
    if (request === generation) { pagination(); $('#fileTableWrap').setAttribute('aria-busy', 'false'); }
  }
}

function renderResults(items) {
  $('#fileTableWrap').scrollTop = 0;
  if (!items.length) { empty('没有匹配的结果，试试其他关键词或调整筛选条件'); return; }
  resultItems = items; selectedIndex = -1;
  const body = $('#fileResults'); body.replaceChildren();
  items.forEach((item, index) => {
    const row = el('tr');
    row.tabIndex = index === 0 ? 0 : -1;
    row.setAttribute('aria-selected', 'false');
    row.addEventListener('click', event => { if (!event.target.closest('.file-row-actions')) selectResult(index); });
    row.addEventListener('focusin', () => { if (selectedIndex !== index) selectResult(index, false); });
    const name = el('td'); const link = el('button', 'file-name'); link.type = 'button';
    const label = el('span'); label.textContent = item.name;
    link.append(icon(item.kind === 'folder' ? 'folder' : 'file-text', 20), label);
    link.title = item.name; link.addEventListener('dblclick', () => openFile(item.path, 'default')); name.append(link);
    const path = el('td', 'file-result-path'); const pathText = el('span'); pathText.textContent = item.path; pathText.title = item.path; path.append(pathText);
    const type = el('td'); type.textContent = item.kind === 'unknown' ? '未知' : item.kind === 'folder' ? '文件夹' : (item.name.includes('.') ? item.name.split('.').at(-1).toUpperCase() : '文件');
    const size = el('td', 'file-size'); size.textContent = bytes(item.size);
    const date = el('td', 'file-date'); date.textContent = item.modified ? item.modified.replace('T', ' ').slice(0, 19) : '—';
    const actions = el('td'); const bar = el('div', 'file-row-actions');
    for (const [glyph, label, run] of [
      ['eye', '预览', () => showPreview(index)],
      ['external-link', '打开', () => openFile(item.path, 'default')],
      ['folder', '定位', () => openFile(item.path)],
      ['copy', '复制路径', () => copyPath(item.path)],
      ...(item.kind === 'folder' ? [['plus', '收藏目录', () => openFolderDialog({ name: item.name, path: item.path })]] : [])
    ]) {
      const button = iconBtn(glyph, label + '：' + item.name); button.addEventListener('click', run); bar.append(button);
    }
    actions.append(bar); row.append(name, path, type, size, date, actions); body.append(row);
  });
}

export function initFileSearch() {
  $('#fileTableWrap').addEventListener('keydown', resultKeydown);
  $('#filePreviewClose').addEventListener('click', stopFilePreview);
  previewStatus();
  $('#railIconFiles').append(icon('search', 19));
  $('#fileSearchIcon').append(icon('search', 20));
  $('#fileSearchForm').addEventListener('submit', event => { event.preventDefault(); runSearch(1, true); });
  $('#fileReset').addEventListener('click', () => {
    stopFilePreview();
    ++generation; $('#fileSearchForm').reset(); lastQuery = null; page = 1; hasMore = false;
    sort = 'name'; direction = 'ascending'; updateSort(); pagination();
    $('#fileSearchStatus').textContent = ''; $('#fileEngineStatus').textContent = 'Everything';
    $('#fileTableWrap').setAttribute('aria-busy', 'false'); empty('输入关键词，或设置筛选条件后搜索');
  });
  $('#filesPrevious').addEventListener('click', () => runSearch(page - 1));
  $('#filesNext').addEventListener('click', () => runSearch(page + 1));
  document.querySelectorAll('[data-file-sort]').forEach(button => button.addEventListener('click', () => {
    const next = button.dataset.fileSort;
    direction = sort === next && direction === 'ascending' ? 'descending' : 'ascending'; sort = next;
    updateSort(); if (lastQuery) runSearch(1);
  }));
  document.addEventListener('file-config', () => {
    const select = $('#fileScope'), previous = select.value;
    select.replaceChildren(); const all = el('option'); all.value = ''; all.textContent = '全部索引'; select.append(all);
    for (const folder of fileConfig().folders) { const option = el('option'); option.value = folder.id; option.textContent = folder.name; option.title = folder.path; select.append(option); }
    select.value = fileConfig().folders.some(f => f.id === previous) ? previous : '';
  });
  updateSort(); pagination(); empty('输入关键词，或设置筛选条件后搜索');
}

function updateSort() {
  document.querySelectorAll('[data-file-sort]').forEach(button => {
    button.parentElement.setAttribute('aria-sort', button.dataset.fileSort === sort ? direction : 'none');
  });
}
