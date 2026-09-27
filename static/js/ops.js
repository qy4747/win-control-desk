'use strict';
import { $, el, icon, setText, state, post, postWithTimeout, put, act, toast, openLayer, closeLayer, activeLayer, escapeHtml } from './core.js';
import { openConfirm, openLogs, openAppModal, getIconVer } from './overlays.js';
import { preferredOpenPort, portIsOpenable } from './ports.js';
import { topResources } from './resources.js';
import { packageState, bindPackagePress } from './packages.js';
import { bindPresetHover, renderPresetHover } from './preset-hover.js';
import { initTagDrawer } from './tag-drawer.js';

const panel = el('div', 'modal-mask ops-mask');
panel.id = 'opsMask'; panel.inert = true; panel.setAttribute('aria-hidden', 'true');
const dialog = el('section', 'ops-panel');
dialog.setAttribute('role', 'dialog'); dialog.setAttribute('aria-modal', 'true'); dialog.setAttribute('aria-labelledby', 'opsTitle');
const heading = el('h3'); heading.id = 'opsTitle';
const close = button('关闭', () => closeOps());
const head = el('header', 'ops-head'); head.append(heading, close);
const content = el('div', 'ops-content'); dialog.append(head, content); panel.append(dialog); document.body.append(panel);
panel.addEventListener('mousedown', e => { if (e.target === panel) closeOps(); });
let detailId = null, detailStatus = null, detailEvents = null, config = null, alertTarget = null;
const history = [];
let hasParentLayer = false, pageKey = null;
const bubble = el('section', 'ops-alert-popover');
bubble.setAttribute('popover', 'auto'); bubble.setAttribute('role', 'dialog'); bubble.setAttribute('aria-label', '异常与临时基线');
document.body.append(bubble);
let bubbleAlert = null, bubbleAnchor = null;

function placeBubble() {
  if (!bubble.matches(':popover-open') || !bubbleAnchor?.isConnected) return;
  const r = bubbleAnchor.getBoundingClientRect();
  bubble.style.left = Math.max(8, Math.min(r.left, innerWidth - bubble.offsetWidth - 8)) + 'px';
  bubble.style.top = Math.max(8, Math.min(r.bottom + 8, innerHeight - bubble.offsetHeight - 8)) + 'px';
}
function closeBubble() { if (bubble.matches(':popover-open')) bubble.hidePopover(); bubbleAlert = null; }
function openAlertBubble(target, anchor, key = null) {
  const alerts = target === 'system' ? (state.data.alerts || []).filter(a => a.target === 'system' && !a.ignored) : appAlerts(state.data.apps.find(a => a.id === target));
  if (!alerts.length) return openAlerts(target);
  closeBubble(); bubble.replaceChildren(); bubbleAnchor = anchor;
  bubbleAlert = alerts.find(a => a.key === key) || alerts[0];
  if (alerts.length > 1) {
    const choice = select(bubble, '选择异常', alerts.map(a => [a.key, a.title]), bubbleAlert.key);
    choice.addEventListener('change', () => { bubbleAlert = alerts.find(a => a.key === choice.value); body.replaceChildren(); alertControls(body, bubbleAlert); placeBubble(); });
  }
  const body = el('div'); bubble.append(body); alertControls(body, bubbleAlert);
  bubble.append(button('查看详情', () => { closeBubble(); openAlerts(target); }, 'btn'));
  bubble.showPopover(); placeBubble(); bubble.querySelector('input:not(:disabled), select, button')?.focus();
}
function alertValue(a, value) {
  if (typeof value !== 'number') return String(value ?? '未知');
  if (a.metric?.includes('Bytes') || a.key?.endsWith(':memory')) return bytes(value) + (a.metric?.endsWith('PerSec') ? '/s' : '');
  return ['cpu', 'memoryPercent', 'gpuPercent', 'diskFreePercent'].includes(a.metric) ? value.toFixed(1) + '%' : String(value);
}
function alertControls(parent, a) {
  const title = el('strong'); title.textContent = a.title; parent.append(title);
  note(parent, a.unknown ? '等待可靠的采集结果' : '当前 ' + alertValue(a, a.value) + (a.threshold != null ? ' · 原阈值 ' + alertValue(a, a.threshold) : ''));
  if (!a.incident) return;
  let threshold = null, scale = a.metric?.includes('Bytes') || a.key?.endsWith(':memory') ? 1048576 : 1;
  if (a.threshold != null) {
    const below = a.comparison === 'below';
    let proposed = below ? Math.min(a.value, a.threshold) * .9 : Math.max(a.value, a.threshold) * 1.1;
    if (['cpu', 'memoryPercent', 'gpuPercent', 'diskFreePercent'].includes(a.metric)) proposed = Math.min(100, proposed);
    threshold = field(parent, '临时阈值（' + (scale > 1 ? 'MiB' + (a.metric?.endsWith('PerSec') ? '/秒' : '') : '%') + '）', Number((proposed / scale).toPrecision(4)), 'number');
    threshold.disabled = !!a.unknown;
    note(parent, '超过临时阈值仍提醒；满足原基线恢复条件后自动结束。');
  } else note(parent, '临时接受当前这次异常，恢复后再次发生仍提醒。');
  async function accept(mode) {
    const r = await act(post('/api/ops/alerts/accept', { key: a.key, incident: a.incident, mode, threshold: threshold ? Number(threshold.value) * scale : null }));
    if (r?.ok) { closeBubble(); toast(mode === 'permanent' ? '已永久忽略，可在设置中心撤销' : '已临时接受'); await window.__poll(); }
  }
  const temporary = button('临时接受', () => accept('temporary'), 'btn btn-accent'); temporary.disabled = !!a.unknown;
  const actions = el('div', 'ops-alert-actions'); actions.append(temporary, button('永久忽略…', () => {
    closeBubble(); openConfirm({ title: '永久忽略此规则', bodyHtml: escapeHtml(a.title) + '<br>仅停止此对象这条规则的提醒，直到在设置中心手动撤销。实际状态和操作限制保持不变。', okText: '永久忽略', onOk: () => accept('permanent') });
  })); parent.append(actions);
}
function openAcceptedAlerts() {
  if (!show('临时接受与永久忽略')) return;
  const saved = Object.entries(state.data.alertOverrides || {});
  if (!saved.length) note(content, '没有已接受或永久忽略的规则');
  for (const [key, rule] of saved) {
    const row = el('article', 'ops-alert-item'); const title = el('strong'); title.textContent = rule.title; row.append(title);
    note(row, rule.mode === 'permanent' ? '永久忽略 · 手动撤销后重新提醒' : '临时接受 · 满足原基线恢复条件后结束');
    row.append(button('撤销', async () => { const r = await act(post('/api/ops/alerts/accept', { key, mode: 'revoke' })); if (r?.ok) { await window.__poll(); row.remove(); } })); content.append(row);
  }
}

function button(label, run, cls = 'btn') {
  const b = el('button', cls); b.type = 'button'; b.textContent = label;
  b.addEventListener('click', async () => {
    if (b.disabled || b.getAttribute('aria-busy') === 'true') return;
    b.setAttribute('aria-busy', 'true');
    try { await run(); } catch (e) { toast(e.message); } finally { b.removeAttribute('aria-busy'); }
  });
  return b;
}
function field(parent, label, value = '', type = 'text') {
  const wrap = el('label', 'ops-field'); const name = el('span'); name.textContent = label;
  const input = el(type === 'textarea' ? 'textarea' : 'input');
  input.setAttribute('aria-label', label);
  if (type !== 'textarea') input.type = type;
  input.value = value ?? ''; if (type === 'number') { input.min = '0'; input.step = 'any'; }
  if (type === 'checkbox') input.checked = !!value;
  wrap.append(name, input); parent.append(wrap); return input;
}
function select(parent, label, options, value) {
  const wrap = el('label', 'ops-field'); const name = el('span'); name.textContent = label;
  const input = el('select');
  input.setAttribute('aria-label', label);
  for (const [key, title] of options) { const o = el('option'); o.value = key; o.textContent = title; input.append(o); }
  input.value = value; wrap.append(name, input); parent.append(wrap); return input;
}
function section(parent, label, expanded = false) {
  const d = el('details', 'ops-section'); d.open = expanded;
  const s = el('summary'); s.textContent = label; d.append(s); parent.append(d); return d;
}
function note(parent, text) { const p = el('p', 'hint'); p.textContent = text; parent.append(p); return p; }
function show(title, replace = false, key = null) {
  closeBubble();
  if (!panel.classList.contains('open')) hasParentLayer = !!activeLayer();
  const previousIndex = replace || key == null ? -1 : history.findIndex(entry => entry.pageKey === key);
  if (previousIndex >= 0) { while (history.length > previousIndex + 1) history.pop(); closeOps(); return false; }
  if (panel.classList.contains('open') && !replace) history.push({
    title: heading.textContent, nodes: [...content.childNodes], scroll: content.scrollTop,
    focus: document.activeElement, detailId, detailStatus, detailEvents, alertTarget, pageKey,
  });
  if (history.length > 8) history.shift();
  pageKey = key; detailId = null; alertTarget = null; heading.textContent = title; content.replaceChildren();
  close.textContent = history.length || hasParentLayer ? '返回' : '关闭';
  openLayer(panel, close);
  return true;
}
export function closeOps() {
  const previous = history.pop();
  if (previous) {
    heading.textContent = previous.title; content.replaceChildren(...previous.nodes);
    ({ detailId, detailStatus, detailEvents, alertTarget, pageKey } = previous);
    content.scrollTop = previous.scroll;
    close.textContent = history.length || hasParentLayer ? '返回' : '关闭';
    openLayer(panel, previous.focus || close);
    renderDetail();
  } else { closeLayer(panel); content.replaceChildren(); detailId = null; alertTarget = null; }
}
export function bytes(n) {
  if (n == null || !Number.isFinite(n)) return '不可用';
  for (const [unit, scale] of [['GiB', 1073741824], ['MiB', 1048576], ['KiB', 1024]]) if (n >= scale) return (n / scale).toFixed(1) + ' ' + unit;
  return Math.round(n) + ' B';
}
const pct = n => n == null ? '不可用' : n.toFixed(1) + '%';
const optional = input => input.value.trim() === '' ? null : Number(input.value);
const probeNames = { 'not-configured': '接口未配置探测', stopped: '接口未探测', pending: '接口等待探测', ok: '接口可用', error: '接口不可用' };
const windowActions = [['window:focus', '前台']];

function actionAvailable(app, action) {
  const when = action.when || 'always';
  return when === 'always' || (app.statusKnown !== false && (when === 'running' ? !!app.running : !app.running));
}

