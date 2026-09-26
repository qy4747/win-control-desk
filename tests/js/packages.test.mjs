import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('partial-package click, canceled hold and committed hold stay distinct', () => {
  const source = readFileSync(new URL('../../static/js/packages.js', import.meta.url), 'utf8');
  let now = 0, serial = 0;
  const timers = new Map(), events = new Map(), calls = [], classes = new Set();
  const context = vm.createContext({
    setTimeout: (fn, ms) => { timers.set(++serial, { at: now + ms, fn }); return serial; },
    clearTimeout: id => timers.delete(id),
    window: { addEventListener() {}, removeEventListener() {} },
    document: { hidden: false, addEventListener() {}, removeEventListener() {} },
  });
  vm.runInContext(source.replaceAll('export ', '') + '\nthis.bind = bindPackagePress; this.status = packageState; this.members = presetMembers;', context);
  const advance = ms => {
    now += ms;
    for (const [id, timer] of [...timers]) if (timer.at <= now) { timers.delete(id); timer.fn(); }
  };
  const node = { addEventListener: (type, fn) => events.set(type, fn), setPointerCapture() {},
    classList: { add: x => classes.add(x), remove: x => classes.delete(x) } };
  const emit = (type, extra = {}) => events.get(type)?.({ button: 0, isPrimary: true, pointerId: 1,
    clientX: 0, clientY: 0, preventDefault() {}, ...extra });
  const partial = { disabled: false, mode: 'partial', count: 1 };
  const cleanup = context.bind(node, () => partial, action => calls.push(action));
  emit('pointerdown'); advance(80); emit('pointerup'); emit('click');
  assert.deepEqual(calls, ['start']);
  emit('pointerdown'); advance(400); assert.ok(classes.has('is-charging'));
  emit('pointerup'); emit('click'); advance(1500);
  assert.deepEqual(calls, ['start']);
  emit('pointerdown'); advance(200); advance(800); emit('pointerup'); emit('click');
  assert.deepEqual(calls, ['start', 'stop']);
  emit('pointerdown'); advance(250); emit('pointermove', { clientX: 20 }); advance(1000); emit('pointerup'); emit('click');
  assert.deepEqual(calls, ['start', 'stop']);
  cleanup(); calls.length = 0;
  const full = { disabled: false, mode: 'on', count: 2 };
  const cleanupFull = context.bind(node, () => full, action => calls.push(action));
  emit('pointerdown'); advance(80); emit('pointerup'); emit('click');
  emit('keydown', { key: 'Enter' }); advance(80); emit('keyup', { key: 'Enter' });
  assert.deepEqual(calls, []);
  emit('pointerdown'); advance(400); emit('pointerup'); emit('click'); advance(1000);
  assert.deepEqual(calls, []);
  emit('pointerdown'); advance(1000); emit('pointerup'); emit('click');
  assert.deepEqual(calls, ['stop']);
  emit('keydown', { key: 'Enter' }); advance(1000); emit('keyup', { key: 'Enter' });
  assert.deepEqual(calls, ['stop', 'stop']);
  full.mode = 'off'; full.count = 0;
  emit('pointerdown'); emit('pointerup'); emit('click');
  assert.deepEqual(calls, ['stop', 'stop', 'start']);
  cleanupFull(); calls.length = 0;
  const member = { disabled: false, mode: 'on', count: 1 };
  context.bind(node, () => member, action => calls.push(action), {
    canHold: current => current.mode === 'on',
    clickAction: current => current.mode === 'on' ? 'focus' : 'start',
  });
  emit('pointerdown'); advance(80); emit('pointerup'); emit('click');
  assert.deepEqual(calls, ['focus']);
  emit('pointerdown'); advance(400); emit('pointerup'); emit('click'); advance(1000);
  assert.deepEqual(calls, ['focus']);
  emit('pointerdown'); advance(1000); emit('pointerup'); emit('click');
  assert.deepEqual(calls, ['focus', 'stop']);
  emit('keydown', { key: 'Enter' }); advance(80); emit('keyup', { key: 'Enter' });
  assert.deepEqual(calls, ['focus', 'stop', 'focus']);
  emit('pointerdown'); advance(400); emit('pointercancel'); advance(1000); emit('click');
  assert.deepEqual(calls, ['focus', 'stop', 'focus']);
  emit('pointerdown'); member.mode = 'off'; member.count = 0;
  advance(1000); emit('pointerup'); emit('click');
  assert.deepEqual(calls, ['focus', 'stop', 'focus']);
  emit('pointerdown'); emit('pointerup'); emit('click');
  assert.deepEqual(calls, ['focus', 'stop', 'focus', 'start']);
  const preset = { steps: [{ appId: 'a' }, { appId: 'b' }] };
  const data = { apps: [{ id: 'a', running: true }, { id: 'b', running: false }] };
  assert.equal(context.status(preset, data).mode, 'partial');
  assert.equal(context.status(preset, { ...data, stale: true }).disabled, true);
  data.apps[1].running = true;
  assert.equal(context.status(preset, data).mode, 'on');
  const pack = { id: 'pack', type: 'package', steps: [{ appId: 'a', action: 'start' }, { appId: 'b', action: 'start' }] };
  const scene = { steps: [{ appId: 'a', action: 'keep' }], packageSteps: [{ packageId: 'pack', action: 'stop' }] };
  assert.deepEqual(JSON.parse(JSON.stringify(context.members(scene, [pack]))), [
    { appId: 'a', action: 'keep' }, { appId: 'b', action: 'stop' }]);
});

test('moving from preset anchor into hover panel keeps the quick controls open', () => {
  const source = readFileSync(new URL('../../static/js/preset-hover.js', import.meta.url), 'utf8');
  let timer, hovered = true, closed = 0;
  const context = vm.createContext({
    clearTimeout() {}, setTimeout: fn => { timer = fn; return 1; },
    panel: { matches: () => hovered }, anchor: { matches: () => false },
    hide: () => closed++, showTimer: null, hideTimer: null,
  });
  vm.runInContext(source.slice(source.indexOf('function scheduleHide('), source.indexOf('function show(')), context);
  context.scheduleHide(); timer(); assert.equal(closed, 0);
  hovered = false; context.scheduleHide(); timer(); assert.equal(closed, 1);
});
