import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('all six pages navigate, persist and expose only the selected panel', () => {
  function node(view) {
    const classes = new Set();
    return { dataset: { view }, attributes: {},
      classList: { add: c => classes.add(c), remove: c => classes.delete(c),
        toggle: (c, on) => on ? classes.add(c) : classes.delete(c), contains: c => classes.has(c) },
      setAttribute(k, v) { this.attributes[k] = v; }, removeAttribute(k) { delete this.attributes[k]; }
    };
  }
  const names = ['launchpad', 'services', 'logs', 'settings', 'folders', 'files'];
  const views = Object.fromEntries(names.map(v => [v, node(v)]));
  const railBtns = names.map(node), stored = {}, state = { view: 'launchpad' };
  let refreshes = 0;
  const context = vm.createContext({ views, state, railBtns, navBtns: [], sideLaunch: {}, sideSvc: {},
    viewTitle: {}, viewOverline: {}, viewSub: {}, document: { documentElement: { dataset: {} } },
    setText: (n, value) => { n.textContent = value; }, refreshCenterPages: () => refreshes++, showFilePage: () => {}, stopFilePreview: () => {},
    localStorage: { setItem: (k, v) => { stored[k] = v; } } });
  const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  vm.runInContext(source.slice(source.indexOf('function switchView('), source.indexOf("navBtns.forEach(b => b.addEventListener")) + '\nthis.navigate = switchView;', context);
  for (const target of ['logs', 'settings', 'folders', 'files', 'services', 'launchpad']) {
    context.navigate(target);
    assert.equal(stored['console-view'], target);
    assert.equal(railBtns.find(b => b.attributes['aria-current'] === 'page').dataset.view, target);
    for (const name of names) {
      assert.equal(views[name].classList.contains('active'), name === target);
      assert.equal(views[name].attributes['aria-hidden'], String(name !== target));
    }
  }
  context.navigate('unknown');
  context.navigate('launchpad');
  assert.equal(state.view, 'launchpad');
  assert.equal(refreshes, 6);
});
