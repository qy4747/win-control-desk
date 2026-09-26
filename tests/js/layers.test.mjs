import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('nested layers return to the parent and restore focus without exposing the background', () => {
  const document = { activeElement: null, querySelector: () => shell };
  function node() {
    const classes = new Set();
    return { style: {}, attributes: {}, inert: true, isConnected: true,
      classList: { add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c) },
      setAttribute(k, v) { this.attributes[k] = v; },
      contains: () => false, blur() { document.activeElement = null; },
      getClientRects: () => [1], focus() { document.activeElement = this; },
    };
  }
  const shell = node(), home = node(), parent = node(), trigger = node(), child = node(), input = node();
  const source = readFileSync(new URL('../../static/js/core.js', import.meta.url), 'utf8');
  const block = source.slice(source.indexOf('const layerReturnFocus'), source.indexOf('/* ---------------- 按 key'));
  const context = vm.createContext({ document, setTimeout: f => f(), clearTimeout: () => {} });
  vm.runInContext(block.replaceAll('export function', 'function') + '\nthis.api = {openLayer, closeLayer, activeLayer};', context);
  const { openLayer, closeLayer, activeLayer } = context.api;
  home.focus(); openLayer(parent, trigger);
  parent.draft = 'unsaved';
  openLayer(child, input);
  child.contains = element => element === input;
  assert.equal(activeLayer(), child);
  assert.equal(parent.inert, true);
  assert.equal(parent.attributes['aria-hidden'], 'true');
  assert.equal(shell.inert, true);
  closeLayer(child);
  assert.equal(activeLayer(), parent);
  assert.equal(parent.draft, 'unsaved');
  assert.equal(parent.inert, false);
  assert.equal(parent.style.display, '');
  assert.equal(document.activeElement, trigger);
  assert.equal(shell.inert, true);
  // Refreshing an open panel must not add a second frame or lose its original focus target.
  openLayer(parent, trigger);
  closeLayer(parent);
  assert.equal(activeLayer(), null);
  assert.equal(shell.inert, false);
  assert.equal(document.activeElement, home);
});
