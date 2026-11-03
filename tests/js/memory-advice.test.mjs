import { test } from 'node:test';
import assert from 'node:assert/strict';
import { commitAdvice, commitLevel, commitTopRows } from '../../static/js/memory-advice.js';
import { scenePlan } from '../../static/js/scene-plan.js';

const GIB = 1024 ** 3;

test('commit levels and advice name consumers, uptime and a small page file', () => {
  assert.equal(commitLevel(null).level, 'unknown');
  assert.equal(commitLevel(40).level, 'normal');
  assert.equal(commitLevel(65).level, 'watch');
  assert.equal(commitLevel(80).level, 'high');
  assert.equal(commitLevel(90).level, 'critical');
  const now = 1_000_000;
  const data = {
    apps: [{ name: 'ComfyUI', pids: [2] }],
    system: { commitPercent: 80, commitBytes: 80 * GIB, commitLimitBytes: 100 * GIB, commitPeakBytes: 95 * GIB,
      memoryTotalBytes: 80 * GIB, bootTime: now - 5 * 86400,
      commitTop: [{ pid: 1, name: 'chrome.exe', privateBytes: 12 * GIB, workingSetBytes: 2 * GIB },
        { pid: 2, name: 'python.exe', privateBytes: 6 * GIB, workingSetBytes: 5 * GIB }] },
  };
  assert.deepEqual(commitTopRows(data).map(r => r.name), ['chrome.exe', 'ComfyUI']);
  const advice = commitAdvice(data, now).lines.join('\n');
  assert.match(advice, /占用最多：chrome\.exe 12 GiB、ComfyUI 6\.0 GiB/);
  assert.match(advice, /chrome\.exe：提交 12 GiB，实际驻留只有 2\.0 GiB/);
  assert.match(advice, /连续运行 5 天/);
  assert.match(advice, /页面文件约 20 GiB/);
  data.system.commitPercent = 30;
  assert.doesNotMatch(commitAdvice(data, now).lines.join('\n'), /占用最多/);
});

test('scene plan lists what will actually close, start or stay', () => {
  const data = {
    apps: [{ id: 'a', name: 'A', running: true }, { id: 'b', name: 'B', running: false },
      { id: 'c', name: 'C', running: true }, { id: 'd', name: 'D', running: false }],
    presets: [{ id: 'p', type: 'package', steps: [{ appId: 'c' }, { appId: 'd' }] }],
  };
  const plan = scenePlan({ steps: [{ appId: 'a', action: 'stop' }, { appId: 'b', action: 'start' },
    { appId: 'd', action: 'keep' }, { appId: 'gone', action: 'stop' }], packageSteps: [{ packageId: 'p', action: 'stop' }] }, data);
  assert.deepEqual(plan.stop.sort(), ['A', 'C']);
  assert.deepEqual(plan.start, ['B']);
  assert.deepEqual(plan.skipped, ['D · 保持不变']);
  assert.deepEqual(plan.missing, ['gone']);
});
