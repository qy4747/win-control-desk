import { $, el, icon, iconBtn, post, postWithTimeout, act, toast, escapeHtml, openLayer, closeLayer } from './core.js';
import { openConfirm } from './overlays.js';

let config = null, loading = null, selectedGroup = '', editingId = null, draggedId = null;
let saving = false, ordering = false;
let folderSession = 0;
export const fileConfig = () => config;

export async function loadFileConfig(fresh = false) {
  // A completed write needs a new snapshot, even if an older read is in flight.
  if (fresh && loading) { try { await loading; } catch { /* Retry the fresh read. */ } }
  if (loading) return loading;
  loading = (async () => {
    const response = await fetch('/api/files/config', { cache: 'no-store', signal: AbortSignal.timeout(12000) });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || '目录配置读取失败');
    config = data;
    renderFolders();
    document.dispatchEvent(new Event('file-config'));
    return data;
  })();
  try { return await loading; } finally { loading = null; }
}

export async function showFilePage(view) {
  if (!['folders', 'files', 'settings'].includes(view)) return;
  try {
    const data = await loadFileConfig();
    if (!$('#esPath').matches(':focus')) $('#esPath').value = data.settings.esPath;
    $('#folderStatus').textContent = '';
  } catch (error) {
    $('#folderStatus').textContent = error.message;
    $('#esSettingStatus').textContent = error.message;
    toast(error.message);
  }
}

export async function copyPath(path) {
  try { await navigator.clipboard.writeText(path); toast('路径已复制'); }
  catch { toast('复制失败，请选中路径后手动复制'); }
}

export const openFile = (path, mode = 'explorer') => act(post('/api/files/open', { path, mode }));

export function closeFolderDialog() {
  if (!saving) { ++folderSession; closeLayer($('#folderMask')); }
}

export function openFolderDialog(folder = null) {
  ++folderSession;
  editingId = folder?.id || null;
  $('#folderTitle').textContent = editingId ? '编辑文件夹' : '添加文件夹';
  $('#folderName').value = folder?.name || '';
  $('#folderPath').value = folder?.path || '';
  $('#folderGroup').value = folder?.group || '';
  $('#folderError').textContent = '';
  $('#folderGroupOptions').replaceChildren(...[...new Set((config?.folders || []).map(f => f.group).filter(Boolean))].map(group => {
    const option = el('option'); option.value = group; return option;
  }));
  openLayer($('#folderMask'), $('#folderName'));
}

function button(label, run, className = 'btn') {
  const node = el('button', className); node.type = 'button'; node.textContent = label;
  node.addEventListener('click', run); return node;
}

async function reorder(source, target) {
  if (ordering || source === target) return;
  const from = config.folders.find(f => f.id === source), to = config.folders.find(f => f.id === target);
  if (!from || !to || from.group !== to.group) return;
  const ids = config.folders.map(f => f.id), sourceIndex = ids.indexOf(source), targetIndex = ids.indexOf(target);
  ids.splice(sourceIndex, 1); ids.splice(targetIndex, 0, source);
  ordering = true;
  try {
    const response = await act(post('/api/files/folders/reorder', { ids }));
    if (response?.ok) {
      await loadFileConfig(true); toast('排序已保存');
      [...document.querySelectorAll('.folder-card')].find(card => card.dataset.folderId === source)?.querySelector('summary').focus();
    }
  } catch (error) { toast(error.message); }
  finally { ordering = false; }
}

