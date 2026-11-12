'use strict';
const SHARED_HOSTS = new Set(['python.exe', 'pythonw.exe', 'node.exe', 'cmd.exe', 'powershell.exe', 'pwsh.exe',
  'windowsterminal.exe', 'wt.exe', 'wsl.exe', 'bash.exe', 'conhost.exe', 'openconsole.exe']);

export function rowKey(row) { return row.pid + '@' + row.created; }

function baseName(path) { return String(path || '').split(/[\\/]/).pop().toLowerCase(); }
function dirName(path) { const s = String(path || ''); const i = Math.max(s.lastIndexOf('\\'), s.lastIndexOf('/')); return i > 0 ? s.slice(0, i) : ''; }

export function discoveryRows(items, query = '', unaddedOnly = true) {
  const q = query.trim().toLowerCase();
  return (items || []).filter(r => !(unaddedOnly && r.card?.state === 'managed')
    && (!q || (r.name + ' ' + r.exe + ' ' + r.pid + ' ' + (r.command || '')).toLowerCase().includes(q)));
}

export function discoveryCounts(items) {
  const counts = { unadded: 0, managed: 0, similar: 0 };
  for (const r of items || []) counts[r.card?.state || 'unadded'] += 1;
  return counts;
}

/* Interpreters need the real entry script, so they become observation cards;
   ordinary programs can be relaunched from their own exe. */
export function quickAddPayload(row) {
  const host = SHARED_HOSTS.has(baseName(row.exe));
  const service = row.kind === 'service';
  return {
    pid: row.pid, created: row.created, name: row.name || baseName(row.exe), kind: service ? 'service' : 'desktop',
    command: host || !row.exe ? '' : '"' + row.exe + '"', shell: 'cmd',
    cwd: host ? null : dirName(row.exe) || null, port: service && row.ports?.length ? row.ports[0] : null,
  };
}

export function aiHandoff(rows, ctx = {}) {
  const url = 'http://127.0.0.1:' + (ctx.port || 9600);
  const lines = rows.map(r => '- ' + (r.name || baseName(r.exe)) + '  PID ' + r.pid + '  创建 ' + r.created + '  ' + r.exe
    + (r.kind === 'service' && r.ports?.length ? '  端口 ' + r.ports.join('、') : '')
    + (r.card?.state === 'similar' ? '  可能对应已有卡片「' + r.card.name + '」（appId ' + r.card.id + '，未关联）' : ''));
  return [
    '请把下面正在运行的程序加入总控台（源码：' + (ctx.cwd || '请确认') + '，地址：' + url + '）。',
    ...lines,
    '',
    '有 skills/win-control-desk-apps/SKILL.md 就按它做；没有就用 `py -3.12 tools/manage_apps.py --url ' + url + ' discover`、`apply <计划>`、`verify`，预演给我确认后再加 `--write`。',
    '只添加我需求里写到的按钮和位置，没写就只建卡片；启动或关闭参数不确定先问我；不要启动、停止或结束任何进程。',
    '',
    '我的需求：',
  ].join('\n');
}
