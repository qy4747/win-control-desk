import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('preview keeps the newest selection, serializes close, and leaves input keys alone', async () => {
  const requests = [], nodes = new Map(), selected = [];
  const context = vm.createContext({
    $: key => { if (!nodes.has(key)) nodes.set(key, {}); return nodes.get(key); },
    toast: () => {},
    postWithTimeout: (url, body) => new Promise(resolve => requests.push({ body, resolve })),
    select: index => selected.push(index)
  });
  const source = readFileSync(new URL('../../static/js/file-search.js', import.meta.url), 'utf8');
  vm.runInContext(source.replace(/^import .*;\n/gm, '').replace(/^export /gm, '') + `
    this.request = requestPreview; this.stop = stopFilePreview; this.key = resultKeydown;
    this.enable = () => { previewActive = true; resultItems = [{path:'a'}, {path:'b'}]; selectedIndex = 0; };
    selectResult = index => { selectedIndex = index; select(index); };
  `, context);
  context.enable();
  const pending = context.request('show', 'a');
  context.request('switch', 'b'); context.request('switch', 'c');
  assert.equal(requests.length, 1);
  requests[0].resolve({ok:true}); await new Promise(setImmediate);
  assert.equal(requests[1].body.path, 'c');
  context.stop(); requests[1].resolve({ok:true}); await new Promise(setImmediate);
  assert.equal(requests[2].body.action, 'close');
  requests[2].resolve({ok:true}); await pending;
  // Closing is still in flight when show(B) is followed by switch(C).
  let nativeVisible = true;
  const closing = context.request('close');
  context.enable(); context.request('show', 'b'); context.request('switch', 'c');
  nativeVisible = false;
  requests[3].resolve({ok:true}); await new Promise(setImmediate);
  assert.equal(requests[4].body.action, 'show');
  assert.equal(requests[4].body.path, 'c');
  if (requests[4].body.action === 'show') nativeVisible = true;
  requests[4].resolve({ok:true}); await closing;
  assert.equal(nativeVisible, true);
  context.enable();
  let prevented = false;
  context.key({key:'ArrowDown', target:{closest:()=>true}, preventDefault(){prevented=true;}});
  assert.equal(prevented, false); assert.equal(selected.length, 0);
  context.key({key:'ArrowDown', target:{closest:()=>false}, preventDefault(){prevented=true;}});
  assert.equal(prevented, true); assert.deepEqual(selected, [1]);
});

test('only the newest ES response can replace results and reset discards in-flight responses', async () => {
  const nodes = new Map();
  const $ = key => {
    if (!nodes.has(key)) nodes.set(key, { textContent: '', attributes: {}, disabled: false,
      setAttribute(k, v) { this.attributes[k] = v; }, addEventListener() {} });
    return nodes.get(key);
  };
  const requests = [], shown = [];
  const context = vm.createContext({ $, AbortSignal, document: { querySelectorAll: () => [] },
    fileConfig: () => ({}), loadFileConfig: async () => ({}),
    postWithTimeout: (path, body) => new Promise(resolve => requests.push({ body, resolve })) });
  const source = readFileSync(new URL('../../static/js/file-search.js', import.meta.url), 'utf8');
  vm.runInContext(source.replace(/^import .*;\n/gm, '').replace(/^export /gm, '') + `
    filters = () => ({ query: 'design' });
    empty = () => {};
    renderResults = items => shown.push(items);
    this.run = runSearch;
    this.reset = () => { ++generation; };
  `.replace('shown.push(items)', 'this.shown.push(items)'), context);
  context.shown = shown;
  const first = context.run(1, true), second = context.run(1, true);
  requests[1].resolve({ ok: true, items: ['new'], hasMore: true }); await second;
  requests[0].resolve({ ok: false, error: 'stale failure' }); await first;
  assert.deepEqual(shown, [['new']]);
  assert.equal($('#fileEngineStatus').textContent, 'Everything 已连接');
  assert.equal($('#filesNext').disabled, false);
  const third = context.run(2); context.reset();
  requests[2].resolve({ ok: true, items: ['discarded'], hasMore: false }); await third;
  assert.deepEqual(shown, [['new']]);
});
