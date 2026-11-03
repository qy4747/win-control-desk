export function glanceStatus(app) {
  if (app.health?.blocking || app.alerts?.some(a => !a.ignored) || app.portOccupied || app.portConflict)
    return ['error', '异常'];
  if (app.statusKnown === false) return ['unknown', '状态待确认'];
  if (app.running) return app.kind === 'task' ? ['task', '任务运行中'] : ['running', '运行中'];
  return ['stopped', '已停止'];
}

export function glanceGroups(apps, query) {
  const groups = new Map(), q = query.trim().toLocaleLowerCase();
  // The launchpad displays non-tasks before tasks, retaining saved order in each section.
  for (const app of [...apps.filter(a => a.kind !== 'task'), ...apps.filter(a => a.kind === 'task')]) {
    const category = app.category || (app.kind === 'task' ? '批处理任务' : '未分类');
    if (q && !(app.name + ' ' + category).toLocaleLowerCase().includes(q)) continue;
    if (!groups.has(category)) groups.set(category, []);
    groups.get(category).push(app);
  }
  return groups;
}

// Rows may be short at a category boundary. Preserve the column when possible.
export function gridNeighbor(rows, id, key) {
  const r = rows.findIndex(row => row.includes(id));
  if (r < 0) return rows[0]?.[0];
  const col = rows[r].indexOf(id), flat = rows.flat(), index = flat.indexOf(id);
  if (key === 'ArrowLeft') return flat[Math.max(0, index - 1)];
  if (key === 'ArrowRight') return flat[Math.min(flat.length - 1, index + 1)];
  const next = rows[r + (key === 'ArrowDown' ? 1 : -1)];
  return next ? next[Math.min(col, next.length - 1)] : id;
}
