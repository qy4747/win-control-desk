import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('service port replaces foreground and the old web action without duplicating buttons', () => {
  const source = readFileSync(new URL('../../static/js/ops.js', import.meta.url), 'utf8');
  const context = vm.createContext({});
  vm.runInContext(source.slice(source.indexOf('function cardButtonSpecs('), source.indexOf('async function flipCard(')), context);
  const app = { kind: 'service', actions: [{id:'repo'},{id:'config'}], cardButtons: [
    {action:'toggle',placement:'primary'}, {action:'window:focus',placement:'card'},
    {action:'web',placement:'card'}, {action:'custom:repo',placement:'card'}
  ]};
  const specs = context.cardButtonSpecs(app);
  assert.deepEqual(Array.from(specs.filter(s => s.placement !== 'menu'), s => s.action),
    ['toggle','web','custom:repo']);
  assert.equal(specs.some(s => s.action === 'custom:config'), false, 'a saved removal must not be silently restored');
  assert.equal(specs.filter(s => s.action === 'web').length, 1);
  assert.equal(specs[1].when, 'always');
  assert.equal(context.cardButtonSpecs({...app,kind:'desktop'})[1].action, 'window:focus');
});

test('default service layout keeps both feature slots after replacing foreground with port', () => {
  const source = readFileSync(new URL('../../static/js/ops.js', import.meta.url), 'utf8');
  const context = vm.createContext({});
  vm.runInContext(source.slice(source.indexOf('function cardButtonSpecs('), source.indexOf('async function flipCard(')) +
    source.slice(source.indexOf('function defaultButtons('), source.indexOf('function openButtons(')), context);
  for (const port of [null, 8765]) {
    const specs = context.cardButtonSpecs({kind: 'service', port, actions: [{id:'repo'}, {id:'config'}]});
    assert.deepEqual(Array.from(specs.filter(s => s.placement !== 'menu'), s => s.action),
      ['toggle', 'web', 'custom:repo', 'custom:config']);
    assert.equal(specs.filter(s => s.action === 'web').length, 1);
  }
});