function cardButtonSpecs(app) {
  const fixed = ['toggle', (app.kind || 'service') === 'service' ? 'web' : 'window:focus'];
  const configured = (app.cardButtons ?? defaultButtons(app)).filter(b => !fixed.includes(b.action)
    && !['start', 'stop', 'window:focus', 'window:pin', 'window:unpin', 'window:topmost'].includes(b.action));
  const features = configured.filter(b => b.placement !== 'menu').slice(0, 2);
  return [...fixed.map(action => ({ action, placement: action === 'toggle' ? 'primary' : 'card', when: 'always' })),
    ...features.map(spec => ({ ...spec, placement: 'card' })),
    ...configured.filter(spec => !features.includes(spec)).map(spec => ({ ...spec, placement: 'menu' }))];
}

async function flipCard(card, open, returnFocus = true) {
  const x = card._ops;
  if (x.flipping || x.menu.open === open) return;
  x.flipping = true;
  const motion = !matchMedia('(prefers-reduced-motion: reduce)').matches;
  const appearance = motion ? getComputedStyle(card) : null;
  const pose = side => appearance.getPropertyValue('--card-flip-' + side).trim() || 'none';
  const timing = phase => ({
    duration: parseFloat(appearance.getPropertyValue('--card-flip-' + phase + '-ms')) || 0,
    easing: appearance.getPropertyValue('--card-flip-' + phase + '-easing').trim() || 'linear',
  });
  let animation, incomingStart;
  try {
    if (motion) {
      const outgoing = timing('out');
      animation = (x.menu.open ? x.body : x.front).animate([{ transform: pose('flat') }, { transform: pose(open ? 'right' : 'left') }], { ...outgoing, fill: 'forwards' });
      await animation.finished;
      incomingStart = animation.startTime + outgoing.duration;
    }
    x.menu.open = open;
    syncCardFace(card);
    animation?.cancel();
    if (motion) {
      animation = (open ? x.body : x.front).animate([{ transform: pose(open ? 'left' : 'right') }, { transform: pose('flat') }], { ...timing('in'), fill: 'both' });
      // Continue the same timeline: a new pending start would hold the edge-on face for extra frames.
      animation.startTime = incomingStart;
      await animation.finished;
    }
    if (open || returnFocus) {
      const toggle = x.menu.querySelector('summary');
      (toggle.getClientRects().length ? toggle : card).focus({ preventScroll: true });
    }
  } finally { animation?.cancel(); x.flipping = false; }
}
function syncCardFace(card) {
  const x = card._ops;
  const toggle = x.menu.querySelector('summary');
  toggle.textContent = x.menu.open ? '返回' : '翻面';
  toggle.title = x.menu.open ? '返回正面（也可点击卡片空白处）' : '翻到背面操作（也可点击卡片空白处）';
  toggle.setAttribute('aria-label', toggle.title + '：' + card._r.name.textContent);
  for (const child of card.children) if (child !== x.menu && !child.classList.contains('app-head')) child.inert = x.menu.open;
  if (x.menu.open) {
    document.querySelectorAll('.ops-more[open]').forEach(other => { if (other !== x.menu) flipCard(other.closest('.app-card'), false, false); });
  }
}

export function updateCardExtras(card, app) {
  if (!card._ops) {
    const resources = el('div', 'ops-card-resources mono');
    const kind = el('span', 'ops-card-kind'); card.querySelector('.app-head').append(kind);
    const summary = el('div', 'ops-card-status');
    const alert = button('', () => openAlertBubble(card.dataset.key, alert), 'ops-alert-badge');
    const notice = el('div', 'ops-card-notice'); notice.append(summary, alert);
    card.querySelector('.app-icon').classList.add('ops-drag-handle');
    const menu = el('details', 'ops-more'); const title = el('summary', 'btn'); title.textContent = '翻面'; title.title = '点击卡片空白处也可翻面'; title.setAttribute('aria-label', '翻到背面操作：' + app.name);
    const body = el('div', 'ops-menu');
    const actions = el('div', 'ops-back-actions');
    const old = card.querySelector('.app-sub-actions'); actions.append(old);
    const custom = el('div', 'ops-custom'); actions.append(custom, button('卡片详情', () => { menu.open = false; openDetails(card.dataset.key); }), button('编辑卡片按钮', () => { menu.open = false; openButtons(card.dataset.key); }));
    body.append(actions); menu.append(title, body);
    body.append(card._r.primary); card._r.primary.classList.add('ops-internal-toggle');
    const buttons = el('div', 'ops-card-buttons'); card.querySelector('.app-actions').append(buttons);
    const front = el('div', 'ops-card-front'); front.append(card.querySelector('.app-cmd'), resources, notice, card.querySelector('.app-actions')); card.append(front, menu);
    card._ops = { kind, resources, summary, alert, custom, buttons, menu, front, body, signature: '' };
    title.addEventListener('click', e => { e.preventDefault(); flipCard(card, !menu.open); });
    menu.addEventListener('toggle', () => syncCardFace(card));
    card.setAttribute('aria-description', '点击非按钮区域或按 Enter 翻面，空格键开始排序');
    card.addEventListener('click', e => {
      if (e.defaultPrevented || e.target.closest('button, [role="button"], a, summary, input, select, textarea, label, [contenteditable]')) return;
      if (window.getSelection()?.isCollapsed === false) return;
      flipCard(card, !menu.open);
    });
    card.addEventListener('keydown', e => {
      if (e.target === card && e.key === 'Enter' && !e.defaultPrevented) {
        e.preventDefault(); flipCard(card, !menu.open);
      }
    });
  }
  const x = card._ops;
  setText(x.kind, { desktop: '[应用]', task: '[Shell]', service: '[服务]' }[app.kind || 'service']);
  setText(x.resources, app.running ? 'CPU ' + pct(app.resources?.cpu) + ' · 内存 ' + bytes(app.resources?.memoryBytes) : 'CPU — · 内存 —');
  x.resources.title = x.resources.textContent;
  x.resources.hidden = !app.running && app.statusKnown !== false;
  const alerts = appAlerts(app);
  setText(x.summary, app.associationDetail || (app.statusKnown === false ? '等待可靠的采集结果' : alerts.length ? alerts[0].title.replace(app.name + ' · ', '') : app.associationState === 'pending' ? '请在详情中确认运行关联' : app.category || ''));
  x.summary.classList.toggle('is-alert', !!alerts.length);
  setText(x.alert, '异常 ' + alerts.length);
  x.alert.setAttribute('aria-label', app.name + '：' + alerts.length + ' 项异常，查看原因');
  x.alert.title = alerts.map(a => a.title).join('；');
  x.alert.hidden = !alerts.length;
  const signature = JSON.stringify([app.actions, app.stopAction, app.cardButtons, app.windowBinding, app.running, app.backgroundOnly, app.statusKnown, app.canStart, app.health, app.listening, app.portConflict, app.portOccupied, app.ports, app.port, app.kind, card._r.primary.disabled, card._r.restart.disabled]);
  if (x.signature !== signature) {
    x.signature = signature; x.custom.replaceChildren(); x.buttons.replaceChildren();
    const specs = cardButtonSpecs(app).filter(spec =>
      !((spec.when === 'running' && !app.running) || (spec.when === 'stopped' && app.running)));
    const main = specs[0];
    const visible = specs.filter(spec => spec.placement !== 'menu');
    for (const spec of specs) {
      const action = app.actions?.find(a => 'custom:' + a.id === spec.action);
      const portLabel = preferredOpenPort(app) ? ':' + preferredOpenPort(app) : '前台';
      const labels = { toggle: app.running && !app.backgroundOnly ? '关闭' : '打开', restart: '重启', web: (app.kind || 'service') === 'service' ? portLabel : '打开 Web', logs: '日志', details: '详情', ...Object.fromEntries(windowActions) };
      const b = button(spec.name || action?.name || labels[spec.action] || '操作已移除', async () => {
        const current = state.data.apps.find(a => a.id === app.id); if (!current) return;
        if (action) return executeAction(app.id, action);
        if (spec.action.startsWith('window:')) return executeWindow(app.id, spec.action.split(':')[1]);
        if (spec.action === 'toggle' || (spec.action === 'start' && !current.running) || (spec.action === 'stop' && current.running)) card._r.primary.click();
        else if (spec.action === 'web') {
          if ((current.kind || 'service') === 'service') return executeWindow(app.id, 'focus');
          card._r.stPort.click();
        }
        else if (spec.action === 'restart') card._r.restart.click();
        else if (spec.action === 'logs') card._r.logs.click();
        else if (spec.action === 'details') openDetails(app.id);
      }, 'btn' + (spec === main ? ' btn-accent' : ''));
      b.disabled = !actionAvailable(app, spec) || (action ? !actionAvailable(app, action) :
        spec.action.startsWith('window:') ? !app.running || app.backgroundOnly || app.statusKnown === false || state.data.platform !== 'win32' || (spec.action !== 'window:focus' && !app.windowBinding) :
        spec.action.startsWith('custom:') ? true :
        spec.action === 'web' ? !app.running || app.statusKnown === false || (!app.windowBinding && !portIsOpenable(app)) :
        spec.action === 'restart' ? !app.running || card._r.restart.disabled || app.statusKnown === false :
        spec.action === 'toggle' ? card._r.primary.disabled : false);
      if (b.disabled) b.title = '当前状态不可执行，请查看卡片详情';
      else if (spec.action === 'web') b.title = '唤到前台；网页窗口未打开时打开网页';
      else if (spec.action === 'window:focus' && !app.windowBinding) b.title = '选择要唤到前台的窗口';
      (visible.includes(spec) ? x.buttons : x.custom).append(b);
    }
    if (app.running) x.custom.append(button('强制结束…', () => openConfirm({
      title: '强制结束 ' + app.name,
      bodyHtml: '强制结束已验证的应用进程，未保存的数据可能丢失。', okText: '强制结束',
      onOk: async () => { await act(post('/api/ops/force', { appId: app.id, confirmed: true })); window.__poll(); },
    }), 'btn danger'));
  }
  card.classList.toggle('has-alert', !!alerts.length);
}

function defaultButtons(app) {
  const isService = (app.kind || 'service') === 'service';
  const actions = ['toggle', isService ? 'web' : 'window:focus', ...(!isService && app.port ? ['web'] : []),
    ...(app.actions || []).filter(a => a.id !== app.stopAction).map(a => 'custom:' + a.id), 'details', 'logs'];
  return actions.map((action, i) => ({ action, name: '',
    placement: i === 0 ? 'primary' : i < 4 ? 'card' : 'menu', when: 'always' }));
}

