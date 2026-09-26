import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('saved button removal persists; explicit stop action stays available in menu', () => {
  const source = readFileSync(new URL('../../static/js/ops.js', import.meta.url), 'utf8');
  const context = vm.createContext({});
  vm.runInContext(source.slice(source.indexOf('function cardButtonSpecs('), source.indexOf('async function flipCard(')) +
    source.slice(source.indexOf('function defaultButtons('), source.indexOf('function openButtons(')) +
    '\nthis.specs = cardButtonSpecs;', context);
  const app = { kind: 'service', stopAction: 'stop-process', actions: [{ id: 'stop-process' }, { id: 'repo' }] };
  assert.equal(context.specs(app).some(b => b.action === 'custom:stop-process'), false);
  assert.equal(context.specs({ ...app, cardButtons: [] }).length, 2);
  const saved = context.specs({ ...app, cardButtons: [{ action: 'custom:stop-process', placement: 'menu' }] });
  assert.equal(saved.length, 3);
  assert.equal(saved[2].placement, 'menu');
});

test('stop completion enables the rendered open button after a busy-state poll', async () => {
  const ops = readFileSync(new URL('../../static/js/ops.js', import.meta.url), 'utf8');
  const launch = readFileSync(new URL('../../static/js/launchpad.js', import.meta.url), 'utf8');
  const node = () => ({ children: [], dataset: {}, classList: { toggle() {} },
    setAttribute() {}, append(child) { this.children.push(child); },
    replaceChildren() { this.children = []; } });
  const app = { id: 'a', name: 'App', running: true, canStart: true, statusKnown: true, kind: 'desktop' };
  const primary = { disabled: false, dataset: {} };
  const card = { classList: { toggle() {} }, _r: { primary, restart: { disabled: false } },
    _ops: Object.fromEntries(['kind', 'resources', 'summary', 'alert', 'custom', 'buttons'].map(k => [k, node()])) };
  primary.closest = () => card;
  let context, requests = 0;
  context = vm.createContext({
    state: { data: { apps: [app], platform: 'win32' } }, findApp: () => app,
    toast() {}, post: async () => { requests++; return { ok: true }; }, act: promise => promise,
    setText: (el, text) => { el.textContent = text; }, pct: () => '', bytes: () => '',
    appAlerts: () => [], preferredOpenPort: () => null, windowActions: [],
    cardButtonSpecs: () => [{ action: 'toggle', placement: 'primary', when: 'always' }],
    actionAvailable: () => true,
    button: (text, click) => ({ textContent: text, click, disabled: false }),
    window: { __poll: async () => {
      app.running = false;
      context.updateCardExtras(card, app);
      assert.equal(card._ops.buttons.children[0].textContent, '打开');
      assert.equal(card._ops.buttons.children[0].disabled, true);
    } },
  });
  vm.runInContext(ops.slice(ops.indexOf('export function updateCardExtras('), ops.indexOf('function defaultButtons(')).replace('export ', '') +
    launch.slice(launch.indexOf('async function toggleApp('), launch.indexOf('export { toggleApp };')), context);
  await context.toggleApp('a', primary, true);
  assert.equal(primary.dataset.busy, undefined);
  assert.equal(card._ops.buttons.children[0].textContent, '打开');
  assert.equal(card._ops.buttons.children[0].disabled, false);
  await context.toggleApp('a', primary, true, 'stop');
  assert.equal(requests, 1, 'a delayed stop must not restart an app that already stopped');
  let foreground = 0, diagnostics = 0;
  context.cardButtonSpecs = () => [{ action: 'toggle', placement: 'primary' }, { action: 'web', placement: 'card' }];
  context.preferredOpenPort = () => 8765;
  context.portIsOpenable = () => false;
  context.executeWindow = async (id, operation) => {
    assert.equal(id, 'a'); assert.equal(operation, 'focus'); foreground++;
  };
  card._r.stPort = { click: () => diagnostics++ };
  app.port = 8765; app.kind = 'service'; app.portOccupied = true;
  context.updateCardExtras(card, app);
  assert.equal(card._ops.buttons.children[1].disabled, true, 'stopped service cannot focus an unrelated port owner');
  app.portOccupied = false; app.running = true;
  context.updateCardExtras(card, app);
  assert.equal(card._ops.buttons.children[1].disabled, true, 'not-ready unbound service remains unavailable');
  app.windowBinding = { hwnd: 123 };
  context.updateCardExtras(card, app);
  assert.equal(card._ops.buttons.children[1].disabled, false);
  await card._ops.buttons.children[1].click();
  assert.equal(foreground, 1);
  assert.equal(diagnostics, 0, 'service button uses the verified window route, not the old diagnostic action');
  app.statusKnown = false;
  context.updateCardExtras(card, app);
  assert.equal(card._ops.buttons.children[1].disabled, true);
});
