'use strict';

const GIB = 1024 ** 3;

function size(n) {
  return Number.isFinite(n) ? (n / GIB).toFixed(n >= 10 * GIB ? 0 : 1) + ' GiB' : '未知';
}

export function commitLevel(percent) {
  if (!Number.isFinite(percent)) return { level: 'unknown', label: '提交内存读数不可用' };
  if (percent >= 85) return { level: 'critical', label: '提交内存接近上限' };
  if (percent >= 75) return { level: 'high', label: '提交内存偏高' };
  if (percent >= 60) return { level: 'watch', label: '提交内存需留意' };
  return { level: 'normal', label: '提交内存正常' };
}

// Largest private-commit holders, named by their card when the PID belongs to one.
export function commitTopRows(data, limit = 3) {
  const owners = new Map();
  for (const app of data?.apps || []) for (const pid of app.pids || []) owners.set(pid, app.name);
  return (data?.system?.commitTop || []).filter(p => Number.isFinite(p.privateBytes)).slice(0, limit).map(p => ({
    pid: p.pid, name: owners.get(p.pid) || p.name || 'PID ' + p.pid,
    commitBytes: p.privateBytes, workingSetBytes: p.workingSetBytes,
  }));
}

export function commitAdvice(data, now = Date.now() / 1000) {
  const s = data?.system || {};
  const { level, label } = commitLevel(s.commitPercent);
  const lines = [];
  if (level === 'unknown') return { level, label, lines: ['等待下一次采样。'] };
  lines.push('已提交 ' + size(s.commitBytes) + ' / 上限 ' + size(s.commitLimitBytes) + '（' + s.commitPercent.toFixed(1) + '%）' +
    (Number.isFinite(s.commitPeakBytes) ? '，开机以来峰值 ' + size(s.commitPeakBytes) : '') + '。');
  lines.push('提交内存是程序已申请、Windows 承诺能提供的内存（物理内存加页面文件）。达到上限后新的申请会失败，程序可能崩溃或卡住，即使物理内存还有空余。');
  const uptimeDays = Number.isFinite(s.bootTime) ? Math.floor((now - s.bootTime) / 86400) : null;
  if (level === 'normal') {
    if (uptimeDays >= 7) lines.push('系统已连续运行 ' + uptimeDays + ' 天，目前余量充足。');
    return { level, label, lines, uptimeDays };
  }
  const top = commitTopRows(data, 3);
  if (top.length) lines.push('占用最多：' + top.map(r => r.name + ' ' + size(r.commitBytes)).join('、') + '。');
  for (const r of top) {
    if (r.commitBytes >= GIB && Number.isFinite(r.workingSetBytes) && r.commitBytes >= r.workingSetBytes * 4)
      lines.push(r.name + '：提交 ' + size(r.commitBytes) + '，实际驻留只有 ' + size(r.workingSetBytes) + '，多为已申请但未使用的内存，重启它通常能释放。');
  }
  const steps = ['保存工作后，关闭或重启排在前面的程序；浏览器可先关闭不用的标签页和窗口。',
    '结束不再需要的后台任务、本地模型、虚拟机或容器。'];
  if (uptimeDays >= 3) steps.push('系统已连续运行 ' + uptimeDays + ' 天' +
    (Number.isFinite(s.commitPeakBytes) ? '，峰值曾到 ' + size(s.commitPeakBytes) : '') + '。有空时重启 Windows 可完整回收，睡眠和休眠不会回收。');
  const pagefile = Number.isFinite(s.commitLimitBytes) && Number.isFinite(s.memoryTotalBytes) ? s.commitLimitBytes - s.memoryTotalBytes : null;
  if (pagefile !== null && pagefile < s.memoryTotalBytes * 0.5)
    steps.push('页面文件约 ' + size(Math.max(0, pagefile)) + '，提交上限偏低。如果经常接近上限，可在「系统属性 → 高级 → 性能设置 → 高级 → 虚拟内存」调大，或改为系统管理大小；页面文件所在磁盘需要留出相应空间。');
  steps.forEach((step, i) => lines.push((i + 1) + '. ' + step));
  return { level, label, lines, uptimeDays };
}
