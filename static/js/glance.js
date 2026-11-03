import { $, el, setText, icon, post, act, state, currentUiTheme, applyUiTheme, toast } from './core.js';
import { glanceStatus, glanceGroups, gridNeighbor } from './glance-model.js';
import { viewPoll } from './view-poll.js';

const search = $('#glanceSearch'), host = $('#glanceGroups'), menu = $('#glanceMenu');
const tiles = new Map(), sections = new Map(), busy = new Set();
let apps = new Map(), selected, menuId, connected = false;
$('#searchIcon').append(icon('search', 15));

function createTile(id) {
  const tile = el('button', 'glance-tile');
  tile.type = 'button';
  tile.dataset.id = id;
  tile.setAttribute('aria-haspopup', 'menu');
  const face = el('span', 'glance-face'), dot = el('i'), art = el('span', 'glance-art');
  face.append(art, dot);
  tile.append(face, el('span', 'glance-name'));
  return tile;
}
function updateTile(tile, app) {
  const [status, label] = glanceStatus(app);
  tile.dataset.status = status;
  const name = app.name || '未命名', action = openLabel(app);
  tile.title = name + ' · ' + label + ' · ' + action;
  tile.setAttribute('aria-label', tile.title);
  setText(tile.lastChild, name);
  const art = tile.querySelector('.glance-art');
  const glyph = app.glyph && window.LUCIDE?.[app.glyph] ? app.glyph : '';
  const src = app.icon || (!glyph && app.favicon);
  const initial = [...name][0].toLocaleUpperCase();
  const key = src ? 'img:' + src : glyph ? 'glyph:' + glyph : 'text:' + initial;
  if (art.dataset.key !== key) {
    art.dataset.key = key;
    if (src) {
      const img = new Image(); img.alt = '';
      img.onerror = () => { if (art.firstChild === img) art.textContent = initial; };
      img.src = src;
      art.replaceChildren(img);
    } else if (glyph) art.replaceChildren(icon(glyph, 30));
    else art.textContent = initial;
  }
}
function render() {
  const focused = document.activeElement.closest('.glance-tile')?.dataset.id;
  const groups = glanceGroups([...apps.values()], search.value);
  const visible = new Set([...groups.values()].flat().map(a => a.id));
  if (!visible.has(selected)) selected = visible.values().next().value;
  if (menuId && !visible.has(menuId)) closeMenu(true);
  let s = 0;
  for (const [category, items] of groups) {
    let section = sections.get(category);
    if (!section) {
      section = el('section', 'glance-section');
      const title = el('h2'); title.append(document.createTextNode(category), el('small', 'mono'));
      section.append(title, el('div', 'glance-grid'));
      sections.set(category, section);
    }
    setText(section.firstChild.lastChild, String(items.length));
    section.style.setProperty('--group-columns', items.length);
    if (host.children[s] !== section) host.insertBefore(section, host.children[s] || null);
    s++;
    const grid = section.lastChild;
    items.forEach((app, i) => {
      let tile = tiles.get(app.id);
      if (!tile) { tile = createTile(app.id); tiles.set(app.id, tile); }
      updateTile(tile, app);
      tile.tabIndex = app.id === selected ? 0 : -1;
      if (grid.children[i] !== tile) grid.insertBefore(tile, grid.children[i] || null);
    });
  }
  for (const [id, tile] of tiles) {
    if (!visible.has(id)) tile.remove();
    if (!apps.has(id)) tiles.delete(id);
  }
  for (const [key, section] of sections) if (!groups.has(key)) { section.remove(); sections.delete(key); }
  if (focused && document.activeElement === document.body) (tiles.get(selected) || search).focus();
  setText($('#glanceCount'), search.value ? visible.size + ' / ' + apps.size : apps.size + ' 个应用');
  $('#glanceEmpty').hidden = !!visible.size;
  setText($('#glanceEmpty'), apps.size ? '没有匹配的应用' : '启动台暂无应用');
  if (menuId) syncMenu(apps.get(menuId));
}

const polling = viewPoll({ url: '/api/state', interval: 3000, timeout: 5000,
  onData(data) {
    state.data = data; connected = true;
    $('#glanceConnection').hidden = true;
    apps = new Map((data.apps || []).map(a => [a.id, a]));
    applyUiTheme(currentUiTheme());
    render();
  },
  onError() {
    connected = false;
    setText($('#glanceConnection'), '连接中断，正在重试…');
    $('#glanceConnection').hidden = false;
    if (menuId) syncMenu(apps.get(menuId));
  },
});
const syncVisibility = () => polling.setActive(!document.hidden);
document.addEventListener('visibilitychange', syncVisibility);
syncVisibility();
const media = matchMedia('(prefers-color-scheme: dark)');
function syncMode() {
  const mode = localStorage.getItem('console-theme');
  document.documentElement.dataset.theme = ['light', 'dark'].includes(mode) ? mode : media.matches ? 'dark' : 'light';
}
media.addEventListener('change', syncMode);
window.addEventListener('storage', e => { if (!e.key || e.key === 'console-theme') syncMode(); });
search.addEventListener('input', render);
host.addEventListener('focusin', e => {
  const tile = e.target.closest('.glance-tile');
  if (tile) {
    if (tiles.has(selected)) tiles.get(selected).tabIndex = -1;
    selected = tile.dataset.id; tile.tabIndex = 0;
  }
});