function openButtons(id) {
  const app = state.data.apps.find(a => a.id === id); if (!app) return;
  if (!show(app.name + ' · 编辑卡片按钮')) return;
  note(content, '顶部固定“关闭 / 打开”，右侧服务显示端口并打开网页，普通应用显示“前台”。下方按顺序显示两个软件专用按钮，其余放背面。显示时机沿用原有规则；目录入口默认始终可用，依赖应用的命令在详情中将“可用状态”设为“运行中”。');
  const list = el('div'); content.append(list); const rows = [];
  const options = [...((app.kind || 'service') === 'service' ? [] : [['web', '打开 Web']]), ['restart', '重启'], ['logs', '日志'], ['details', '详情'], ...(state.data.platform === 'win32' ? windowActions.slice(1) : []), ...(app.actions || []).map(a => ['custom:' + a.id, a.name])];
  function add(spec = { action: 'details', placement: 'card' }) {
    const row = el('section', 'ops-button-editor'); list.append(row);
    const action = select(row, '动作', options, spec.action);
    const name = field(row, '按钮名称（可留空）', spec.name || '');
    const placement = select(row, '显示位置', [['card', '下方按钮（前两个）'], ['menu', '背面操作']], spec.placement);
    const when = select(row, '显示时机', [['always', '始终'], ['running', '运行中'], ['stopped', '停止时']], spec.when || 'always');
    const tools = el('div', 'ops-editor-tools');
    tools.append(button('上移', () => { if (row.previousElementSibling) list.insertBefore(row, row.previousElementSibling); }), button('下移', () => { if (row.nextElementSibling) list.insertBefore(row.nextElementSibling, row); }), button('移除', () => { rows.splice(rows.findIndex(entry => entry.row === row), 1); row.remove(); })); row.append(tools);
    rows.push({ row, read: () => ({ action: action.value, name: name.value, placement: placement.value, when: when.value }) });
  }
  cardButtonSpecs(app).slice(2).forEach(add);
  content.append(button('添加按钮', () => add()), button('保存按钮', async () => {
    const cardButtons = [...list.children].map(row => rows.find(r => r.row === row).read());
    const r = await act(put('/api/apps/' + id, { cardButtons }));
    if (r && r.ok !== false) { closeOps(); toast('卡片按钮已保存'); window.__poll(); }
  }, 'btn btn-accent'), button('恢复默认', async () => { const r = await act(put('/api/apps/' + id, { cardButtons: null })); if (r && r.ok !== false) { closeOps(); window.__poll(); } }));
}

function appAlerts(app) {
  const alerts = [...(app?.alerts || [])];
  if (app?.health?.blocking && app.canStart !== false && !alerts.some(a => a.key?.endsWith(':config'))) {
    for (const issue of app.health.issues || []) alerts.push({ title: issue.title, value: issue.detail || issue.message || '请检查启动配置' });
  }
  return alerts.filter(a => !a.ignored);
}
function openAlerts(target) {
  const app = state.data?.apps.find(a => a.id === target);
  if (!show(target === 'system' ? '系统状态与异常' : (app?.name || '应用') + ' · 异常', false, 'alerts:' + target)) return;
  alertTarget = target; renderAlerts();
}
function renderAlerts() {
  if (!alertTarget) return;
  // 轮询更新读数时复用折叠分组；标题及目录完整路径在此面板内唯一。
  const sections = new Map([...content.querySelectorAll('.ops-section')]
    .map(node => [node.firstElementChild.textContent, node]));
  const focused = content.contains(document.activeElement) ? document.activeElement : null;
  const scroll = content.scrollTop;
  const data = state.data || {};
  const app = data.apps?.find(a => a.id === alertTarget);
  const alerts = alertTarget === 'system' ? (data.alerts || []).filter(a => a.target === 'system' && !a.ignored) : appAlerts(app);
  content.replaceChildren();
  if (data.stale || data.degraded || app?.statusKnown === false) note(content, '采集数据不完整，以下状态可能尚未更新。');
  if (!alerts.length) note(content, '当前没有异常');
  for (const a of alerts) {
    const item = el('article', 'ops-alert-item');
    const title = el('strong'); title.textContent = a.title; item.append(title);
    const rule = data.rules?.find(r => a.key?.startsWith('rule:' + r.id + ':'));
    const value = typeof a.value === 'number' ? (rule?.metric?.includes('Bytes') || a.key?.endsWith(':memory') ? bytes(a.value) + (rule?.metric?.endsWith('PerSec') ? '/s' : '') : a.value.toFixed(1) + '%') : a.value;
    note(item, (a.unknown ? '等待新的采集结果' : '当前：' + (value ?? '未知')) + (a.muted ? ' · 已静音' : ''));
    if (a.incident) { const edit = button('处理异常', () => openAlertBubble(alertTarget, edit, a.key)); item.append(edit); }
    const event = data.events?.find(e => e.key === a.key && e.phase === 'alert');
    if (event) note(item, '发生于 ' + new Date(event.at * 1000).toLocaleString());
    content.append(item);
  }
  if (alertTarget === 'system') {
    const s = data.system || {};
    const readings = section(content, '资源读数');
    note(readings, 'CPU ' + pct(s.cpu) + ' · 内存 ' + pct(s.memoryPercent) + '\n磁盘写入 ' + bytes(s.diskWriteBytesPerSec) + '/s');
    for (const d of s.disks || []) note(readings, d.path + ' 剩余 ' + bytes(d.freeBytes) + ' / ' + bytes(d.totalBytes));
    renderDirectorySnapshots(content, data);
    content.append(button('配置目录定时快照', () => openRules()));
  } else if (app) content.append(button('查看应用详情', () => openDetails(app.id)));
  content.append(button('设置长期静音规则', () => alertTarget === 'system' ? openRules() : openDetails(app.id)));
  const events = section(content, '最近事件');
  note(events, (data.events || []).filter(e => e.target === alertTarget).slice(0, 30).map(e => new Date(e.at * 1000).toLocaleString() + ' · ' + e.title + ' · ' + e.detail).join('\n') || '暂无事件');
  for (const updated of content.querySelectorAll('.ops-section')) {
    const previous = sections.get(updated.firstElementChild.textContent);
    if (!previous) continue;
    previous.replaceChildren(previous.firstElementChild, ...[...updated.children].slice(1));
    updated.replaceWith(previous);
  }
  if (focused?.isConnected) focused.focus({ preventScroll: true });
  content.scrollTop = scroll;
}

async function executeAction(appId, action) {
  const app = state.data.apps.find(a => a.id === appId);
  action = app?.actions?.find(a => a.id === action.id);
  if (!action || !actionAvailable(app, action)) { toast('当前状态不可执行'); return; }
  if (action.id === app.stopAction) {
    openConfirm({ title: '关闭 ' + app.name,
      bodyHtml: '执行此应用配置的关闭操作；进程关闭脚本会直接结束已核实的实例，请先保存工作。', okText: '确认关闭',
      onOk: async () => { await act(post('/api/apps/' + appId + '/stop')); window.__poll(); } });
    return;
  }
  if (action.type === 'url') { window.open(action.url, '_blank', 'noopener,noreferrer'); return; }
  const result = await act(postWithTimeout('/api/ops/action', { appId, actionId: action.id }, (action.timeoutSec || 30) * 1000 + 10000));
  if (result?.ok) toast(action.type === 'location' ? '已发出打开请求' : '操作已完成');
  window.__poll();
}

export async function executeWindow(appId, operation) {
  const app = state.data.apps.find(a => a.id === appId);
  if (!app?.running || app.statusKnown === false) { toast('应用未运行或状态未知'); return; }
  if (!app.windowBinding && operation === 'focus' && (app.kind || 'service') !== 'service') return openWindowPicker(appId);
  const r = await act(post('/api/ops/window', { appId, operation }));
  if (r?.ok) {
    toast(r.opened ? '已发出网页打开请求' : '已唤到前台');
    await window.__poll();
    renderDetail();
  }
}

async function openWindowPicker(id) {
  if (!show('选择要关联的窗口')) return;
  note(content, '选择 GUI 或承载 TUI 的终端窗口。应用重启后按窗口特征重新匹配；终端及外部窗口要求标题匹配，多个候选时再选择。操作作用于整个窗口及其所有标签页，不改变其中进程的归属。');
  const search = field(content, '搜索窗口标题、路径或 PID');
  const results = el('div', 'ops-discovery'); content.append(results);
  let items = [];
  async function bind(selection) {
    const r = await act(post('/api/ops/window/bind', { appId: id, window: selection }));
    if (r?.ok) { await window.__poll(); closeOps(); toast(selection ? '窗口已关联' : '已解除窗口关联'); }
  }
  function render() {
    results.replaceChildren();
    for (const w of items.filter(w => (w.title + ' ' + w.exe + ' ' + w.pid).toLowerCase().includes(search.value.toLowerCase()))) {
      const row = el('div', 'ops-discovery-row'); note(row, w.title + '\nPID ' + w.pid + ' · ' + w.exe);
      row.append(button('关联此窗口', () => bind(w))); results.append(row);
    }
    if (!results.children.length) note(results, '没有匹配的可访问窗口');
  }
  async function refresh() {
    const r = await act(fetch('/api/ops/windows').then(r => { if (!r.ok) throw new Error('读取窗口失败'); return r.json(); }));
    if (r) { items = r.items; render(); }
  }
  search.addEventListener('input', render);
  content.append(button('刷新窗口', refresh), button('解除关联', () => bind(null)));
  await refresh();
}

