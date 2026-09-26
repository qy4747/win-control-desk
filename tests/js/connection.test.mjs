import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('health notices stay connected; failures, restart and stop stay disconnected until recovery', () => {
  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const widgets = readFileSync(new URL('../../static/js/widgets.js', import.meta.url), 'utf8');
  function node() {
    const classes = new Set();
    return { dataset: {}, setAttribute() {}, classList: {
      add: name => classes.add(name), contains: name => classes.has(name),
      toggle: (name, on) => on ? classes.add(name) : classes.delete(name) } };
  }
  const banner = node(), railConnDot = node(), railConnText = node();
  const state = { data: { schemaVersion: 8, configHealth: { migratedFromSchema: 7 } } };
  const notices = [], saved = new Map();
  let observed;
  const context = vm.createContext({ banner, state, railConnDot, railConnText,
    toast: (message, duration) => notices.push({ message, duration }),
    localStorage: { getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value) },
    DISCONNECTED_TEXT: '连接断开', setText: (n, text) => { n.textContent = text; },
    MutationObserver: class { observe(target, options) { observed = options.attributeFilter; } } });
  vm.runInContext(app.slice(app.indexOf('const HEALTH_COMPONENT_NAMES'), app.indexOf('function render()')) +
    widgets.slice(widgets.indexOf('  const syncConn ='), widgets.indexOf('\n\n  tipsAction')) +
    '\nthis.connect = (ok) => { setConnected(ok); syncConn(); };', context);
  assert.equal(observed.join(), 'data-connection');
  context.connect(true);
  assert.equal(railConnText.textContent, '已连接');
  assert.equal(banner.classList.contains('show'), false);
  assert.match(notices[0].message, /配置已从旧版本升级/);
  assert.equal(notices[0].duration, 4000);
  context.connect(true);
  assert.equal(notices.length, 1);
  // A reload resets the in-memory marker, but does not repeat the same migration notice.
  vm.runInContext('migrationNoticeVersion = null;', context);
  context.connect(true);
  assert.equal(notices.length, 1);
  context.connect(false);
  assert.equal(railConnText.textContent, '连接中断');
  assert.equal(railConnDot.classList.contains('danger'), true);
  context.connect(true);
  assert.equal(railConnText.textContent, '已连接');
  state.data.degraded = true;
  context.connect(true);
  assert.equal(railConnText.textContent, '已连接');
  assert.match(banner.textContent, /降级运行/);
  for (const flag of ['restartingFrom', 'stopping']) {
    state[flag] = true;
    banner.textContent = '正在执行';
    context.connect(false);
    context.connect(true);
    assert.equal(railConnText.textContent, '连接中断');
    assert.equal(banner.textContent, '正在执行');
    state[flag] = false;
    context.connect(true);
    assert.equal(railConnText.textContent, '已连接');
  }
});
