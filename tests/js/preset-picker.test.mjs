// Offline DOM stub: exercises selection only, never calls application APIs.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('scene icons cycle start-stop-clear; package icons toggle; filtering retains selections', () => {
  const node = (tag, cls) => ({ tag, cls, children: [], dataset: {}, attributes: {}, events: {}, value: '',
    classList: { toggle() {} }, append(...nodes) { this.children.push(...nodes); },
    setAttribute(key, value) { this.attributes[key] = value; },
    addEventListener(key, fn) { this.events[key] = fn; } });
  const context = vm.createContext({
    el: node, icon: () => node('icon'), getIconVer: () => '',
    setText: (n, text) => { n.textContent = text; },
    button: (text, click, cls) => Object.assign(node('button', cls), { textContent: text, click }),
    field: parent => { const input = node('input'); parent.append(input); return input; },
  });
  const source = readFileSync(new URL('../../static/js/ops.js', import.meta.url), 'utf8');
  vm.runInContext(source.slice(source.indexOf('function iconActionPicker('), source.indexOf('function editPreset(')), context);
  const root = node('root'), items = [{ id: 'a', name: 'Alpha' }, { id: 'b', name: 'Beta' }];
  const fields = context.iconActionPicker(root, items, new Map([['a', 'start'], ['b', 'stop']]),
    [['start', '打开'], ['stop', '关闭']]);
  const values = new Map(fields), [search, grid] = root.children[0].children;
  assert.equal(values.get('a').value, 'start');
  assert.equal(values.get('b').value, 'stop');
  grid.children[0].click();
  assert.equal(values.get('a').value, 'stop');
  grid.children[0].click(); assert.equal(values.get('a').value, '');
  search.value = 'Alpha'; search.events.input();
  assert.equal(grid.children[1].hidden, true);
  assert.equal(values.get('b').value, 'stop');
  grid.children[0].click();
  assert.equal(values.get('a').value, 'start');
  assert.equal(grid.children[0].attributes['aria-pressed'], 'true');
  const pack = node('root');
  const members = new Map(context.iconActionPicker(pack, items, new Map([['a', 'start']]), [['start', '已加入']]));
  pack.children[0].children[1].children[0].click();
  assert.equal(members.get('a').value, '');
  pack.children[0].children[1].children[1].click();
  assert.equal(members.get('b').value, 'start');
});
