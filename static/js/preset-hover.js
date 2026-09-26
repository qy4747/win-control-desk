import { el, icon, setText, state, toast } from './core.js';
import { getIconVer } from './overlays.js';
import { presetMembers, bindPackagePress } from './packages.js';

const panel = el('section', 'ops-preset-popover');
panel.id = 'opsPresetPopover'; panel.setAttribute('popover', 'auto');
panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-labelledby', 'opsPresetPopoverTitle');
const header = el('header'), title = el('strong'), close = el('button', 'ibtn');
title.id = 'opsPresetPopoverTitle'; close.type = 'button'; close.append(icon('x', 18));
close.setAttribute('aria-label', '关闭悬浮面板');
header.append(title, close);
const body = el('div', 'ops-preset-popover-body'); panel.append(header, body); document.body.append(panel);
let anchor = null, selected = null, showTimer, hideTimer, signature = '';
const rows = new Map(), pending = new Set();

function hide() {
  clearTimeout(showTimer); clearTimeout(hideTimer);
  for (const entry of rows.values()) entry.toggle.dispatchEvent(new Event('pointercancel'));
  if (panel.matches(':popover-open')) panel.hidePopover();
  anchor?.setAttribute('aria-expanded', 'false'); anchor = null; selected = null;
}
function position() {
  if (!panel.matches(':popover-open') || !anchor?.isConnected) return;
  const rect = anchor.getBoundingClientRect(), gap = 9;
  const above = rect.bottom + gap + panel.offsetHeight > innerHeight - 8 && rect.top > panel.offsetHeight + gap;
  panel.style.left = Math.max(8, Math.min(rect.left, innerWidth - panel.offsetWidth - 8)) + 'px';
  panel.style.top = Math.max(8, above ? rect.top - panel.offsetHeight - gap : rect.bottom + gap) + 'px';
  panel.style.maxHeight = Math.max(100, above ? rect.top - gap - 8 : innerHeight - rect.bottom - gap - 8) + 'px';
}
function scheduleHide() {
  clearTimeout(showTimer); clearTimeout(hideTimer);
  hideTimer = setTimeout(() => {
    if (!panel.matches(':hover, :focus-within') && !anchor?.matches(':hover, :focus')) hide();
  }, 240);
}
function show(node, id) {
  const preset = state.data?.presets?.find(p => p.id === id);
  if (!preset || !node.isConnected) return;
  anchor?.setAttribute('aria-expanded', 'false');
  anchor = node; selected = id; anchor.setAttribute('aria-expanded', 'true');
  renderPresetHover(state.data);
  if (!panel.matches(':popover-open')) panel.showPopover();
  position();
}
export function bindPresetHover(node, id) {
  node.dataset.hoverPreset = id;
  node.setAttribute('aria-haspopup', 'dialog'); node.setAttribute('aria-controls', panel.id);
  node.setAttribute('aria-expanded', 'false');
  const enter = () => {
    clearTimeout(hideTimer); clearTimeout(showTimer);
    showTimer = setTimeout(() => show(node, id), 180);
  };
  node.addEventListener('pointerenter', enter); node.addEventListener('focus', enter);
  node.addEventListener('pointerleave', scheduleHide); node.addEventListener('blur', scheduleHide);
  node.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown') {
      event.preventDefault(); clearTimeout(showTimer); show(node, id); close.focus();
    }
  });
}
close.addEventListener('click', hide);
panel.addEventListener('pointerenter', () => { clearTimeout(hideTimer); clearTimeout(showTimer); });
panel.addEventListener('pointerleave', scheduleHide);
panel.addEventListener('focusin', () => clearTimeout(hideTimer));
panel.addEventListener('focusout', scheduleHide);
panel.addEventListener('toggle', () => { if (!panel.matches(':popover-open')) hide(); });
panel.addEventListener('keydown', event => { if (event.key === 'Escape') hide(); });
window.addEventListener('resize', position);
document.addEventListener('scroll', event => { if (!panel.contains(event.target)) position(); }, true);

