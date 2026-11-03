'use strict';

// Mirrors ops_model.preset_steps: packages expand first, explicit app steps override them.
export function scenePlan(preset, data) {
  const apps = new Map((data?.apps || []).map(a => [a.id, a]));
  const presets = new Map((data?.presets || []).map(p => [p.id, p]));
  const actions = new Map();
  for (const step of preset?.packageSteps || []) {
    for (const member of presets.get(step.packageId)?.steps || []) actions.set(member.appId, step.action);
  }
  for (const step of preset?.steps || []) actions.set(step.appId, step.action);
  const plan = { stop: [], start: [], skipped: [], missing: [] };
  for (const [appId, action] of actions) {
    const app = apps.get(appId);
    if (!app) { plan.missing.push(appId); continue; }
    const running = !!(app.running || app.backgroundOnly);
    if (action === 'stop' && running) plan.stop.push(app.name);
    else if (action === 'start' && !running) plan.start.push(app.name);
    else plan.skipped.push(app.name + (action === 'keep' ? ' · 保持不变' : running ? ' · 已在运行' : ' · 已停止'));
  }
  return plan;
}