function alertFields(parent, policy = {}) {
  const exit = select(parent, '退出报警', [['default', '按类型默认'], ['always', '应保持运行'], ['never', '不提醒退出']], policy.exitPolicy || 'default');
  const grace = field(parent, '启动宽限（秒）', policy.graceSec ?? 30, 'number');
  const cpu = field(parent, 'CPU 阈值（全机 %，留空关闭）', policy.cpuPercent, 'number'); cpu.max = '100';
  const memory = field(parent, '内存阈值（MiB，留空关闭）', policy.memoryBytes == null ? '' : policy.memoryBytes / 1048576, 'number');
  const duration = field(parent, '资源持续超限（秒）', policy.durationSec ?? 60, 'number');
  const mute = el('div', 'ops-grid'); parent.append(mute);
  const muted = [['exit', '退出'], ['config', '配置'], ['port', '端口'], ['http', '接口'], ['cpu', 'CPU'], ['memory', '内存']]
    .map(([key, label]) => [key, field(mute, '静音：' + label, policy.muted?.includes(key), 'checkbox')]);
  return () => ({ exitPolicy: exit.value, graceSec: Number(grace.value), cpuPercent: optional(cpu),
    memoryBytes: optional(memory) == null ? null : optional(memory) * 1048576,
    durationSec: Number(duration.value), muted: muted.filter(([, f]) => f.checked).map(([key]) => key) });
}
function httpFields(parent, spec = {}, probe = false) {
  const url = field(parent, '本机 HTTP 地址' + (probe ? '（留空关闭探测）' : ''), spec.url);
  const method = select(parent, '请求方法', (probe ? ['GET', 'HEAD'] : ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE']).map(v => [v, v]), spec.method || 'GET');
  const headers = field(parent, '请求头（每行 名称: 值）', Object.entries(spec.headers || {}).map(([k, v]) => k + ': ' + v).join('\n'), 'textarea');
  const body = probe ? null : field(parent, '请求内容', spec.body, 'textarea');
  const timeout = field(parent, '请求超时（秒）', spec.timeoutSec || 5, 'number');
  return () => {
    const h = {};
    for (const line of headers.value.split('\n').filter(l => l.trim())) {
      const i = line.indexOf(':'); if (i <= 0) throw new Error('请求头格式应为 名称: 值');
      h[line.slice(0, i).trim()] = line.slice(i + 1).trim();
    }
    return url.value.trim() ? { url: url.value.trim(), method: method.value, headers: h, body: body?.value || '', timeoutSec: Number(timeout.value) } : null;
  };
}

export function openDetails(id) {
  const app = state.data?.apps.find(a => a.id === id); if (!app) return;
  if (!show(app.name + ' · 详情', false, 'details:' + id)) return; detailId = id;
  detailStatus = note(content, '');
  const info = section(content, '运行身份与启动配置', true);
  note(info, 'PID：' + (app.pids?.join(', ') || '未关联') + '\n目录：' + (app.cwd || '未设置') + '\n命令：' + (app.command || '观察卡片，尚无启动命令'));
  info.append(button('编辑启动配置', () => openAppModal(state.data.apps.find(a => a.id === id))), button('查看日志', () => openLogs(app)));
  info.append(button('编辑卡片按钮', () => openButtons(id)), button('查看异常', () => openAlerts(id)));
  if (state.data.platform === 'win32') {
    const followNote = note(info, app.instanceMatch ? '已启用：跟随应用重启，唯一匹配时自动关联新实例。' : '当前只关联本次实例；从运行中关联后可启用自动识别。');
    const follow = button(app.instanceMatch ? '关闭自动识别' : '启用自动识别', async () => {
      const current = state.data.apps.find(a => a.id === id);
      const result = await act(post('/api/ops/instance', { appId: id, enabled: !current.instanceMatch }));
      if (result?.ok) {
        setText(follow, result.instanceMatch ? '关闭自动识别' : '启用自动识别');
        setText(followNote, result.instanceMatch ? '已启用：跟随应用重启，唯一匹配时自动关联新实例。' : '当前只关联本次实例；从运行中关联后可启用自动识别。');
        await window.__poll();
      }
    }); info.append(follow);
  }
  if (!app.running) info.append(button('选择运行实例', () => openDiscovery(id)));
  const category = field(content, '分类', app.category || '');
  if (state.data.platform === 'win32') {
    const windows = section(content, '窗口关联', true);
    note(windows, '').dataset.windowBinding = '';
    windows.append(button('选择 / 更换窗口', () => openWindowPicker(id)));
    for (const [key, label] of windowActions) {
      const b = button(label, () => executeWindow(id, key.split(':')[1]));
      b.dataset.windowOperation = key.split(':')[1]; windows.append(b);
    }
  }
  const editors = [];
  const locations = section(content, '相关位置', true);
  note(locations, '保存项目、配置、日志、输出或下载路径。资源管理器打开目录或选中文件；终端在该目录（文件则在父目录）打开。编辑器默认使用系统文本编辑器，可指定 Code.exe 等可执行文件。');
  function addLocation(a = {}) {
    const box = section(locations, a.name || '新位置', true);
    const actionId = a.id || crypto.randomUUID();
    const name = field(box, '位置名称', a.name);
    const path = field(box, '文件或目录的绝对路径', a.path);
    const mode = select(box, '打开方式', [['explorer', '资源管理器'], ['terminal', '终端'], ['editor', '编辑器']], a.mode || 'explorer');
    const editor = field(box, '编辑器可执行文件路径（可留空）', a.editor);
    const when = select(box, '可用状态', [['always', '始终'], ['running', '运行中'], ['stopped', '停止时']], a.when || 'always');
    const sync = () => { editor.parentElement.hidden = mode.value !== 'editor'; }; mode.addEventListener('change', sync); sync();
    const open = button('打开已保存位置', () => executeAction(id, { id: actionId, type: 'location' })); open.disabled = !a.id;
    const entry = { removed: false, open, read: () => ({ id: actionId, name: name.value, type: 'location', path: path.value, mode: mode.value, editor: editor.value, when: when.value }) };
    box.append(open, button('移除此位置', () => { entry.removed = true; box.remove(); })); editors.push(entry);
  }
  for (const a of app.actions || []) if (a.type === 'location') addLocation(a);
  locations.append(button('添加相关位置', () => addLocation()));
  const probe = httpFields(section(content, '接口探测'), app.probe || {}, true);
  const policy = alertFields(section(content, '异常规则'), app.alertPolicy || {});
  const actionsSection = section(content, '自定义操作');
  const list = el('div'); actionsSection.append(list);
  const stop = select(actionsSection, '点击关闭时执行', [['', '默认关闭方式'], ...(app.actions || []).filter(a => ['command', 'script', 'http'].includes(a.type)).map(a => [a.id, a.name])], app.stopAction || '');
  function syncStopActions() {
    const selected = stop.value;
    const fallback = el('option'); fallback.value = ''; fallback.textContent = '默认关闭方式';
    const options = [fallback], actions = editors.filter(e => e.exitAction && !e.removed);
    for (const entry of actions) {
      const a = entry.readMeta(), eligible = ['command', 'script', 'http'].includes(a.type) && a.when !== 'stopped';
      entry.exitAction.disabled = !eligible;
      if (eligible) { const option = el('option'); option.value = a.id; option.textContent = a.name || '新操作'; options.push(option); }
    }
    stop.replaceChildren(...options);
    stop.value = options.some(o => o.value === selected) ? selected : '';
    for (const entry of actions) entry.exitAction.checked = entry.readMeta().id === stop.value;
  }
  stop.addEventListener('change', syncStopActions);
  function addAction(a = {}) {
    const box = section(list, a.name || '新操作', true);
    const actionId = a.id || crypto.randomUUID();
    const name = field(box, '操作名称', a.name);
    const type = select(box, '操作方式', [['command', '命令'], ['script', 'PowerShell / Python 脚本'], ['http', '本机 API'], ['url', '打开网页']], a.type || 'command');
    const when = select(box, '可用状态', [['always', '始终'], ['running', '运行中'], ['stopped', '停止时']], a.when || 'always');
    const cmdBox = el('div'), scriptBox = el('div'), httpBox = el('div'), urlBox = el('div'); box.append(cmdBox, scriptBox, httpBox, urlBox);
    const cmd = field(cmdBox, '命令', a.command, 'textarea');
    const shell = select(cmdBox, '解释器', state.data?.platform === 'win32' ? [['cmd', 'CMD'], ['powershell', 'PowerShell']] : [['bash', 'Bash']], a.shell || (state.data?.platform === 'win32' ? 'cmd' : 'bash'));
    const timeout = field(cmdBox, '超时（秒）', a.timeoutSec || 30, 'number');
    const scriptPath = field(scriptBox, '脚本绝对路径（.ps1 / .py）', a.path || '');
    const python = field(scriptBox, 'Python 解释器路径（留空使用总控台 Python）', a.python || '');
    const scriptTimeout = field(scriptBox, '超时（秒）', a.timeoutSec || 30, 'number');
    note(scriptBox, '保存后可在「配置按钮」中选择此操作，也可用作关闭操作。');
    const http = httpFields(httpBox, a); const url = field(urlBox, '网页地址', a.url);
    const readMeta = () => ({ id: actionId, name: name.value, type: type.value, when: when.value });
    const entry = { removed: false, readMeta, read: () => ({ ...readMeta(),
      ...(type.value === 'http' ? http() : type.value === 'url' ? { url: url.value } : type.value === 'script' ? { path: scriptPath.value, python: python.value, timeoutSec: Number(scriptTimeout.value) } : { command: cmd.value, shell: shell.value, timeoutSec: Number(timeout.value) }) }) };
    const sync = () => { cmdBox.hidden = type.value !== 'command'; scriptBox.hidden = type.value !== 'script'; httpBox.hidden = type.value !== 'http'; urlBox.hidden = type.value !== 'url'; };
    type.addEventListener('change', sync); sync();
    const exitAction = field(box, '用作关闭操作', app.stopAction === actionId, 'checkbox');
    entry.exitAction = exitAction;
    exitAction.addEventListener('change', () => {
      if (exitAction.checked) { const o = el('option'); o.value = actionId; o.textContent = name.value || '新操作'; if (![...stop.options].some(x => x.value === actionId)) stop.append(o); stop.value = actionId; }
      else if (stop.value === actionId) stop.value = '';
      syncStopActions();
    });
    for (const input of [name, type, when]) input.addEventListener('change', syncStopActions);
    box.append(button('移除此操作', () => { entry.removed = true; box.remove(); syncStopActions(); }));
    editors.push(entry);
  }
  for (const a of app.actions || []) if (a.type !== 'location') addAction(a);
  syncStopActions();
  actionsSection.append(button('添加操作', () => { addAction(); syncStopActions(); }));
  content.append(button('保存详情设置', async () => {
    const result = await act(put('/api/apps/' + id, { category: category.value, probe: probe(), alertPolicy: policy(),
      actions: editors.filter(e => !e.removed).map(e => e.read()), stopAction: stop.value || null }));
    if (result && result.ok !== false) { for (const entry of editors) if (entry.open) entry.open.disabled = false; toast('设置已保存'); window.__poll(); }
  }, 'btn btn-accent'));
  detailEvents = section(content, '最近事件', true);
  renderDetail();
}

function renderDetail() {
  if (!detailId) return;
  const app = state.data?.apps.find(a => a.id === detailId); if (!app) return;
  const binding = content.querySelector('[data-window-binding]');
  if (binding) setText(binding, app.windowBinding ? '已选择：' + app.windowBinding.title + (app.windowBinding.match ? '（失效后自动匹配；多个候选时需选择）' : '（本次窗口）') : '尚未选择窗口。GUI 和 TUI 的宿主终端首次需选择。');
  content.querySelectorAll('[data-window-operation]').forEach(b => { b.disabled = !app.running || app.statusKnown === false || !app.windowBinding; });
  setText(detailStatus, (app.associationDetail || (app.statusKnown === false ? '状态未知' : app.backgroundOnly ? '后台驻留' : app.running ? '运行中' : '已停止')) + ' · CPU ' + pct(app.resources?.cpu) + ' · 内存 ' + bytes(app.resources?.memoryBytes) + ' · ' + (probeNames[app.probeState?.status] || '接口未配置探测'));
  let events = detailEvents.querySelector('.ops-event-lines');
  if (!events) { events = el('div', 'ops-event-lines'); detailEvents.append(events); }
  setText(events, (state.data.events || []).filter(e => e.target === detailId).slice(0, 15).map(e => new Date(e.at * 1000).toLocaleString() + ' · ' + e.title + ' · ' + e.detail).join('\n') || '暂无事件');
}

async function openDiscovery(existingId = null) {
  if (!show(existingId ? '选择要关联的运行实例' : '从当前运行中发现')) return;
  const search = field(content, '搜索名称、路径或 PID');
  const all = field(content, '包括隐藏后台进程（无窗口、无端口）', false, 'checkbox');
  const results = el('div', 'ops-discovery'); content.append(results);
  let items = [];
  const render = () => {
    results.replaceChildren();
    const query = search.value.toLowerCase();
    for (const row of items.filter(r => (r.name + ' ' + r.exe + ' ' + r.pid + ' ' + r.command).toLowerCase().includes(query))) {
      const item = el('div', 'ops-discovery-row');
      const desc = el('div'); const name = el('strong'); name.textContent = row.name; desc.append(name);
      note(desc, 'PID ' + row.pid + ' · ' + (row.ports.map(p => ':' + p).join(' ') || '无监听端口') + '\n' + row.exe);
      item.append(desc, button(existingId ? '关联' : '加入卡片', () => importEditor(row, existingId))); results.append(item);
    }
    if (!results.children.length) note(results, '没有匹配的运行对象');
  };
  async function load() {
    const response = await fetch('/api/ops/discover' + (all.checked ? '?all=1' : ''));
    const data = await response.json(); if (!response.ok) throw new Error(data.error || '发现失败');
    items = data.items; render();
  }
  search.addEventListener('input', render); all.addEventListener('change', () => load().catch(e => toast(e.message)));
  note(results, '正在读取当前运行对象…'); await load();
}
function importEditor(row, existingId) {
  if (!show('加入：' + row.name)) return;
  note(content, '发现命令：' + (row.command || '无法读取') + '\n程序：' + row.exe + '\n未填写启动命令时保存为观察卡片。');
  const existing = state.data.apps.find(a => a.id === existingId);
  const name = field(content, '名称', existing?.name || row.name);
  const kind = select(content, '类型', [['desktop', '桌面应用'], ['service', '长期服务']], existing?.kind || row.kind);
  const command = field(content, '启动命令（可留空）', existing?.command || '', 'textarea');
  const shell = select(content, '执行方式', [['cmd', 'CMD'], ['powershell', 'PowerShell']], existing?.shell || 'cmd');
  const cwd = field(content, '工作目录（可留空）', existing?.cwd || '');
  const port = field(content, '配置端口（可留空）', existing?.port || row.ports[0] || '', 'number');
  content.append(button('保存并关联此实例', async () => {
    const result = await act(post('/api/ops/discover/import', { pid: row.pid, created: row.created,
      appId: existingId || undefined, name: name.value, command: command.value, shell: shell.value,
      cwd: cwd.value || null, kind: kind.value, port: optional(port) }));
    if (result && result.ok !== false) { closeOps(); toast('已保存固定卡片'); window.__poll(); }
  }, 'btn btn-accent'));
}

async function loadConfig() {
  const response = await fetch('/api/ops/config'); const data = await response.json();
  if (!response.ok) throw new Error(data.error || '读取配置失败'); config = data;
}
const metricOptions = [['cpu', '整机 CPU（%）'], ['memoryPercent', '整机内存（%）'], ['memoryBytes', '整机内存（字节）'],
  ['diskFreePercent', '磁盘剩余空间（%）'], ['diskWriteBytesPerSec', '磁盘写入（字节/秒）'], ['diskWriteBytes', '区间写入（字节）'],
  ['directoryBytes', '指定目录大小（字节）'], ['directoryGrowthBytes', '目录增长（字节）'], ['gpuPercent', '显存（%，需可读容量）']];
function renderDirectorySnapshots(parent, data) {
  const rules = (data.rules || []).filter(r => r.metric === 'directorySnapshotGrowthBytes');
  if (!rules.length) return;
  const box = section(parent, '目录定时快照', true);
  for (const path of new Set(rules.map(r => r.path))) {
    const record = data.directorySnapshots?.[path] || {};
    const row = section(box, path, true);
    const times = [...new Set(rules.filter(r => r.path === path).flatMap(r => r.dailyTimes))].sort();
    note(row, '每天 ' + times.join('、'));
    const status = record.running ? '正在统计' : record.status === 'ok' ? '统计完成' : record.status === 'incomplete' ? '统计超时，本次未计入对比' : record.status === 'unavailable' ? '目录无法完整读取，本次未计入对比' : '等待首次统计';
    note(row, status + (record.checkedAt ? ' · ' + new Date(record.checkedAt * 1000).toLocaleString() : '') + (record.durationMs != null ? ' · 耗时 ' + (record.durationMs / 1000).toFixed(1) + ' 秒' : ''));
    const last = record.history?.at(-1);
    if (last) note(row, '最近完整快照 ' + bytes(last[1]) + ' · ' + new Date(last[0] * 1000).toLocaleString());
    for (const [key, label] of [['day', '约 24 小时净增长'], ['week', '约 7 天净增长']]) {
      const delta = record.status === 'ok' ? record[key] : null;
      const reading = note(row, label + '：' + (delta ? (delta.bytes > 0 ? '+' : delta.bytes < 0 ? '−' : '') + bytes(Math.abs(delta.bytes)) : '—（等待完整样本）'));
      if (delta) reading.title = new Date(delta.fromAt * 1000).toLocaleString() + ' → ' + new Date(delta.toAt * 1000).toLocaleString();
    }
  }
}

async function openRules() {
  await loadConfig(); if (!show('系统基线与事件')) return;
  note(content, '基线只检查与提醒，不修改系统。目录检查仅在你明确指定后启用；显存容量不可用时不触发百分比规则。');
  const list = el('div'); content.append(list); const editors = [];
  function addSnapshot(rule = {}) {
    const box = section(list, rule.name || '目录定时快照', true);
    const name = field(box, '名称', rule.name || '目录持续增长');
    const path = field(box, '监控目录（包含子目录）', rule.path || '');
    path.placeholder = '粘贴本地目录绝对路径';
    box.append(button('选择目录', async () => {
      const original = path.value;
      const result = await act(postWithTimeout('/api/pick', { what: 'dir' }, 195000));
      if (result?.path && box.isConnected && panel.classList.contains('open') && path.value === original) path.value = result.path;
    }));
    const times = field(box, '每天采样时刻（逗号分隔，最多 4 次）', (rule.dailyTimes || ['03:00', '08:00', '12:30', '21:00']).join(', '));
    const window = select(box, '增长比较窗口', [['86400', '24 小时'], ['604800', '7 天']], String(rule.windowSec || 86400));
    const threshold = field(box, '净增长超过此值时提醒（GiB）', (rule.threshold ?? 1073741824) / 1073741824, 'number');
    const recovery = field(box, '净增长回落至此值时恢复（GiB）', (rule.recoveryThreshold ?? rule.threshold ?? 1073741824) / 1073741824, 'number');
    const mute = field(box, '静音此规则', rule.muted, 'checkbox');
    note(box, '按本机时间执行；首次保存后建立基线，休眠或关机错过的时段只补一次。只读文件大小，跳过链接目录；快照随配置保存。');
    const id = rule.id || crypto.randomUUID();
    const entry = { removed: false, read: () => ({ id, name: name.value, metric: 'directorySnapshotGrowthBytes',
      path: path.value.trim(), dailyTimes: times.value.split(/[,，\s]+/).filter(Boolean), windowSec: Number(window.value),
      threshold: Number(threshold.value) * 1073741824, recoveryThreshold: Number(recovery.value) * 1073741824,
      durationSec: 0, intervalSec: 900, muted: mute.checked }) };
    box.append(button('删除规则', () => { entry.removed = true; box.remove(); })); editors.push(entry);
    return path;
  }
  function add(rule = {}) {
    if (rule.metric === 'directorySnapshotGrowthBytes') return addSnapshot(rule);
    const box = section(list, rule.name || '新规则', true);
    const name = field(box, '名称', rule.name || '新规则');
    const metric = select(box, '指标', metricOptions, rule.metric || 'cpu');
    const gpu = [...metric.options].find(o => o.value === 'gpuPercent');
    gpu.disabled = !(state.data?.system?.gpus || []).some(g => g.capacityBytes && g.dedicatedBytes != null);
    const threshold = field(box, '触发阈值（磁盘剩余空间为低于，其余为高于）', rule.threshold ?? 90, 'number');
    const recovery = field(box, '恢复阈值', rule.recoveryThreshold ?? rule.threshold ?? 90, 'number');
    const duration = field(box, '持续时间（秒）', rule.durationSec ?? 60, 'number');
    const interval = field(box, '检查间隔（秒）', rule.intervalSec ?? 10, 'number');
    const path = field(box, '本地目录（目录类指标使用）', rule.path || '');
    const window = field(box, '增量比较窗口（秒）', rule.windowSec || 900, 'number');
    const mute = field(box, '静音此规则', rule.muted, 'checkbox');
    const entry = { removed: false, read: () => ({ id: rule.id || name.dataset.id, name: name.value,
      metric: metric.value, threshold: Number(threshold.value), recoveryThreshold: Number(recovery.value),
      durationSec: Number(duration.value), intervalSec: Number(interval.value), path: path.value,
      windowSec: Number(window.value), muted: mute.checked }) };
    name.dataset.id = crypto.randomUUID();
    box.append(button('删除规则', () => { entry.removed = true; box.remove(); })); editors.push(entry);
  }
  config.rules.forEach(add);
  content.append(button('添加规则', () => add()), button('添加目录定时快照', () => addSnapshot().focus()), button('保存基线', async () => {
    const result = await act(post('/api/ops/rules', { rules: editors.filter(e => !e.removed).map(e => e.read()) }));
    if (result?.ok) { toast('基线已保存'); window.__poll(); }
  }, 'btn btn-accent'));
  const readings = section(content, '磁盘、显存与目录读数', true);
  for (const d of state.data?.system?.disks || []) note(readings, d.path + ' 剩余 ' + bytes(d.freeBytes) + ' / ' + bytes(d.totalBytes));
  for (const g of state.data?.system?.gpus || []) note(readings, g.id + ' · 专用显存 ' + bytes(g.dedicatedBytes) + ' · 共享 ' + bytes(g.sharedBytes));
  for (const [path, d] of Object.entries(state.data?.directories || {})) note(readings, path + ' · ' + (d.status === 'ok' ? bytes(d.bytes) : '检查未完成／不可用'));
  renderDirectorySnapshots(content, state.data || {});
  const events = section(content, '最近事件', true);
  note(events, (state.data?.events || []).slice(0, 50).map(e => new Date(e.at * 1000).toLocaleString() + ' · ' + e.title + ' · ' + e.detail).join('\n') || '暂无事件');
}

async function openPresets(manage = false, replace = false) {
  await loadConfig(); if (!show('场景与预设包', replace)) return;
  note(content, '场景保留切换和基线设置；预设包单击打开或补齐，全部运行时单击不执行操作。关闭统一长按一秒，蓄力中松手取消。');
  for (const preset of config.presets || []) {
    const row = el('div', 'ops-discovery-row'); const title = el('strong'); title.textContent = preset.name;
    row.append(title);
    if (preset.type === 'package') note(row, '预设包 · ' + preset.steps.length + ' 个应用');
    else row.append(button('切换…', () => confirmPreset(preset)));
    if (manage) row.append(button('编辑', () => editPreset(preset)),
      button('删除', () => openConfirm({ title: '删除预设', bodyHtml: escapeHtml(preset.name), okText: '删除', onOk: async () => {
        const r = await act(post('/api/ops/presets', { presets: config.presets.filter(p => p.id !== preset.id) })); if (r?.ok) openPresets(true, true);
      } }))); content.append(row);
  }
  if (manage) content.append(button('新建场景', () => editPreset()), button('新建预设包', () => editPreset({ type: 'package' })));
  else if (!config.presets.length) note(content, '尚无模式，请在设置中心创建预设。');
  const result = el('pre', 'ops-run'); result.id = 'opsRun'; content.append(result);
  content.append(button('取消后续操作', () => act(post('/api/ops/presets/cancel'))));
  renderRun();
}
function iconActionPicker(parent, items, saved, actions) {
  const values = new Map(items.map(item => [item.id, { value: saved.get(item.id) || '' }]));
  const picker = el('div', 'ops-icon-picker'); parent.append(picker);
  const cycle = ['', ...actions.map(a => a[0])];
  const search = field(picker, '搜索', '', 'search'); search.placeholder = '搜索名称或分类';
  const grid = el('div', 'ops-picker-grid'); picker.append(grid);
  const nodes = [];
  function image(parent, app) {
    const visual = el('span', 'ops-picker-image'); parent.append(visual);
    const src = app.icon ? app.icon + (getIconVer(app.id) ? '?v=' + getIconVer(app.id) : '') : app.glyph ? null : app.favicon;
    if (src) {
      const img = new Image(); img.alt = ''; img.src = src;
      img.addEventListener('error', () => { visual.textContent = [...app.name][0] || '?'; }, { once: true }); visual.append(img);
    } else if (app.glyph) visual.append(icon(app.glyph, 28));
    else visual.textContent = [...app.name][0] || '?';
  }
  for (const item of items) {
    const choice = button('', () => {
      const selection = values.get(item.id), index = cycle.indexOf(selection.value);
      selection.value = cycle[(Math.max(0, index) + 1) % cycle.length]; render();
    }, 'ops-picker-choice');
    const check = el('span', 'ops-picker-check'); check.setAttribute('aria-hidden', 'true');
    const yes = icon('check', 12), no = icon('x', 12); check.append(yes, no);
    if (item.members?.length) {
      const mosaic = el('span', 'ops-picker-mosaic'); item.members.slice(0, 4).forEach(app => image(mosaic, app)); choice.append(mosaic);
    } else image(choice, item);
    choice.append(check); grid.append(choice);
    nodes.push({ item, choice, check, yes, no });
  }
  const empty = el('p', 'hint'); empty.textContent = '没有匹配的项目'; picker.append(empty);
  function render() {
    const query = search.value.trim().toLocaleLowerCase(); let visible = 0;
    for (const { item, choice, check, yes, no } of nodes) {
      const value = values.get(item.id).value, label = actions.find(a => a[0] === value)?.[1] || (value === 'keep' ? '保持不变（已有设置）' : '未选择');
      choice.hidden = !(item.name + ' ' + (item.category || '')).toLocaleLowerCase().includes(query);
      if (!choice.hidden) visible++;
      choice.dataset.action = value; choice.setAttribute('aria-pressed', String(value === 'start' || value === 'stop'));
      choice.setAttribute('aria-label', item.name + '，' + label); choice.title = item.name + ' · ' + label;
      choice.setAttribute('aria-description', actions.length === 1 ? '点击切换加入或取消' : '点击依次切换打开、关闭、不参与');
      check.hidden = value !== 'start' && value !== 'stop'; yes.hidden = value !== 'start'; no.hidden = value !== 'stop';
    }
    empty.hidden = !!visible;
  }
  search.addEventListener('input', render); render();
  return [...values];
}

function editPreset(preset = {}, drafts = {}, replace = false) {
  const isPackage = preset.type === 'package';
  if (!show((preset.id ? '编辑' : '新建') + (isPackage ? '预设包' : '场景'), replace)) return;
  if (!preset.id) {
    const modes = el('div', 'ops-picker-toolbar'); content.append(modes);
    for (const [type, label] of [['scene', '场景模式'], ['package', '应用包模式']]) {
      const selected = type === (isPackage ? 'package' : 'scene');
      const mode = button(label, () => {
        if (selected) return;
        drafts[isPackage ? 'package' : 'scene'] = readValue();
        editPreset({ ...(drafts[type] || { type }), name: name.value, timeoutSec: Number(timeout.value) }, drafts, true);
      }, 'btn' + (selected ? ' btn-accent' : ''));
      mode.setAttribute('aria-pressed', String(selected)); modes.append(mode);
    }
  }
  const name = field(content, '名称', preset.name || '');
  const timeout = field(content, '每项就绪超时（秒）', preset.timeoutSec || 30, 'number');
  const members = section(content, isPackage ? '包内应用' : '应用操作', true);
  const steps = iconActionPicker(members, (state.data.apps || []).filter(app => !isPackage || app.kind !== 'task'),
    new Map((preset.steps || []).map(s => [s.appId, s.action])),
    isPackage ? [['start', '已加入']] : [['start', '打开'], ['stop', '关闭']]);
  let packageFields = [];
  if (!isPackage) {
    const groups = section(content, '关联预设包', true);
    const packs = config.presets.filter(p => p.type === 'package').map(p => ({ ...p, glyph: 'package',
      members: p.steps.map(s => state.data.apps.find(a => a.id === s.appId)).filter(Boolean) }));
    packageFields = iconActionPicker(groups, packs, new Map((preset.packageSteps || []).map(s => [s.packageId, s.action])), [['start', '打开'], ['stop', '关闭']]);
  }
  const overrides = section(content, '模式下的系统阈值覆盖（留空沿用基础规则）');
  overrides.hidden = isPackage;
  const ruleFields = config.rules.map(r => [r.id, field(overrides, r.name, preset.ruleOverrides?.[r.id] ?? '', 'number')]);
  const appSection = section(content, '模式下的应用告警覆盖'); const appFields = [];
  appSection.hidden = isPackage;
  for (const app of state.data.apps || []) {
    const box = section(appSection, app.name); const enabled = field(box, '启用此应用的模式规则', !!preset.appOverrides?.[app.id], 'checkbox');
    const read = alertFields(box, preset.appOverrides?.[app.id] || app.alertPolicy || {}); appFields.push([app.id, enabled, read]);
  }
  function readValue() {
    return { id: preset.id, type: isPackage ? 'package' : 'scene', name: name.value, timeoutSec: Number(timeout.value),
      steps: steps.filter(([, f]) => f.value).map(([appId, f]) => ({ appId, action: f.value })),
      packageSteps: packageFields.filter(([, f]) => f.value).map(([packageId, f]) => ({ packageId, action: f.value })),
      ruleOverrides: isPackage ? {} : Object.fromEntries(ruleFields.filter(([, f]) => f.value !== '').map(([id, f]) => [id, Number(f.value)])),
      appOverrides: isPackage ? {} : Object.fromEntries(appFields.filter(([, enabled]) => enabled.checked).map(([id, , read]) => [id, read()])) };
  }
  content.append(button('保存预设', async () => {
    const value = readValue(); value.id ||= crypto.randomUUID();
    const presets = [...config.presets.filter(p => p.id !== value.id), value];
    const r = await act(post('/api/ops/presets', { presets })); if (r?.ok) { toast('预设已保存'); closeOps(); await openPresets(true, true); }
  }, 'btn btn-accent'));
}
function confirmPreset(preset) {
  const labels = { start: '启动', stop: '停止', keep: '保持不变' };
  const groups = (preset.packageSteps || []).map(s => escapeHtml(labels[s.action] + '预设包 · ' + (state.data.presets.find(p => p.id === s.packageId)?.name || s.packageId)));
  openConfirm({ title: '切换场景：' + preset.name, okText: '已保存工作，确认切换',
    bodyHtml: '<p><b>请先保存当前工作。</b>切换可能关闭应用，未保存的内容可能丢失。</p><div class="confirm-detail">' + ([...groups, ...preset.steps.map(s => escapeHtml(labels[s.action] + ' · ' + (state.data.apps.find(a => a.id === s.appId)?.name || s.appId)))].join('<br>') || '只切换此场景的基线规则。') + '</div><p>先关闭，再启动。完成后不会强制维持应用运行。</p>',
    onOk: async () => { const r = await act(post('/api/ops/presets/run', { id: preset.id })); if (r?.ok) { selectedPreset = null; toast('正在切换场景'); await window.__poll(); } },
  });
}
function renderRun() {
  const node = $('#opsRun'); if (!node) return;
  const run = state.data?.presetRun;
  const labels = { waiting: '等待', running: '执行中', succeeded: '成功', failed: '失败', skipped: '跳过', completed: '已完成', canceled: '已取消' };
  setText(node, run ? run.name + ' · ' + labels[run.status] + '\n' + run.steps.map(s =>
    (state.data.apps.find(a => a.id === s.appId)?.name || s.appId) + ' · ' + labels[s.status] + ' · ' + (s.detail || '')).join('\n') : '尚未执行预设');
}

let categoryFilter, systemSummary, notificationState, alertSignature = '';
let metricsSummary, sceneList, packageList, sceneSwitch, sceneStatus, sceneProgress, runStatus, tagList, selectedPreset = null;
let tagDrawer;
const packageNodes = new Map(), pendingPackages = new Set();

async function runPackage(preset, action) {
  if (pendingPackages.size || packageState(preset, state.data).disabled) return;
  pendingPackages.add(preset.id); renderPackages(state.data);
  try {
    const r = await act(post('/api/ops/presets/run', { id: preset.id, action }));
    if (r?.ok) { state.data.presetRun = r.run; renderOps(state.data); await window.__poll(); }
  } finally { pendingPackages.delete(preset.id); renderPackages(state.data); }
}

function renderPackages(data) {
  const presets = (data.presets || []).filter(p => p.type === 'package');
  for (const [id, node] of packageNodes) {
    if (!presets.some(p => p.id === id)) { node.cleanup(); node.remove(); packageNodes.delete(id); }
  }
  for (const preset of presets) {
    let node = packageNodes.get(preset.id);
    if (!node) {
      node = el('button', 'btn ops-package'); node.type = 'button';
      node.lamps = el('span', 'ops-package-lamps'); node.lamps.setAttribute('aria-hidden', 'true');
      node.label = el('span'); node.charge = el('span', 'ops-package-charge'); node.charge.setAttribute('aria-hidden', 'true');
      node.append(node.lamps, node.label, node.charge);
      bindPresetHover(node, preset.id);
      node.cleanup = bindPackagePress(node, () => ({ ...packageState(node.preset, state.data),
        disabled: !!pendingPackages.size || packageState(node.preset, state.data).disabled }),
      action => { void runPackage(node.preset, action).catch(error => toast(error.message)); });
      packageNodes.set(preset.id, node); packageList.append(node);
    }
    node.preset = preset;
    const status = packageState(preset, data), run = data.presetRun;
    const busy = run?.status === 'running' && run.presetId === preset.id;
    setText(node.label, preset.name);
    node.style.minWidth = Math.max(66, preset.steps.length * 10 + 20) + 'px';
    node.disabled = !!pendingPackages.size || status.disabled;
    node.dataset.state = status.mode;
    node.classList.toggle('is-opening', busy && run.action === 'start');
    node.classList.toggle('is-closing', busy && run.action === 'stop');
    node.classList.toggle('has-failure', run?.presetId === preset.id && run.status === 'failed');
    node.setAttribute('aria-busy', String(busy || pendingPackages.has(preset.id)));
    const action = status.mode === 'on' ? '长按一秒关闭' : status.mode === 'partial' ? '单击补齐；长按一秒关闭' : '单击打开';
    node.setAttribute('aria-label', `${preset.name}，${status.count}/${status.members.length} 运行，${action}`);
    if (node.lamps.children.length !== preset.steps.length) node.lamps.replaceChildren(...preset.steps.map(() => el('i')));
    status.members.forEach((app, index) => {
      const lamp = node.lamps.children[index];
      lamp.classList.toggle('is-on', status.lights[index]);
      lamp.classList.toggle('is-unknown', !!data.stale || !app || app.statusKnown === false);
      lamp.title = (app?.name || preset.steps[index].appId) + (lamp.classList.contains('is-unknown') ? ' · 状态待更新' : status.lights[index] ? ' · 运行中' : ' · 已关闭');
    });
  }
  packageList.hidden = !presets.length;
}
let activeMetric, metricsHideTimer;
const metricBars = [];
const GPU_CAPACITY_BYTES = 24 * 1024 ** 3; // 用户确认的显存容量，接口缺失容量时使用。

function updateMetricBar(ring, value, fallback = '—', detail = '') {
  const known = Number.isFinite(value);
  const reading = known ? value.toFixed(1) + '%' : fallback;
  ring.node.style.setProperty('--progress', (known ? Math.max(0, Math.min(100, value)) : 0) + '%');
  ring.node.classList.toggle('is-unknown', !known);
  ring.node.dataset.level = known && value >= 90 ? 'high' : known && value >= 75 ? 'warm' : 'normal';
  setText(ring.value, reading);
  ring.node.setAttribute('aria-label', ring.label + '：' + reading + (detail ? ' · ' + detail : ''));
}

function placeMetricsPopover() {
  const metricsPopover = activeMetric?.popover;
  if (!metricsPopover?.matches(':popover-open')) return;
  const rect = activeMetric.node.getBoundingClientRect();
  metricsPopover.style.left = Math.max(8, Math.min(rect.left, innerWidth - metricsPopover.offsetWidth - 8)) + 'px';
  metricsPopover.style.top = Math.max(8, Math.min(rect.bottom + 12, innerHeight - metricsPopover.offsetHeight - 8)) + 'px';
}
function closeMetricsPopover() {
  clearTimeout(metricsHideTimer);
  if (activeMetric?.popover.matches(':popover-open')) activeMetric.popover.hidePopover();
  activeMetric = null;
}
function showMetricsPopover(metric) {
  if (activeMetric !== metric) closeMetricsPopover();
  clearTimeout(metricsHideTimer);
  activeMetric = metric;
  if (!metric.popover.matches(':popover-open')) metric.popover.showPopover();
  placeMetricsPopover();
}
function scheduleMetricsHide() {
  clearTimeout(metricsHideTimer);
  metricsHideTimer = setTimeout(() => {
    if (activeMetric && !activeMetric.node.matches(':hover, :focus-visible') && !activeMetric.popover.matches(':hover')) closeMetricsPopover();
  }, 140);
}
function renderResourcePopover(data) {
  for (const bar of metricBars) {
    const group = { label: bar.label, metric: bar.metric, total: bar.value.textContent, rows: topResources(data, bar.metric) };
    const signature = JSON.stringify([group, !!data.stale]);
    if (bar.popover.dataset.signature === signature) continue;
    bar.popover.dataset.signature = signature;
    const header = el('div', 'ops-resource-head');
    const title = el('strong'); title.textContent = group.label + '占用';
    const status = el('span'); status.textContent = data.stale ? '数据待更新' : 'TOP 3 · 实时'; header.append(title, status);
    const section = el('section', 'ops-resource-section'); section.dataset.metric = group.metric;
    const heading = el('div', 'ops-resource-heading');
    const label = el('strong'); label.textContent = group.label;
    const total = el('span', 'mono'); total.textContent = group.total; heading.append(label, total); section.append(heading);
    if (!group.rows.length) note(section, '暂无可用数据');
    group.rows.forEach((item, i) => {
      const row = el('div', 'ops-resource-row');
      const rank = el('span', 'ops-resource-rank'); rank.textContent = String(i + 1);
      const name = el('span', 'ops-resource-name'); name.textContent = item.name; name.title = item.name;
      const value = el('span', 'ops-resource-value mono'); value.textContent = group.metric === 'cpu' ? pct(item[group.metric]) : bytes(item[group.metric]);
      row.append(rank, name, value); section.append(row);
    });
    bar.popover.replaceChildren(header, section);
  }
  placeMetricsPopover();
}
let sceneRunKey = null, sceneFeedbackTimer = null, compactRunResult = true;

function sceneRunState(run) {
  if (!run) return null;
  const steps = run.steps || [];
  const done = steps.filter(s => ['succeeded', 'failed', 'skipped'].includes(s.status)).length;
  const failed = steps.filter(s => s.status === 'failed').length;
  const kind = run.status === 'running' ? 'running' : run.status === 'failed' || failed ? 'warning' : run.status === 'canceled' ? 'canceled' : 'success';
  return { kind, done, total: steps.length, label: kind === 'running' ? done + '/' + steps.length :
    kind === 'warning' ? (failed ? failed + ' 项失败' : '执行失败') : kind === 'canceled' ? '已取消' : '已切换' };
}

function renderSceneRun(run) {
  const result = sceneRunState(run);
  const key = JSON.stringify([run?.id, run?.status, result?.kind]);
  if (key !== sceneRunKey) {
    const initial = sceneRunKey === null;
    sceneRunKey = key; clearTimeout(sceneFeedbackTimer); compactRunResult = initial;
    if (result?.kind === 'success' && !initial) {
      sceneFeedbackTimer = setTimeout(() => { compactRunResult = true; renderSceneRun(state.data?.presetRun); }, 3000);
    }
  }
  runStatus.hidden = !result;
  sceneProgress.hidden = result?.kind !== 'running';
  if (!result) return;
  runStatus.dataset.state = result.kind;
  runStatus.dataset.compact = String(compactRunResult && result.kind === 'success');
  setText(runStatus, result.kind === 'success' && compactRunResult ? '结果' : result.label);
  runStatus.title = run.name + ' · ' + result.label + ' · 点击查看逐项结果';
  runStatus.setAttribute('aria-label', runStatus.title);
  sceneProgress.setAttribute('aria-valuemax', String(result.total || 1));
  sceneProgress.setAttribute('aria-valuenow', String(result.done));
  sceneProgress.firstElementChild.style.transform = 'scaleX(' + (result.total ? result.done / result.total : 0) + ')';
}

export function initOps() {
  window.addEventListener('resize', placeBubble);
  document.addEventListener('scroll', placeBubble, true);
  window.addEventListener('resize', placeMetricsPopover);
  document.addEventListener('scroll', placeMetricsPopover, true);
  $('#settingsMonitoring').append(button('临时接受与永久忽略', openAcceptedAlerts));
  document.addEventListener('pointerdown', e => {
    if (activeMetric && !activeMetric.popover.contains(e.target) && !activeMetric.node.contains(e.target)) closeMetricsPopover();
    document.querySelectorAll('.ops-more[open]').forEach(menu => { if (!menu.closest('.app-card').contains(e.target)) flipCard(menu.closest('.app-card'), false, false); });
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeMetricsPopover();
    if (e.key !== 'Escape' || activeLayer()) return;
    const menu = $('.ops-more[open]');
    if (menu) { flipCard(menu.closest('.app-card'), false); e.preventDefault(); }
  });
  const toolbar = el('div', 'ops-toolbar');
  $('#settingsMonitoring').append(button('系统基线与事件', () => openRules()));
  $('#settingsScenes').append(button('管理模式预设', () => openPresets(true)));
  const size = select($('#settingsAppearance'), '卡片尺寸', [['small', '小'], ['medium', '中'], ['large', '大']], localStorage.getItem('cddeck-card-size') || 'medium');
  const resize = () => { document.documentElement.dataset.cardSize = size.value; localStorage.setItem('cddeck-card-size', size.value); };
  size.addEventListener('change', resize); resize();
  categoryFilter = select(toolbar, '分类', [['', '全部分类']], '');
  categoryFilter.parentElement.hidden = true;
  const search = $('#cmdkTrigger');
  search.className = 'icon-btn ops-header-search';
  search.replaceChildren(icon('search', 16));
  search.title = '快捷命令 · Ctrl/⌘ K';
  categoryFilter.addEventListener('change', filterCards);
  const tools = el('div', 'ops-launch-tools');
  systemSummary = button('系统状态', () => openAlertBubble('system', systemSummary), 'btn ops-system-status');
  const add = el('details', 'ops-add'); const title = el('summary', 'btn'); title.textContent = '＋ 添加';
  const menu = el('div', 'ops-menu');
  const addOption = (label, run) => button(label, () => { add.open = false; run(); });
  menu.append(addOption('添加应用／服务', () => openAppModal(null, 'desktop')), addOption('添加批处理任务', () => openAppModal(null, 'task')), addOption('从运行中发现', () => openDiscovery()));
  add.append(title, menu);
  tools.append(add); toolbar.append(search, tools);
  notificationState = note($('#settingsMonitoring'), '后台通知：准备中');
  const settingsButton = el('button', 'icon-btn ops-settings-shortcut'); settingsButton.type = 'button';
  settingsButton.dataset.qa = 'settings'; settingsButton.setAttribute('aria-label', '设置中心'); settingsButton.title = '设置中心'; settingsButton.append(icon('settings', 18));
  $('.side-controls').append(settingsButton);
  const controls = el('div', 'ops-editor-tools'); controls.append($('#restartConsoleBtn'), $('#stopConsoleBtn'), $('#githubLink')); $('#settingsConsole').append(controls);
  $('.rail').prepend($('.side-brand'));
  $('.topbar-inner').prepend(toolbar);
  const overview = el('div', 'ops-performance');
  metricsSummary = el('div', 'ops-metrics');
  metricsSummary.setAttribute('role', 'group'); metricsSummary.setAttribute('aria-label', '系统资源');
  for (const [label, metric] of [['CPU', 'cpu'], ['内存', 'memoryBytes'], ['显存', 'gpuMemoryBytes']]) {
    const node = button('', () => { closeMetricsPopover(); openAlerts('system'); }, 'ops-metric');
    const popover = el('div', 'ops-resource-popover'); popover.id = 'opsResourcePopover-' + metric;
    popover.setAttribute('popover', 'manual'); popover.setAttribute('role', 'tooltip');
    document.body.append(popover); node.setAttribute('aria-describedby', popover.id);
    const track = el('span', 'ops-metric-track'); track.setAttribute('aria-hidden', 'true');
    const value = el('span', 'ops-metric-value');
    const caption = el('span', 'ops-metric-label'); caption.textContent = label;
    const bar = { node, value, label, metric, popover };
    node.append(caption, value, track); metricsSummary.append(node); metricBars.push(bar);
    node.addEventListener('pointerenter', () => showMetricsPopover(bar));
    node.addEventListener('focus', () => showMetricsPopover(bar));
    node.addEventListener('pointerleave', scheduleMetricsHide);
    node.addEventListener('blur', scheduleMetricsHide);
    popover.addEventListener('pointerenter', () => clearTimeout(metricsHideTimer));
    popover.addEventListener('pointerleave', scheduleMetricsHide);
  }
  overview.append(systemSummary, metricsSummary);
  const scenes = el('div', 'ops-scenes'); const label = el('span', 'ops-row-label'); label.textContent = '场景';
  sceneList = el('div', 'ops-scene-list'); sceneList.setAttribute('role', 'group'); sceneList.setAttribute('aria-label', '选择场景，不立即执行');
  packageList = el('div', 'ops-package-list'); packageList.setAttribute('role', 'group'); packageList.setAttribute('aria-label', '预设包开关');
  sceneSwitch = button('切换场景', () => { const p = state.data?.presets?.find(p => p.id === selectedPreset); if (p) confirmPreset(p); }, 'btn btn-accent');
  const edit = button('', () => openPresets(true), 'btn ops-scene-edit'); edit.append(icon('settings', 15));
  edit.title = '管理场景与预设包'; edit.setAttribute('aria-label', edit.title);
  sceneStatus = el('div', 'ops-scene-status sr-only'); sceneStatus.setAttribute('role', 'status');
  sceneStatus.title = '当前生效表示场景基线已启用；应用启停是否成功请查看执行结果。';
  runStatus = button('', () => openPresets(), 'ops-scene-result'); runStatus.hidden = true;
  sceneProgress = el('div', 'ops-scene-progress'); sceneProgress.hidden = true; sceneProgress.append(el('i'));
  sceneProgress.setAttribute('role', 'progressbar'); sceneProgress.setAttribute('aria-label', '场景执行进度'); sceneProgress.setAttribute('aria-valuemin', '0');
  scenes.append(label, sceneList, packageList, sceneSwitch, runStatus, edit, sceneStatus, sceneProgress);
  const clearSelection = () => { if (selectedPreset) { selectedPreset = null; renderOps(state.data); } };
  document.addEventListener('keydown', event => { if (event.key === 'Escape') clearSelection(); });
  document.addEventListener('pointerdown', event => {
    if (!event.target.closest('.ops-scene, .ops-scenes > .btn-accent, .ops-preset-popover, #confirmMask')) clearSelection();
  });
  tagList = el('div', 'ops-tags'); tagList.setAttribute('role', 'group'); tagList.setAttribute('aria-label', '按标签筛选卡片');
  toolbar.prepend(overview, tagList);
  tagDrawer = initTagDrawer(tagList, name => {
    categoryFilter.value = name;
    if (state.view !== 'launchpad') $('#rail-launchpad').click();
    renderOps(state.data);
  });
  $('#view-launchpad').prepend(scenes);
  $('#rail-launchpad .rail-label').textContent = '首页';
  $('#rail-launchpad').setAttribute('aria-label', '首页');
  $('#rail-services .rail-label').textContent = '服务与端口';
  $('#view-launchpad .sec-label > span').textContent = '我的应用';
}
function filterCards() {
  if (!categoryFilter) return;
  for (const app of state.data?.apps || []) {
    const card = document.querySelector('.app-card[data-key="' + app.id + '"]');
    if (card) card.classList.toggle('ops-filtered', !!categoryFilter.value && app.category !== categoryFilter.value);
  }
}
export function renderOps(data) {
  if (bubbleAlert && !(data.alerts || []).some(a => a.key === bubbleAlert.key && a.incident === bubbleAlert.incident && !a.ignored)) closeBubble();
  const count = (data.alerts || []).filter(a => a.target === 'system' && !a.ignored).length;
  setText(systemSummary, count ? '系统 · ' + count + ' 项异常' : data.stale || data.degraded ? '系统状态待更新' : '系统正常');
  systemSummary.classList.toggle('has-alert', count > 0);
  systemSummary.classList.toggle('is-pending', !count && !!(data.stale || data.degraded));
  systemSummary.setAttribute('aria-label', count ? count + ' 项系统异常，查看原因' : '查看系统状态');
  setText(notificationState, '后台 Windows 通知：' + ({ ready: '可用', disabled: '已关闭', unavailable: '不可用', starting: '准备中', pending: '待首次通知验证', busy: '忙碌' }[data.notificationStatus] || '未知'));
  const s = data.system || {};
  const gpus = s.gpus || [];
  const readable = gpus.filter(g => Number.isFinite(g.dedicatedBytes));
  const gpuBytes = readable.reduce((sum, g) => sum + g.dedicatedBytes, 0);
  const hasCapacity = gpus.length > 0 && gpus.every(g => Number.isFinite(g.dedicatedBytes) && Number.isFinite(g.capacityBytes) && g.capacityBytes > 0);
  const capacity = hasCapacity ? gpus.reduce((sum, g) => sum + g.capacityBytes, 0) : GPU_CAPACITY_BYTES;
  updateMetricBar(metricBars[0], s.cpu);
  updateMetricBar(metricBars[1], s.memoryPercent);
  updateMetricBar(metricBars[2], readable.length ? gpuBytes / capacity * 100 : null,
    '—', readable.length ? bytes(gpuBytes) + ' / ' + bytes(capacity) + (hasCapacity ? '' : '（用户指定容量）') : '显存读数不可用');
  renderResourcePopover(data);
  const presets = (data.presets || []).filter(p => p.type !== 'package');
  if (!presets.some(p => p.id === selectedPreset)) selectedPreset = null;
  const activePreset = presets.find(p => p.id === data.activePreset);
  const pendingPreset = presets.find(p => p.id === selectedPreset);
  setText(sceneStatus, '当前生效：' + (activePreset?.name || '未启用场景') +
    (pendingPreset ? pendingPreset.id === activePreset?.id ? ' · 已选当前场景，可重新应用' : ' · 待切换：' + pendingPreset.name : ''));
  const sceneSig = JSON.stringify([presets.map(p => [p.id, p.name]), selectedPreset, data.activePreset]);
  if (sceneList.dataset.signature !== sceneSig) {
    const focused = sceneList.contains(document.activeElement) ? document.activeElement.dataset.presetId : null;
    sceneList.dataset.signature = sceneSig; sceneList.replaceChildren();
    for (const p of presets) {
      const active = p.id === data.activePreset;
      const pending = p.id === selectedPreset && !active;
      const b = button(p.name, () => { selectedPreset = selectedPreset === p.id ? null : p.id; renderOps(state.data); }, 'btn ops-scene');
      b.dataset.presetId = p.id;
      bindPresetHover(b, p.id);
      b.setAttribute('aria-pressed', String(p.id === selectedPreset));
      b.setAttribute('aria-description', active ? '当前场景；点击选择，再次点击取消' : '点击选择，再次点击取消');
      b.classList.toggle('is-current', active); b.classList.toggle('is-pending', pending); sceneList.append(b);
      if (focused === p.id) b.focus({ preventScroll: true });
    }
    if (!presets.length) note(sceneList, '尚未设置场景');
  }
  renderPackages(data);
  renderPresetHover(data);
  sceneSwitch.disabled = !selectedPreset || data.presetRun?.status === 'running';
  setText(sceneSwitch, selectedPreset && selectedPreset === data.activePreset ? '重新应用场景' : '切换场景');
  sceneSwitch.title = selectedPreset ? '确认保存工作后再执行所选场景' : '先选择一个场景';
  renderSceneRun(data.presetRun);
  const next = JSON.stringify([alertTarget, data.alerts, data.events, data.stale, data.degraded, data.directorySnapshots, data.rules, data.apps?.map(a => [a.id, a.health, a.alerts])]);
  if (alertSignature !== next) { alertSignature = next; renderAlerts(); }
  const categories = [...new Set((data.apps || []).map(a => a.category).filter(Boolean))].sort();
  const sig = categories.join('|');
  if (categoryFilter.dataset.signature !== sig) {
    const selected = categoryFilter.value; categoryFilter.replaceChildren();
    for (const name of ['', ...categories]) { const o = el('option'); o.value = name; o.textContent = name || '全部分类'; categoryFilter.append(o); }
    categoryFilter.value = categories.includes(selected) ? selected : ''; categoryFilter.dataset.signature = sig;
  }
  tagDrawer.render(categories, categoryFilter.value);
  $('#taskGrid').closest('.panel').hidden = !(data.apps || []).some(a => a.kind === 'task');
  filterCards(); renderDetail(); renderRun();
}
