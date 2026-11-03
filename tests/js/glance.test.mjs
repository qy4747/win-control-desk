import test from 'node:test';
import assert from 'node:assert/strict';
import { glanceGroups, glanceStatus, gridNeighbor } from '../../static/js/glance-model.js';
import { viewPoll } from '../../static/js/view-poll.js';

test('status distinguishes running tasks, alerts, blocked and unconfirmed cards', () => {
  for (const [app, state] of [
    [{}, 'stopped'], [{ running: true }, 'running'], [{ kind: 'task', running: true }, 'task'],
    [{ running: true, alerts: [{}] }, 'error'], [{ alerts: [{ ignored: true }] }, 'stopped'],
    [{ health: { blocking: true } }, 'error'], [{ statusKnown: false }, 'unknown'],
  ]) assert.equal(glanceStatus(app)[0], state);
});
test('group filtering retains saved order within launchpad sections', () => {
  const apps = [{ name: 'run', category: 'DEV', kind: 'task' }, { name: 'Code', category: 'DEV' },
    { name: 'Mail', category: 'Desk' }, { name: 'Compiler', category: 'DEV' }];
  assert.deepEqual([...glanceGroups(apps, ' dev ')], [['DEV', [apps[1], apps[3], apps[0]]]]);
  assert.deepEqual([...glanceGroups(apps, 'coDE').values()].flat(), [apps[1]]);
  assert.equal(glanceGroups(apps, 'missing').size, 0);
});
test('arrow navigation respects partial rows, column position and edges', () => {
  const rows = [['a', 'b', 'c'], ['d'], ['e', 'f']];
  assert.equal(gridNeighbor(rows, 'c', 'ArrowDown'), 'd');
  assert.equal(gridNeighbor(rows, 'd', 'ArrowLeft'), 'c');
  assert.equal(gridNeighbor(rows, 'f', 'ArrowUp'), 'd');
  assert.equal(gridNeighbor(rows, 'a', 'ArrowLeft'), 'a');
  assert.equal(gridNeighbor(rows, 'f', 'ArrowRight'), 'f');
});
test('hidden views cancel timers and ignore their stale in-flight responses; resume fetches immediately', async () => {
  const calls = [], timers = new Map(), data = [], errors = [];
  const poll = viewPoll({ url: '/api/state', interval: 3000, timeout: 5000,
    fetcher: (_, { signal }) => new Promise(resolve => calls.push({ signal, resolve })),
    later(fn, ms) { timers.set(fn, ms); return fn; }, cancel: id => timers.delete(id),
    onData: x => data.push(x), onError: e => errors.push(e) });
  poll.setActive(false); assert.equal(calls.length, 0);
  const stale = poll.setActive(true);
  poll.setActive(true); assert.equal(calls.length, 1);
  poll.setActive(false); assert.equal(calls[0].signal.aborted, true);
  const fresh = poll.setActive(true);
  calls[1].resolve({ ok: true, json: async () => 'new' }); await fresh;
  calls[0].resolve({ ok: true, json: async () => 'old' }); await stale;
  assert.deepEqual(data, ['new']); assert.deepEqual(errors, []);
  assert.deepEqual([...timers.values()], [3000]);
  poll.setActive(false); assert.equal(timers.size, 0);
});
test('a visible request times out at five seconds, reports disconnection and schedules a retry', async () => {
  const timers = new Map(), errors = [];
  const poll = viewPoll({ url: '/api/state', interval: 3000, timeout: 5000,
    fetcher: (_, { signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(signal.reason))),
    later(fn, ms) { timers.set(fn, ms); return fn; }, cancel: id => timers.delete(id),
    onData: () => assert.fail('unexpected response'), onError: e => errors.push(e.name) });
  const pending = poll.setActive(true);
  const [deadline, ms] = [...timers][0]; assert.equal(ms, 5000);
  deadline(); await pending;
  assert.deepEqual(errors, ['AbortError']);
  assert.deepEqual([...timers.values()], [3000]);
  poll.setActive(false);
});
