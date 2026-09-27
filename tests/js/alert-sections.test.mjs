import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('alert refresh preserves nested disclosures, summary focus and scroll without freezing readings', () => {
  const document = { activeElement: null };
  function el(tag, className = '') {
    return {
      tag, className, children: [], parent: null, textContent: '', open: false, scrollTop: 0,
      get firstElementChild() { return this.children[0]; },
      get isConnected() { return this === content || !!this.parent?.isConnected; },
      contains(node) { return this === node || this.children.some(c => c.contains(node)); },
      remove() {
        if (this.contains(document.activeElement)) document.activeElement = null;
        if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1);
        this.parent = null;
      },
      append(...nodes) { for (const n of nodes) { n.remove(); n.parent = this; this.children.push(n); } },
      replaceChildren(...nodes) {
        for (const n of [...this.children]) n.remove();
        this.scrollTop = 0;
        this.append(...nodes);
      },
      replaceWith(node) {
        const parent = this.parent, index = parent.children.indexOf(this);
        node.remove(); this.remove(); node.parent = parent; parent.children.splice(index, 0, node);
      },
      querySelectorAll() {
        return this.children.flatMap(c => [...(c.className === 'ops-section' ? [c] : []), ...c.querySelectorAll()]);
      },
      focus(options) { assert.equal(options.preventScroll, true); document.activeElement = this; },
    };
  }
  const content = el('div');
  const state = { data: { apps: [], alerts: [], events: [], system: { cpu: 10 },
    rules: ['C:/Demo/A', 'C:/Demo/B'].map(path => ({ metric: 'directorySnapshotGrowthBytes', path, dailyTimes: ['12:00'] })),
    directorySnapshots: {} } };
  const context = vm.createContext({ content, document, state, el, alertTarget: 'system',
    button: () => el('button'), pct: n => String(n), bytes: n => String(n),
  });
  const source = readFileSync(new URL('../../static/js/ops.js', import.meta.url), 'utf8');
  vm.runInContext(source.slice(source.indexOf('function section('), source.indexOf('function show('))
    + source.slice(source.indexOf('function renderAlerts('), source.indexOf('async function executeAction('))
    + source.slice(source.indexOf('function renderDirectorySnapshots('), source.indexOf('async function openRules(')), context);
  context.renderAlerts();
  const sections = () => new Map(content.querySelectorAll().map(n => [n.firstElementChild.textContent, n]));
  const before = sections();
  before.get('资源读数').open = true;
  before.get('最近事件').open = true;
  before.get('C:/Demo/A').open = false;
  before.get('目录定时快照').open = false;
  const summary = before.get('资源读数').firstElementChild;
  document.activeElement = summary; content.scrollTop = 125;
  state.data.system.cpu = 42;
  state.data.events.push({ target: 'system', title: 'Updated event', detail: '', at: 100 });
  context.renderAlerts();
  for (const [label, node] of before) assert.equal(sections().get(label), node, label + ' keeps its DOM node');
  assert.equal(before.get('资源读数').open, true);
  assert.equal(before.get('最近事件').open, true);
  assert.equal(before.get('目录定时快照').open, false);
  assert.equal(before.get('C:/Demo/A').open, false);
  assert.equal(before.get('C:/Demo/B').open, true);
  assert.equal(document.activeElement, summary);
  assert.equal(content.scrollTop, 125);
  assert.match(before.get('资源读数').children[1].textContent, /CPU 42/);
  assert.match(before.get('最近事件').children[1].textContent, /Updated event/);
  before.get('资源读数').open = false;
  context.renderAlerts();
  assert.equal(before.get('资源读数').open, false);
  content.replaceChildren(); // A newly opened page starts with its own defaults.
  context.renderAlerts();
  assert.equal(sections().get('资源读数').open, false);
  assert.equal(sections().get('目录定时快照').open, true);
});
