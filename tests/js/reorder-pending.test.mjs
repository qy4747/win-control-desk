import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('stale polling cannot undo a newly dropped order before the server catches up', () => {
  const source = readFileSync(new URL('../../static/js/launchpad.js', import.meta.url), 'utf8');
  const context = vm.createContext({});
  vm.runInContext('let pendingOrder = ["b", "a"];\n' + source.slice(
    source.indexOf('function preservePendingOrder('), source.indexOf('function announceReorder(')), context);
  const ids = rows => Array.from(rows, row => row.id);
  const stale = [{id:'a'}, {id:'b'}, {id:'task'}];
  assert.deepEqual(ids(context.preservePendingOrder(stale)), ['b','a','task']);
  assert.deepEqual(ids(context.preservePendingOrder(stale)), ['b','a','task']);
  context.preservePendingOrder([{id:'b'}, {id:'a'}, {id:'task'}]);
  assert.equal(context.preservePendingOrder(stale), stale);
});