function makeMember(step) {
  const row = el('div', 'ops-preset-member'), toggle = el('button', 'ops-preset-app-toggle');
  toggle.type = 'button';
  const image = el('span', 'ops-preset-app-image');
  const charge = el('span', 'ops-package-charge'); charge.setAttribute('aria-hidden', 'true');
  toggle.append(image, charge); row.append(toggle);
  const invoke = async action => {
    if (toggle.disabled || pending.has(step.appId)) return;
    const app = state.data.apps?.find(a => a.id === step.appId);
    if (!app || app.statusKnown === false || state.data.stale) return;
    pending.add(step.appId); renderPresetHover(state.data);
    try {
      if (action === 'focus') {
        const { executeWindow } = await import('./ops.js'); await executeWindow(step.appId, 'focus');
      } else {
        const { toggleApp } = await import('./launchpad.js');
        await toggleApp(step.appId, toggle, action === 'stop', action);
      }
    } catch (error) { toast(error.message); }
    finally { pending.delete(step.appId); renderPresetHover(state.data); }
  };
  const cleanup = bindPackagePress(toggle, () => {
    const app = state.data.apps?.find(a => a.id === step.appId);
    const running = !!app?.running && !app.backgroundOnly;
    return { mode: running ? 'on' : 'off', count: Number(running),
      disabled: toggle.disabled || !!state.data.stale || !app || app.statusKnown === false };
  }, action => { void invoke(action).catch(error => toast(error.message)); }, {
    canHold: current => current.mode === 'on', clickAction: current => current.mode === 'on' ? 'focus' : 'start',
  });
  return { row, toggle, image, cleanup };
}

export function renderPresetHover(data) {
  if (!selected) return;
  const preset = data.presets?.find(p => p.id === selected);
  if (!preset) { hide(); return; }
  if (!anchor?.isConnected) {
    anchor = [...document.querySelectorAll('[data-hover-preset]')].find(node => node.dataset.hoverPreset === selected);
    if (!anchor) { hide(); return; }
    anchor.setAttribute('aria-expanded', 'true');
  }
  const isPackage = preset.type === 'package', members = presetMembers(preset, data.presets);
  setText(title, (isPackage ? '应用包 · ' : '场景 · ') + preset.name);
  panel.classList.toggle('is-package', isPackage);
  const next = JSON.stringify([preset.id, isPackage, members]);
  if (signature !== next) {
    signature = next; for (const entry of rows.values()) entry.cleanup(); rows.clear(); body.replaceChildren();
    const groups = isPackage ? [['all', '', members]] : ['start', 'stop', 'keep'].map(action => [
      action, { start: '准备打开', stop: '准备关闭', keep: '保持不变' }[action], members.filter(s => s.action === action)]);
    for (const [action, label, steps] of groups) {
      if (!steps.length) continue;
      const group = el('section', 'ops-preset-member-group'); group.dataset.action = action;
      if (label) { const caption = el('h4'); caption.textContent = label + '（' + steps.length + '）'; group.append(caption); }
      const list = el('div', isPackage ? 'ops-preset-member-grid' : 'ops-preset-member-list');
      list.style.setProperty('--member-columns', Math.min(4, steps.length));
      list.style.setProperty('--member-columns-small', Math.min(3, steps.length));
      for (const step of steps) { const entry = makeMember(step); rows.set(step.appId, entry); list.append(entry.row); }
      group.append(list); body.append(group);
    }
    if (!members.length) { const empty = el('p', 'hint'); empty.textContent = '此场景仅调整规则，没有应用开关。'; body.append(empty); }
  }
  for (const step of members) {
    const entry = rows.get(step.appId), app = data.apps?.find(a => a.id === step.appId);
    const known = !!app && !data.stale && app.statusKnown !== false;
    const running = !!app?.running && !app.backgroundOnly;
    const cardBusy = document.querySelector('.app-card[data-key="' + CSS.escape(step.appId) + '"]')?._r?.primary?.dataset.busy === 'true';
    const busy = pending.has(step.appId) || entry.toggle.dataset.busy === 'true' || cardBusy;
    const unavailable = !known || busy || data.presetRun?.status === 'running' || (!running &&
      (app.canStart === false || app.health?.blocking || app.portConflict || app.portOccupied));
    entry.toggle.disabled = !!unavailable;
    entry.toggle.setAttribute('aria-busy', String(busy));
    entry.toggle.classList.toggle('is-on', running);
    const name = app?.name || step.appId;
    const label = !known ? '状态待更新' : busy ? '处理中' : running ? '运行中' : app?.backgroundOnly ? '后台驻留' : '已关闭';
    const actionLabel = running ? '单击前台显示；长按一秒关闭' : '单击打开';
    entry.toggle.title = name + ' · ' + label;
    entry.toggle.setAttribute('aria-label', entry.toggle.title + '；' + actionLabel);
    const visual = app?.icon ? app.icon + (getIconVer(app.id) ? '?v=' + getIconVer(app.id) : '') : app?.glyph ? '' : app?.favicon;
    const imageKey = visual || app?.glyph || name;
    if (entry.image.dataset.key !== imageKey) {
      entry.image.dataset.key = imageKey; entry.image.replaceChildren();
      if (visual) {
        const img = new Image(); img.alt = ''; img.src = visual;
        img.addEventListener('error', () => { entry.image.textContent = [...name][0] || '?'; }, { once: true });
        entry.image.append(img);
      } else if (app?.glyph) entry.image.append(icon(app.glyph, 30));
      else entry.image.textContent = [...name][0] || '?';
    }
  }
  position();
}
