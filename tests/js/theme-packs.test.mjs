import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('material packs use their own stylesheet and preserve theme rollback and switching', async () => {
  const source = readFileSync(new URL('../../static/js/core.js', import.meta.url), 'utf8');
  const listeners = new Map(), saved = new Map();
  let href = '/themes/ops.css', failSave = false;
  const link = {
    sheet: {}, get href() { return 'http://localhost' + href; },
    set href(value) { href = value; queueMicrotask(() => listeners.get('load')?.()); },
    getAttribute() { return href; },
    addEventListener(name, callback) { listeners.set(name, callback); },
    removeEventListener(name) { listeners.delete(name); },
  };
  const root = { dataset: { uiTheme: 'ops', theme: 'dark' } };
  const state = { data: { uiTheme: 'ops', themes: [
    { id: 'ops' }, { id: 'apple' },
    { id: 'pack-journal', css: '/themes/packs/journal/theme.css' },
  ] } };
  const context = vm.createContext({ state, document: { documentElement: root },
    $: () => link, URL, location: { href: 'http://localhost/' }, setTimeout, clearTimeout,
    localStorage: { getItem: key => saved.get(key) ?? null,
      setItem: (key, value) => saved.set(key, value), removeItem: key => saved.delete(key) },
    post: async () => ({ ok: !failSave }), toast() {},
  });
  vm.runInContext(source.slice(source.indexOf('let pendingPersistedUiTheme')).replaceAll('export function', 'function'), context);
  assert.equal(await context.applyUiTheme('pack-journal', true), true);
  assert.equal(href, '/themes/packs/journal/theme.css');
  assert.equal(saved.get('console-ui-theme'), 'pack-journal');
  failSave = true;
  assert.equal(await context.applyUiTheme('apple', true), false);
  assert.equal(href, '/themes/packs/journal/theme.css');
  assert.equal(root.dataset.uiTheme, 'pack-journal');
  failSave = false;
  assert.equal(await context.applyUiTheme('apple', true), true);
  assert.equal(href, '/themes/apple.css');
  assert.equal(await context.applyUiTheme('ops', true), true);
  assert.equal(href, '/themes/ops.css');
  assert.equal(root.dataset.theme, 'dark');
  state.data = null;
  root.dataset.uiTheme = 'pack-journal';
  saved.set('console-ui-theme', 'apple');
  assert.equal(context.currentUiTheme(), 'pack-journal', 'server-selected first paint must beat a stale browser cache');
});

test('startup applies appearance before the app and supports unavailable storage', () => {
  const source = readFileSync(new URL('../../static/js/theme-startup.js', import.meta.url), 'utf8');
  for (const [saved, darkSystem, blocked, expected] of [
    ['dark', false, false, 'dark'], ['light', true, false, 'light'],
    [null, true, false, 'dark'], [null, false, true, 'light'],
  ]) {
    const root = { dataset: {} };
    vm.runInNewContext(source, { document: { documentElement: root },
      matchMedia: () => ({ matches: darkSystem }),
      localStorage: { getItem(key) { if (blocked) throw Error('blocked'); return key === 'console-theme' ? saved : 'off'; } },
    });
    assert.equal(root.dataset.theme, expected);
    assert.equal(root.dataset.rainMist, blocked ? 'on' : 'off');
  }
});
