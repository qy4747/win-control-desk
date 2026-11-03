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
  const apps = rows.map(r => {
    const spec = { name: r.name || baseName(r.exe), pid: r.pid, created: r.created, kind: r.kind === 'service' ? 'service' : 'desktop' };
    if (r.card?.state === 'similar') spec.appId = r.card.id;
    if (r.kind === 'service' && r.ports?.length) spec.port = r.ports[0];
    return spec;
  });
  const lines = rows.map(r => '- ' + (r.name || baseName(r.exe)) + '：' + r.exe
    + (r.ports?.length ? '，端口 ' + r.ports.join('、') : '')
    + (r.card?.state === 'similar' ? '，可能对应已有卡片「' + r.card.name + '」（未关联）' : ''));
  const url = 'http://127.0.0.1:' + (ctx.port || 9600);
  return [
    '请帮我把以下正在运行的程序加入总控台卡片。',
    '总控台源码目录：' + (ctx.cwd || '（请确认）'),
    '总控台地址：' + url,
    '',
    '运行中的程序：',
    ...lines,
    '',
    '处理方式（若源码目录有 skills/win-control-desk-apps/SKILL.md，请先按其流程）：',
    '1. 运行 `py -3.12 tools/manage_apps.py --url ' + url + ' discover <名称>`，核对 PID 和创建时间仍有效；变化了就重新发现。',
    '2. 查明真实启动命令、工作目录和关闭方式；不确定的启动或退出参数先问我，不要猜。',
    '3. 按我的需求补全自定义按钮（actions、front）、相关位置（locations）、窗口关联（window）和关闭脚本（stopAction）；批处理流另建 kind=task 卡片。',
    '4. 计划放在 tmp/，先 `apply <计划>` 预演并把变更给我确认，再加 `--write` 写入，最后运行 `verify`。',
    '5. 不要启动、停止或结束任何进程。',
    '',
    '我的定制需求：（在这里补充，例如“加一个打开配置目录的按钮”）',
    '',
    '计划骨架：',
    '```json',
    JSON.stringify({ apps }, null, 2),
    '```',
  ].join('\n');
}