function renderFolders() {
  if (!config) return;
  const groups = [...new Set(config.folders.map(f => f.group))];
  if (selectedGroup && !groups.includes(selectedGroup)) selectedGroup = '';
  const tabs = $('#folderGroups'); tabs.replaceChildren();
  for (const group of ['', ...groups.filter(Boolean)]) {
    const tab = button(group || '全部', () => { selectedGroup = group; renderFolders(); }, 'btn folder-tab');
    tab.setAttribute('aria-pressed', String(group === selectedGroup)); tabs.append(tab);
  }
  const query = $('#folderFilter').value.trim().toLowerCase();
  const visible = config.folders.filter(f => (!selectedGroup || f.group === selectedGroup) &&
    (f.name + ' ' + f.path).toLowerCase().includes(query));
  const list = $('#folderList'); list.replaceChildren();
  if (!visible.length) {
    const empty = el('div', 'file-empty'); empty.append(icon('folder', 32));
    const message = el('p'); message.textContent = config.folders.length ? '没有匹配的目录' : '把常用目录放在这里，一键打开';
    empty.append(message); list.append(empty); return;
  }
  for (const group of [...new Set(visible.map(f => f.group))]) {
    const section = el('section', 'folder-section');
    const heading = el('h3', 'folder-group-title');
    const members = visible.filter(f => f.group === group);
    heading.textContent = (group || '未分组') + ' · ' + members.length;
    const grid = el('div', 'folder-grid');
    const siblings = config.folders.filter(f => f.group === group);
    members.forEach(folder => {
      const card = el('article', 'folder-card'); card.dataset.folderId = folder.id;
      card.addEventListener('dragover', event => {
        if (config.folders.find(f => f.id === draggedId)?.group === folder.group) { event.preventDefault(); card.classList.add('drop-target'); }
      });
      card.addEventListener('dragleave', () => card.classList.remove('drop-target'));
      card.addEventListener('drop', event => { event.preventDefault(); card.classList.remove('drop-target'); reorder(draggedId, folder.id); });
      const head = el('div', 'folder-card-head');
      const grip = iconBtn('layout-grid', '拖动排序；也可在管理菜单中前移或后移', 'folder-grip'); grip.draggable = true;
      grip.addEventListener('dragstart', event => { draggedId = folder.id; event.dataTransfer.setData('text/plain', folder.id); event.dataTransfer.effectAllowed = 'move'; });
      grip.addEventListener('dragend', () => { draggedId = null; document.querySelectorAll('.drop-target').forEach(n => n.classList.remove('drop-target')); });
      const badge = el('span', 'folder-badge'); badge.append(icon('folder', 27));
      const title = button(folder.name, () => openFile(folder.path), 'folder-name'); title.title = folder.path;
      const copy = el('div', 'folder-copy'); const path = el('div', 'folder-path'); path.textContent = folder.path; path.title = folder.path;
      copy.append(title, path);
      head.append(grip, badge, copy);
      const menu = el('details', 'folder-menu'); const summary = el('summary', 'btn'); summary.textContent = '管理'; summary.setAttribute('aria-label', '管理 ' + folder.name);
      const actions = el('div', 'folder-menu-actions');
      actions.append(button('编辑', () => { menu.open = false; openFolderDialog(folder); }));
      const index = siblings.findIndex(f => f.id === folder.id);
      for (const [label, next] of [['前移', index - 1], ['后移', index + 1]]) {
        const move = button(label, () => reorder(folder.id, siblings[next]?.id)); move.disabled = next < 0 || next >= siblings.length; actions.append(move);
      }
      actions.append(button('移除收藏', () => {
        menu.open = false;
        openConfirm({ title: '移除收藏', bodyHtml: '移除「' + escapeHtml(folder.name) + '」的快捷入口？磁盘目录和文件会保留。', okText: '移除收藏', onOk: async () => {
          const response = await act(post('/api/files/folders/remove', { id: folder.id }));
          if (response?.ok) { await loadFileConfig(true); toast('已移除收藏'); }
        } });
      }));
      menu.append(summary, actions); head.append(menu);
      const foot = el('div', 'folder-card-foot'); const open = button('打开', () => openFile(folder.path)); open.prepend(icon('folder', 15));
      const copyButton = iconBtn('copy', '复制路径：' + folder.name); copyButton.addEventListener('click', () => copyPath(folder.path));
      foot.append(open, copyButton); card.append(head, foot); grid.append(card);
    });
    section.append(heading, grid); list.append(section);
  }
}

export function initFolders() {
  $('#railIconFolders').append(icon('folder', 19));
  $('#folderAdd').prepend(icon('plus', 16));
  $('#folderAdd').classList.add('file-page-action');
  $('.view-head').append($('#folderAdd'));
  $('#folderAdd').addEventListener('click', () => openFolderDialog());
  $('#folderRefresh').addEventListener('click', () => showFilePage('folders'));
  $('#folderFilter').addEventListener('input', renderFolders);
  $('#folderClose').addEventListener('click', closeFolderDialog);
  $('#folderCancel').addEventListener('click', closeFolderDialog);
  $('#folderMask').addEventListener('mousedown', e => { if (e.target === $('#folderMask')) closeFolderDialog(); });
  $('#folderPick').addEventListener('click', async event => {
    const session = folderSession;
    event.currentTarget.disabled = true;
    try {
      const result = await act(postWithTimeout('/api/pick', { what: 'dir' }, 195000));
      if (result?.path && session === folderSession && $('#folderMask').classList.contains('open')) {
        $('#folderPath').value = result.path;
        if (!$('#folderName').value.trim()) $('#folderName').value = result.path.replace(/[\\/]+$/, '').split(/[\\/]/).at(-1) || result.path;
      }
    } finally { $('#folderPick').disabled = false; }
  });
  $('#folderForm').addEventListener('submit', async event => {
    event.preventDefault(); if (saving) return;
    ++folderSession;
    saving = true; $('#folderSave').disabled = true; $('#folderError').textContent = '';
    try {
      const result = await post('/api/files/folders/save', { id: editingId, name: $('#folderName').value, path: $('#folderPath').value, group: $('#folderGroup').value });
      if (!result.ok) { $('#folderError').textContent = result.error; return; }
      closeLayer($('#folderMask')); await loadFileConfig(true); toast('目录已保存');
    } catch (error) { $('#folderError').textContent = error.message; }
    finally { saving = false; $('#folderSave').disabled = false; }
  });
  $('#esSettingsForm').addEventListener('submit', async event => {
    event.preventDefault(); $('#esSave').disabled = true;
    try {
      const result = await post('/api/files/settings', { esPath: $('#esPath').value });
      $('#esSettingStatus').textContent = result.ok ? '已保存' : result.error;
      if (result.ok) await loadFileConfig(true);
    } catch (error) { $('#esSettingStatus').textContent = error.message; }
    finally { $('#esSave').disabled = false; }
  });
}
