'use strict';

// App totals already include their child processes; listeners repeat a PID per port.
export function resourceRows(data) {
  const rows = new Map(), seen = new Set(), managed = new Set();
  const total = data.system?.memoryTotalBytes;
  for (const app of data.apps || []) {
    if (app.statusKnown === false) { for (const pid of app.pids || []) seen.add(pid); continue; }
    if (!app.running) continue;
    const r = app.resources || {};
    if (![r.cpu, r.memoryBytes, r.gpuMemoryBytes].some(Number.isFinite)) continue;
    for (const pid of app.pids || []) seen.add(pid);
    managed.add(app.id);
    rows.set('app:' + app.id, { name: app.name, cpu: r.cpu,
      mem: Number.isFinite(r.memoryBytes) && total > 0 ? r.memoryBytes / total * 100 : null,
      memoryBytes: r.memoryBytes, gpuMemoryBytes: r.gpuMemoryBytes });
  }
  for (const svc of data.services || []) {
    if (svc.hidden || seen.has(svc.pid) || managed.has(svc.appId)) continue;
    seen.add(svc.pid);
    const key = svc.appId ? 'app:' + svc.appId : 'pid:' + svc.pid;
    const row = rows.get(key) || { name: svc.appName || svc.name || svc.project || '本地进程' };
    for (const [metric, value] of Object.entries({ cpu: svc.cpu, mem: svc.mem,
      memoryBytes: Number.isFinite(svc.mem) && total > 0 ? svc.mem / 100 * total : null,
      gpuMemoryBytes: svc.gpuMemoryBytes })) {
      if (Number.isFinite(value)) row[metric] = (row[metric] || 0) + value;
    }
    rows.set(key, row);
  }
  return [...rows.values()];
}

export function topResources(data, metric, limit = 3) {
  return resourceRows(data).filter(row => Number.isFinite(row[metric]))
    .sort((a, b) => b[metric] - a[metric]).slice(0, limit);
}