function openLabel(app) { return app.running ? '前台' : app.kind === 'task' ? '运行' : '启动'; }
function available(action, app) {
  if (action === 'show' || action === 'log') return true;
  if (!connected || busy.has(app.id) || app.statusKnown === false) return false;
  if (action === 'stop') return app.running;
  const canStart = app.canStart !== false && !app.health?.blocking;
  if (action === 'restart') return app.running && canStart;
  return app.running || canStart;
}
function showMain(id, action) {
  try {
    if (window.opener && !window.opener.closed && typeof window.opener.__showGlanceApp === 'function') {
      window.opener.__showGlanceApp(id, action);
      window.opener.focus();
      return;
    }
  } catch { /* A former opener may now host another origin. */ }
  const url = '/#' + (action === 'log' ? 'log' : 'app') + '=' + encodeURIComponent(id);
  if (!window.open(url, 'console-main')) toast('请允许弹出总控台窗口');
}
async function operate(id, action) {
  const app = apps.get(id);
  if (!app) return;
  if (action === 'show' || action === 'log') return showMain(id, action);
  if (!available(action, app)) return toast('当前状态无法执行此操作');
  if (['stop', 'restart'].includes(action) &&
      !window.confirm('确定' + (action === 'stop' ? '停止' : '重启') + '「' + app.name + '」？')) return;
  busy.add(id);
  try {
    const focus = action === 'open' && app.running;
    const result = await act(focus ? post('/api/ops/window', { appId: id, operation: 'focus' })
      : post('/api/apps/' + encodeURIComponent(id) + '/' + (action === 'open' ? 'start' : action)));
    if (result?.ok && !focus) polling.refresh();
  } finally { busy.delete(id); }
}
host.addEventListener('click', e => {
  const tile = e.target.closest('.glance-tile');
  if (tile) operate(tile.dataset.id, 'open');
});
function syncMenu(app) {
  for (const b of menu.children) {
    b.disabled = !available(b.dataset.action, app);
    if (b.dataset.action === 'open') setText(b, openLabel(app));
  }
}
function openMenu(tile, x, y) {
  menuId = tile.dataset.id;
  syncMenu(apps.get(menuId));
  menu.hidden = false;
  menu.style.left = Math.max(0, Math.min(x, innerWidth - menu.offsetWidth)) + 'px';
  menu.style.top = Math.max(0, Math.min(y, innerHeight - menu.offsetHeight)) + 'px';
  menu.querySelector(':enabled').focus();
}
function closeMenu(restore) {
  if (!menuId) return;
  const tile = tiles.get(menuId);
  menuId = null; menu.hidden = true;
  if (restore) (tile?.isConnected ? tile : search).focus();
}
host.addEventListener('contextmenu', e => {
  const tile = e.target.closest('.glance-tile');
  if (tile) { e.preventDefault(); openMenu(tile, e.clientX, e.clientY); }
});
menu.addEventListener('click', e => {
  const action = e.target.closest('button')?.dataset.action, id = menuId;
  if (action) { closeMenu(true); operate(id, action); }
});
document.addEventListener('pointerdown', e => { if (!menu.contains(e.target)) closeMenu(false); });
document.addEventListener('keydown', e => {
  if (e.isComposing || e.keyCode === 229) return;
  if (menuId) {
    if (e.key === 'Tab' || e.key === 'Escape') {
      if (e.key === 'Escape') e.preventDefault();
      closeMenu(true);
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const items = [...menu.querySelectorAll(':enabled')], i = items.indexOf(document.activeElement);
      items[(i + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length].focus();
    }
    return;
  }
  if (e.key === 'Escape') { e.preventDefault(); search.value = ''; render(); return; }
  const tile = e.target.closest('.glance-tile');
  if (tile && (e.key === 'ContextMenu' || (e.key === 'F10' && e.shiftKey))) {
    e.preventDefault(); const rect = tile.getBoundingClientRect(); openMenu(tile, rect.left, rect.bottom);
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
  if (e.key === '/' && e.target !== search) { e.preventDefault(); search.focus(); }
  if (e.target === search && e.key === 'ArrowDown') { e.preventDefault(); tiles.get(selected)?.focus(); }
  if (!tile || !['ArrowRight', 'ArrowLeft', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
  e.preventDefault();
  const rows = []; let top;
  for (const t of host.querySelectorAll('.glance-tile')) {
    const y = t.getBoundingClientRect().top;
    if (y !== top) { rows.push([]); top = y; }
    rows.at(-1).push(t.dataset.id);
  }
  tiles.get(gridNeighbor(rows, tile.dataset.id, e.key))?.focus();
});
