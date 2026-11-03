const ERROR = /error|exception|traceback|fatal|错误|失败/i;

export function filterLog(text, errorsOnly) {
  return errorsOnly ? text.split(/\r?\n/).filter(line => ERROR.test(line)).join('\n') : text;
}
export function logMatches(text, query) {
  if (!query) return [];
  // Literal, Unicode-aware offsets into the original text (no lowercased index drift).
  const pattern = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'giu');
  return Array.from(text.matchAll(pattern), m => [m.index, m.index + m[0].length]);
}
export function sortedLogs(summary, sort) {
  const score = row => sort === 'growth' ? row.growthBytesPerHour ?? -1
    : sort === 'errors' ? row.errorCount : row.bytes + row.backupBytes;
  return [...summary.apps, summary.console].sort((a, b) => score(b) - score(a));
}
export function growthTone(value) {
  return value > 500 * 1024 ** 2 ? 'danger' : value > 50 * 1024 ** 2 ? 'warn' : '';
}
export function formatBytes(value) {
  if (value == null) return '—';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  let i = 0;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 1 }) + ' ' + units[i];
}
