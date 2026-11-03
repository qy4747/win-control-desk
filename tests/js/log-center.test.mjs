import test from 'node:test';
import assert from 'node:assert/strict';
import { filterLog, logMatches, growthTone, sortedLogs } from '../../static/js/log-model.js';

test('error filter retains original lines; literal search offsets refer to displayed text', () => {
  const raw = '<b>info</b>\nERROR [a.b]\n失败 [A.B]\nException thrown\nnormal';
  const text = filterLog(raw, true);
  assert.equal(text, 'ERROR [a.b]\n失败 [A.B]\nException thrown');
  assert.equal(filterLog(raw, false), raw);
  assert.deepEqual(logMatches(text, '[a.b]').map(([a,b]) => text.slice(a,b)), ['[a.b]', '[A.B]']);
  assert.deepEqual(logMatches('İ hi', 'hi'), [[2, 4]]);
  assert.deepEqual(logMatches(text, ''), []);
});
test('directory footprint includes backups; unknown growth sorts last, thresholds are strict', () => {
  const app = { bytes: 100, backupBytes: 200, errorCount: 1, growthBytesPerHour: null };
  const self = { bytes: 200, backupBytes: 5, errorCount: 4, growthBytesPerHour: 1 };
  const summary = { apps: [app], console: self };
  assert.deepEqual(sortedLogs(summary, 'size'), [app, self]);
  for (const sort of ['growth', 'errors']) assert.deepEqual(sortedLogs(summary, sort), [self, app]);
  const mib = 1024 ** 2;
  assert.deepEqual([50*mib, 50*mib+1, 500*mib, 500*mib+1].map(growthTone), ['', 'warn', 'warn', 'danger']);
});
