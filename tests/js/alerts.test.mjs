import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('ignored app alerts disappear without recreating their configuration warning', () => {
  const source = readFileSync(new URL('../../static/js/ops.js', import.meta.url), 'utf8');
  const context = vm.createContext({});
  vm.runInContext(source.slice(source.indexOf('function appAlerts('), source.indexOf('function openAlerts(')) + '\nthis.read = appAlerts;', context);
  const app = { health: { blocking: true, issues: [{ title: 'invalid config' }] },
    alerts: [{ key: 'app:a:config', ignored: true }, { key: 'app:a:cpu', ignored: false }] };
  assert.equal(context.read(app).length, 1);
  assert.equal(context.read(app)[0].key, 'app:a:cpu');
  app.alerts[1].ignored = true;
  assert.equal(context.read(app).length, 0);
  app.alerts = [{ key: 'app:a:config', ignored: false }];
  assert.equal(context.read(app).length, 1);
});

test('card extras own only the alert state, including after an alert is ignored', () => {
  const source = readFileSync(new URL('../../static/js/ops.js', import.meta.url), 'utf8');
  function node(initial = []) {
    const classes = new Set(initial);
    return { children: [], classList: { toggle: (c, on) => on ? classes.add(c) : classes.delete(c),
      remove: c => classes.delete(c), contains: c => classes.has(c) }, setAttribute() {},
      append(child) { this.children.push(child); }, replaceChildren() { this.children = []; } };
  }
  const app = { name: 'sample', alerts: [{ title: 'sample · CPU', ignored: false }] };
  const card = node(['has-error']);
  card._r = { stText: node(['fail']), dot: node(['danger']),
    primary: { disabled: false }, restart: { disabled: false } };
  // Use a complete DOM contract, not a copy of the production cache signature.
  card._ops = { kind: node(), resources: node(), summary: node(), alert: node(),
    custom: node(), buttons: node() };
  const context = vm.createContext({ pct: () => '—', bytes: () => '—',
    cardButtonSpecs: () => [],
    setText: (n, text) => { n.textContent = text; } });
  vm.runInContext(source.slice(source.indexOf('function appAlerts('), source.indexOf('function openAlerts(')) +
    source.slice(source.indexOf('export function updateCardExtras('), source.indexOf('function defaultButtons(')).replace('export function', 'function') +
    '\nthis.update = updateCardExtras;', context);
  context.update(card, app);
  assert.equal(card.classList.contains('has-alert'), true);
  app.alerts[0].ignored = true;
  context.update(card, app);
  assert.equal(card.classList.contains('has-alert'), false);
  assert.equal(card.classList.contains('has-error'), true);
  assert.equal(card._r.stText.classList.contains('fail'), true);
  assert.equal(card._r.dot.classList.contains('danger'), true);
});

test('fixed controls follow runtime state, locations stay usable, and configured hiding is preserved', () => {
  const source = readFileSync(new URL('../../static/js/ops.js', import.meta.url), 'utf8');
  const node = () => ({ children: [], classList: { toggle() {} }, setAttribute() {},
    append(child) { this.children.push(child); }, replaceChildren() { this.children = []; } });
  const app = { id: 'a', name: 'sample', kind: 'desktop', running: true, windowBinding: { hwnd: 123 },
    actions: [{ id: 'repo', name: '目录', type: 'location', when: 'always' },
      { id: 'refresh', name: '刷新应用', type: 'command', when: 'running' }],
    cardButtons: [
      { action: 'custom:repo', placement: 'primary', when: 'always' },
      { action: 'custom:refresh', placement: 'card', when: 'always' },
      { action: 'details', name: '运行时显示', placement: 'menu', when: 'running' },
    ] };
  const card = node();
  card._r = { primary: { disabled: false }, restart: { disabled: false } };
  card._ops = { kind: node(), resources: node(), summary: node(), alert: node(), custom: node(), buttons: node(), signature: '' };
  const context = vm.createContext({ pct: () => '—', bytes: () => '—', appAlerts: () => [], state: { data: { platform: 'win32', apps: [app] } },
    preferredOpenPort: () => null, setText() {}, button: (label, run, classes) => ({ label, run, classes }) });
  vm.runInContext(source.slice(source.indexOf('const windowActions ='), source.indexOf('async function flipCard(')) + '\n' + source.slice(source.indexOf('export function updateCardExtras('), source.indexOf('function openButtons(')).replace('export function', 'function') +
    '\nthis.update = updateCardExtras;', context);
  context.update(card, app);
  assert.deepEqual(card._ops.buttons.children.map(b => b.label), ['关闭', '前台', '目录', '刷新应用']);
  assert.ok(card._ops.buttons.children.every(b => !b.disabled));
  assert.equal(card._ops.buttons.children.filter(b => b.classes.includes('btn-accent')).length, 1);
  app.running = false;
  context.update(card, app);
  assert.deepEqual(card._ops.buttons.children.map(b => b.label), ['打开', '前台', '目录', '刷新应用']);
  assert.deepEqual(card._ops.buttons.children.map(b => !!b.disabled), [false, true, false, true]);
  assert.ok(!card._ops.custom.children.some(b => b.label === '运行时显示'));
  app.statusKnown = false;
  card._r.primary.disabled = true;
  context.update(card, app);
  assert.deepEqual(card._ops.buttons.children.map(b => !!b.disabled), [true, true, false, true]);
  app.statusKnown = true; app.running = true; card._r.primary.disabled = false;
  app.windowBinding = null;
  context.update(card, app);
  assert.equal(card._ops.buttons.children[1].disabled, false);
  assert.equal(card._ops.buttons.children[1].title, '选择要唤到前台的窗口');
});
