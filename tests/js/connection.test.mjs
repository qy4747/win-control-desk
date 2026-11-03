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
  const state = { data: { schemaVersion: 8, sampledAt: null, configHealth: { migratedFromSchema: 7 } } };
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
  assert.match(banner.textContent, /正在采集/);
  assert.doesNotMatch(banner.textContent, /降级运行/);
  assert.equal(banner.classList.contains('show'), true);
  state.data.sampledAt = 1;
  context.connect(true);
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
  state.data.sampledAt = null;
  context.connect(true);
  assert.match(banner.textContent, /降级运行/);
  assert.doesNotMatch(banner.textContent, /正在采集/);
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

test('startup snapshot waits for a baseline before reporting new services', () => {
  const services = readFileSync(new URL('../../static/js/services.js', import.meta.url), 'utf8');
  const widgets = readFileSync(new URL('../../static/js/widgets.js', import.meta.url), 'utf8');
  const notices = [], events = [];
  const noop = () => {};
  const context = vm.createContext({
    configuredPort: app => app.port, actualPorts: app => app.ports || [],
    toast: message => notices.push(message), pushEvent: (_, title) => events.push(title),
    renderFeeds: noop, renderTopPortsInto: noop, renderTopRes: noop, renderTips: noop,
    setText: noop, refreshCenterPages: noop, topPortsL: {}, topPortsS: {}, railVer: {},
  });
  const code = 'const discoverySeenKeys = new Set(), discoveryItems = new Map(); ' +
    'let discoveryNeedsBaseline = true, prevSnap = null;\n' +
    services.slice(services.indexOf('function serviceSnapshotHealthy'), services.indexOf('function openServiceAppModal')) +
    widgets.slice(widgets.indexOf('export function resetFeedBaseline'), widgets.indexOf('const feedListL')) +
    widgets.slice(widgets.indexOf('function snapshotMaps'), widgets.indexOf('function pushEvent')) +
    widgets.slice(widgets.indexOf('function diffSnapshot'), widgets.indexOf('function feedItem')) +
    widgets.match(/export function renderWidgets\(data\) \{[\s\S]*?\n\}/)[0];
  vm.runInContext(code.replaceAll('export ', ''), context);
  const update = data => { context.observePortDiscovery(data); context.renderWidgets(data); };
  update({ apps: [], services: [], sampledAt: null, degraded: false });
  const existing = { instanceKey: '1:8000', name: 'existing', port: 8000, group: 'mine' };
  update({ apps: [], services: [existing], sampledAt: 1, degraded: false });
  assert.deepEqual(notices, []);
  assert.deepEqual(events, []);
  update({ apps: [], services: [existing, { ...existing, instanceKey: '2:8001', name: 'new', port: 8001 }], sampledAt: 2 });
  assert.equal(notices.length, 1);
  assert.deepEqual(events, ['new 服务已启动']);
});
