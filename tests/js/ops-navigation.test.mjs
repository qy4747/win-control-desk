import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('detail navigation deduplicates by identity and bounds retained pages', () => {
  const source = readFileSync(new URL('../../static/js/ops.js', import.meta.url), 'utf8');
  let open = false;
  const content = { childNodes: [], scrollTop: 0, replaceChildren(...nodes) { this.childNodes = nodes; } };
  const context = vm.createContext({ content, heading: { textContent: '' }, close: {},
    panel: { classList: { contains: () => open } }, document: { activeElement: null },
    closeBubble() {}, activeLayer: () => null, openLayer() { open = true; },
    closeLayer() { open = false; }, renderDetail() {} });
  vm.runInContext(`const history = []; let hasParentLayer = false, pageKey = null,
    detailId = null, detailStatus = null, detailEvents = null, alertTarget = null;` +
    source.slice(source.indexOf('function show('), source.indexOf('export function bytes(')).replace('export function', 'function') +
    '\nthis.show = show; this.close = closeOps; this.depth = () => history.length;', context);
  context.show('Same name', false, 'details:a');
  for (let i = 0; i < 30; i++) {
    context.show('Alert', false, 'alerts:a');
    assert.equal(context.show('Same name', false, 'details:a'), false);
    assert.equal(context.depth(), 0);
  }
  assert.equal(context.show('Same name', false, 'details:b'), true);
  for (let i = 0; i < 20; i++) context.show('Page ' + i);
  assert.equal(context.depth(), 8);
  while (context.depth()) context.close();
  context.close();
  assert.equal(open, false);
  assert.equal(content.childNodes.length, 0);
});
