import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('scene progress counts finished steps and partial failure never looks successful', () => {
  const source = readFileSync(new URL('../../static/js/ops.js', import.meta.url), 'utf8');
  const context = vm.createContext({});
  vm.runInContext(source.slice(source.indexOf('function sceneRunState('), source.indexOf('function renderSceneRun(')) + '\nthis.read = sceneRunState;', context);
  assert.equal(context.read(null), null);
  const run = { status: 'running', steps: ['succeeded', 'skipped', 'running', 'waiting'].map(status => ({ status })) };
  assert.equal(context.read(run).label, '2/4');
  run.status = 'completed'; run.steps[2].status = 'failed'; run.steps[3].status = 'succeeded';
  assert.equal(context.read(run).kind, 'warning');
  assert.equal(context.read(run).label, '1 项失败');
  run.status = 'canceled';
  assert.equal(context.read(run).kind, 'warning');
  run.steps[2].status = 'skipped';
  assert.equal(context.read(run).kind, 'canceled');
  run.status = 'completed';
  assert.equal(context.read(run).kind, 'success');
  assert.equal(context.read({ status: 'running', steps: [] }).total, 0);
});
