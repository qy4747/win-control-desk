export const HOLD_DELAY = 200;
export const HOLD_DURATION = 1000;

export function presetMembers(preset, presets = []) {
  const members = new Map();
  if (preset.type !== 'package') {
    for (const group of preset.packageSteps || []) {
      const pack = presets.find(p => p.id === group.packageId && p.type === 'package');
      for (const step of pack?.steps || []) members.set(step.appId, { appId: step.appId, action: group.action });
    }
  }
  // Match the backend: explicit scene steps override package membership.
  for (const step of preset.steps || []) members.set(step.appId, step);
  return [...members.values()];
}

export function packageState(preset, data) {
  const apps = new Map((data.apps || []).map(app => [app.id, app]));
  const members = preset.steps.map(step => apps.get(step.appId));
  const known = !data.stale && members.every(app => app && app.statusKnown !== false);
  const lights = members.map(app => !!app?.running && !app.backgroundOnly);
  const count = lights.filter(Boolean).length;
  const mode = !known ? 'unknown' : !count ? 'off' : count === members.length ? 'on' : 'partial';
  return { members, lights, count, mode, disabled: !known || !members.length || data.presetRun?.status === 'running' };
}

// Short press opens/fills a package; closing always requires a completed hold.
export function bindPackagePress(node, read, invoke, {
  canHold = current => current.mode === 'partial' || current.mode === 'on',
  clickAction = current => current.mode === 'on' ? null : 'start',
} = {}) {
  let press = null, chargeTimer, commitTimer, suppressClick = false;
  function clear() {
    clearTimeout(chargeTimer); clearTimeout(commitTimer);
    node.classList.remove('is-charging');
    press = null;
  }
  function cancel() { if (press) suppressClick = true; clear(); }
  function begin(kind, event) {
    const current = read();
    if (current.disabled || !canHold(current) || press) return false;
    suppressClick = false;
    press = { kind, x: event.clientX, y: event.clientY, charging: false, fired: false };
    chargeTimer = setTimeout(() => {
      if (!press) return;
      press.charging = true; node.classList.add('is-charging');
    }, HOLD_DELAY);
    commitTimer = setTimeout(() => {
      if (!press) return;
      suppressClick = true; press.fired = true;
      const latest = read();
      node.classList.remove('is-charging');
      if (!latest.disabled && latest.count) invoke('stop');
    }, HOLD_DURATION);
    return true;
  }
  node.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.isPrimary === false) return;
    if (!press) suppressClick = false;
    if (begin('pointer', event)) node.setPointerCapture(event.pointerId);
  });
  node.addEventListener('pointermove', event => {
    if (press?.kind === 'pointer' && Math.hypot(event.clientX - press.x, event.clientY - press.y) > 8) cancel();
  });
  node.addEventListener('pointerup', () => {
    if (press?.kind !== 'pointer') return;
    suppressClick = press.charging || press.fired;
    clear();
  });
  node.addEventListener('pointercancel', cancel);
  node.addEventListener('lostpointercapture', () => { if (press) cancel(); });
  node.addEventListener('contextmenu', event => event.preventDefault());
  node.addEventListener('click', event => {
    if (suppressClick) { suppressClick = false; event.preventDefault(); return; }
    const current = read();
    const action = clickAction(current);
    if (!current.disabled && action) invoke(action);
  });
  node.addEventListener('keydown', event => {
    if (event.key === 'Escape') { cancel(); return; }
    if (![' ', 'Enter'].includes(event.key)) return;
    if (!press && !event.repeat) suppressClick = false;
    if (press || canHold(read())) {
      event.preventDefault();
      if (!event.repeat) begin('key', event);
    }
  });
  node.addEventListener('keyup', event => {
    if (![' ', 'Enter'].includes(event.key) || press?.kind !== 'key') return;
    event.preventDefault();
    const short = !press.charging && !press.fired;
    suppressClick = true; clear();
    const current = read();
    const action = clickAction(current);
    if (short && !current.disabled && action) invoke(action);
  });
  node.addEventListener('blur', cancel);
  window.addEventListener('blur', cancel);
  const visibility = () => { if (document.hidden) cancel(); };
  document.addEventListener('visibilitychange', visibility);
  return () => { cancel(); window.removeEventListener('blur', cancel); document.removeEventListener('visibilitychange', visibility); };
}
