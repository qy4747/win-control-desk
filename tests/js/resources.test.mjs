import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('../../static/js/resources.js', import.meta.url), 'utf8');
const { topResources } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));

test('rankings count app trees once and deduplicate listeners before summing processes', () => {
  const data = { system: { memoryTotalBytes: 1000 }, apps: [
    { id: 'deck', name: 'Stream Deck', running: true, pids: [1, 2], resources: { cpu: 20, memoryBytes: 100, gpuMemoryBytes: 30 } },
  ], services: [
    { pid: 1, port: 80, appId: 'deck', cpu: 10 }, { pid: 1, port: 81, appId: 'deck', cpu: 10 },
    { pid: 2, appId: 'deck', cpu: 10 },
    { pid: 3, appId: 'other', appName: 'Other', cpu: 2, mem: 1, gpuMemoryBytes: 40 },
    { pid: 3, appId: 'other', appName: 'Other', cpu: 2, mem: 1, gpuMemoryBytes: 40 },
    { pid: 4, appId: 'other', appName: 'Other', cpu: 3, mem: 2, gpuMemoryBytes: 20 },
    { pid: 5, name: 'Unknown', cpu: null },
  ] };
  assert.deepEqual(topResources(data, 'cpu').map(r => [r.name, r.cpu]), [['Stream Deck', 20], ['Other', 5]]);
  assert.deepEqual(topResources(data, 'mem').map(r => r.mem), [10, 3]);
  assert.deepEqual(topResources(data, 'gpuMemoryBytes').map(r => [r.name, r.gpuMemoryBytes]), [['Other', 60], ['Stream Deck', 30]]);
});

test('unregistered apps use the process name rather than the working folder', () => {
  const data = { services: [{ pid: 7, name: 'SketchUp.exe', project: 'Documents', gpuMemoryBytes: 100 }] };
  assert.equal(topResources(data, 'gpuMemoryBytes')[0].name, 'SketchUp.exe');
});
