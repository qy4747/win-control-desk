// Offline regression check; never starts or stops real applications.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/ops.js', import.meta.url), 'utf8');
const node = () => ({ childNodes: [], value: '',
  append(...nodes) { this.childNodes.push(...nodes); },
  replaceChildren(...nodes) { this.childNodes = nodes; this.value = nodes[0]?.value || ''; },
  setAttribute() {} });

test('unfinished actions preserve stop selection; preset mode changes keep one editor in history', async () => {
  const stop = node(); stop.value = 'quit';
  const quit = { id: 'quit', name: 'Exit script', type: 'script', when: 'running' };
  const draft = { id: 'draft', name: 'HTTP draft', type: 'http', when: 'always' };
  const failRead = () => { throw new Error('Incomplete HTTP header'); };
  const editors = [quit, draft].map(meta => ({ exitAction: {}, readMeta: () => meta, read: failRead }));
  const context = vm.createContext({ stop, editors, el: node });
  vm.runInContext(source.slice(source.indexOf('  function syncStopActions()'),
    source.indexOf("  stop.addEventListener('change', syncStopActions)")), context);
  context.syncStopActions();
  assert.equal(stop.value, 'quit');
  assert.equal(editors[0].exitAction.checked, true);
  editors[1].removed = true; editors[1].readMeta = failRead;
  context.syncStopActions();
  assert.equal(stop.value, 'quit');
  assert.equal(stop.childNodes.length, 2);
  quit.when = 'stopped'; context.syncStopActions();
  assert.equal(stop.value, '');
  assert.equal(editors[0].exitAction.disabled, true);

  const content = node(), heading = { textContent: 'Manage' }, history = [];
  const config = { presets: [], rules: [] };
  Object.assign(context, {
    content, heading, history, config, close: {}, document: {},
    panel: { classList: { contains: () => true } },
    hasParentLayer: false, detailId: null, detailStatus: null, detailEvents: null,
    alertTarget: null, pageKey: null, closeBubble() {}, activeLayer() {},
    openLayer() {}, closeLayer() {}, renderDetail() {}, toast() {},
    state: { data: { apps: [] } }, crypto: { randomUUID: () => 'new-preset' },
    button: (text, click) => Object.assign(node(), { text, click }),
    field: (parent, label, value) => {
      const input = Object.assign(node(), { label, value }); parent.append(input); return input;
    },
    section: parent => { const section = node(); parent.append(section); return section; },
    iconActionPicker: () => [],
    act: async result => result,
    post: async (_, data) => { config.presets = data.presets; return { ok: true }; },
    openPresets: async (_, replace) => context.show('Manage', replace),
  });
  vm.runInContext(source.slice(source.indexOf('function show('), source.indexOf('export function bytes('))
    .replace('export function closeOps', 'function closeOps'), context);
  vm.runInContext(source.slice(source.indexOf('function editPreset('), source.indexOf('function confirmPreset(')), context);
  context.editPreset();
  for (const mode of ['应用包模式', '场景模式', '应用包模式', '场景模式']) {
    content.childNodes[0].childNodes.find(button => button.text === mode).click();
    assert.equal(history.length, 1);
  }
  await content.childNodes.find(button => button.text === '保存预设').click();
  assert.equal(config.presets.length, 1);
  assert.equal(heading.textContent, 'Manage');
  assert.equal(history.length, 0);
  context.closeOps();
  assert.equal(content.childNodes.length, 0);
});
