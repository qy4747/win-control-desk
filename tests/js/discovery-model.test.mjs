import { test } from 'node:test';
import assert from 'node:assert/strict';
import { aiHandoff, discoveryCounts, discoveryRows, quickAddPayload, rowKey } from '../../static/js/discovery-model.js';

const items = [
  { pid: 1, created: 'a', name: '画图', exe: 'C:\\Apps\\Paint\\paint.exe', ports: [], kind: 'desktop', card: null },
  { pid: 2, created: 'b', name: 'python', exe: 'C:\\Py\\python.exe', ports: [8899], kind: 'service', card: null },
  { pid: 3, created: 'c', name: '笔记', exe: 'C:\\Apps\\Note\\note.exe', ports: [], kind: 'desktop', card: { id: 'n1', name: '笔记', state: 'managed' } },
  { pid: 4, created: 'd', name: '音乐', exe: 'C:\\Apps\\Music\\music.exe', ports: [], kind: 'desktop', card: { id: 'm1', name: '音乐', state: 'similar' } },
];

test('unadded filter hides only processes a card already controls', () => {
  assert.deepEqual(discoveryRows(items).map(r => r.pid), [1, 2, 4]);
  assert.deepEqual(discoveryRows(items, '', false).map(r => r.pid), [1, 2, 3, 4]);
  assert.deepEqual(discoveryRows(items, 'paint').map(r => r.pid), [1]);
  assert.deepEqual(discoveryCounts(items), { unadded: 2, managed: 1, similar: 1 });
  assert.equal(rowKey(items[0]), '1@a');
});

test('quick add relaunches ordinary programs but keeps interpreters as observation cards', () => {
  assert.deepEqual(quickAddPayload(items[0]), { pid: 1, created: 'a', name: '画图', kind: 'desktop',
    command: '"C:\\Apps\\Paint\\paint.exe"', shell: 'cmd', cwd: 'C:\\Apps\\Paint', port: null });
  const py = quickAddPayload(items[1]);
  assert.equal(py.command, ''); assert.equal(py.cwd, null); assert.equal(py.port, 8899); assert.equal(py.kind, 'service');
});

test('AI handoff carries identities, plan skeleton and the no-start/stop boundary', () => {
  const text = aiHandoff([items[0], items[3]], { cwd: 'D:\\console', port: 9601 });
  assert.match(text, /D:\\console/);
  assert.match(text, /--url http:\/\/127\.0\.0\.1:9601 discover/);
  assert.match(text, /不要启动、停止或结束任何进程/);
  assert.match(text, /可能对应已有卡片「音乐」/);
  const plan = JSON.parse(text.split('```json\n')[1].split('\n```')[0]);
  assert.deepEqual(plan.apps, [
    { name: '画图', pid: 1, created: 'a', kind: 'desktop' },
    { name: '音乐', pid: 4, created: 'd', kind: 'desktop', appId: 'm1' },
  ]);
});
