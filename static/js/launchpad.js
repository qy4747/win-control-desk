'use strict';
import { updateCardExtras, executeWindow } from './ops.js';
/* ============================================================
   launchpad.js — 启动台：应用卡片 / 拖拽排序 / 端口诊断 / 启动诊断
   ============================================================ */
import { $, el, setText, setChildren, icon, iconBtn, escapeHtml,
  post, del, act, toast, openLayer, closeLayer, reconcile,
  state, findApp, fmtUptime, fmtDuration, taskExitStatus,
  localServiceUrl } from './core.js';
import { openConfirm, openAppModal, openLogs, getIconVer } from './overlays.js';
import { configuredPort, actualPorts, hasPortMismatch,
  preferredOpenPort, displayedPorts, portIsOpenable } from './ports.js';

const svcGrid = $('#svcGrid'), taskGrid = $('#taskGrid');
const reorderStatus = $('#reorderStatus');
/* ---------------- 图标取色光晕 ---------------- */
function hueFromString(s) {
  let h = 0;
  for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h % 360;
}
/* 8x8 缩样后按透明度加权取平均色；跨域/解码失败静默回退 */
function glowFromImage(img, cb) {
  const compute = () => {
    try {
      const cv = document.createElement('canvas');
      cv.width = cv.height = 8;
      const cx = cv.getContext('2d', { willReadFrequently: true });
      cx.drawImage(img, 0, 0, 8, 8);
      const d = cx.getImageData(0, 0, 8, 8).data;
      let r = 0, g = 0, b = 0, w = 0;
      for (let i = 0; i < d.length; i += 4) {
        const a = d[i + 3] / 255;
        if (a > 0.2) { r += d[i] * a; g += d[i + 1] * a; b += d[i + 2] * a; w += a; }
      }
      if (!w) return cb(null);
      cb('rgb(' + Math.round(r / w) + ' ' + Math.round(g / w) + ' ' + Math.round(b / w) + ')');
    } catch (e) { cb(null); }
  };
  if (img.complete && img.naturalWidth) compute();
  else img.addEventListener('load', compute, { once: true });
}
function updateCardGlow(card, app) {
  const key = app.icon || app.favicon || ('id:' + app.id);
  if (card._glowKey === key) return;
  card._glowKey = key;
  card.style.setProperty('--icon-hue', hueFromString(app.id));
  card.style.removeProperty('--icon-color');
  if (app.icon || app.favicon) {
    glowFromImage(card._r.iconImg, c => {
      if (card._glowKey === key && c) card.style.setProperty('--icon-color', c);
    });
  }
}

const FAVICON_RETRY_DELAYS = [5000, 15000, 60000];
let iconFetchQueue = Promise.resolve();
function maybeFetchExeIcon(card, app) {
  if (state.data?.platform !== 'win32' || app.kind !== 'desktop' || app.icon) return;
  const signature = JSON.stringify([app.command, app.externalIdentity?.exe, app.instanceMatch?.exe]);
  if (card._exeIconAttempt === signature) return;
  card._exeIconAttempt = signature;
  iconFetchQueue = iconFetchQueue.then(() => post('/api/apps/' + app.id + '/exe-icon', {}))
    .then(result => { if (result?.icon) return window.__poll(); }).catch(() => {});
}
function maybeFetchFavicon(card, app) {
  const port = preferredOpenPort(app);
  if (app.icon || app.glyph || !app.running || !port) {
    if (app.favicon) card._favFetch = null;
    return;
  }
  /* favicon 已就位时只在加载失败后重试（_favFailedAt 记录上次失败的地址），
     正常显示的 favicon 不再重复请求。 */
  if (app.favicon && card._favFailedAt !== app.favicon) {
    card._favFetch = null;
    return;
  }
  const signature = String(app.pid || app.lastPid || port);
  if (!card._favFetch || card._favFetch.signature !== signature) {
    card._favFetch = { signature, attempts: 0, nextAt: 0, inFlight: false };
  }
  const attempt = card._favFetch;
  if (attempt.inFlight || attempt.attempts >= FAVICON_RETRY_DELAYS.length
      || Date.now() < attempt.nextAt) return;
  attempt.inFlight = true;
  attempt.attempts += 1;
  post('/api/apps/' + app.id + '/favicon', {})
    .then(result => {
      if (result && result.ok) window.__poll();
      else attempt.nextAt = Date.now() + FAVICON_RETRY_DELAYS[attempt.attempts - 1];
    })
    .catch(() => {
      attempt.nextAt = Date.now() + FAVICON_RETRY_DELAYS[attempt.attempts - 1];
    })
    .finally(() => { attempt.inFlight = false; });
}

function createAppCard() {
  const card = el('article', 'app-card');
  card.tabIndex = 0;
  card.setAttribute('aria-describedby', 'reorderInstructions');
  card.setAttribute('aria-roledescription', '可排序应用卡片');
  card.addEventListener('pointerdown', cardPointerDown);
  card.addEventListener('keydown', cardSortKeyDown);

  const head = el('div', 'app-head');
  const iconBox = el('div', 'app-icon');
  const iconImg = new Image();
  iconImg.alt = '';
  iconImg.hidden = true;
  iconImg.addEventListener('error', () => {
    iconImg._failedSrc = iconImg.getAttribute('src') || '';
    iconImg.hidden = true;
    iconGlyph.hidden = true;
    iconTxt.hidden = false;
    const app = findApp(card.dataset.key);
    setText(iconTxt, app && app.name ? [...app.name][0].toUpperCase() : '?');
    /* favicon 已保存但图片加载失败（404/损坏）：按重试延迟再次抓取，
       否则 app.favicon 一旦被设置就永远停在字母占位。 */
    if (app && app.favicon && iconImg._failedSrc === app.favicon) {
      card._favFailedAt = app.favicon;
      const attempt = card._favFetch;
      const signature = String(app.pid || app.lastPid || preferredOpenPort(app));
      if (attempt && attempt.signature === signature) {
        const delayIndex = Math.max(0, Math.min(
          attempt.attempts - 1, FAVICON_RETRY_DELAYS.length - 1));
        attempt.nextAt = Date.now() + FAVICON_RETRY_DELAYS[delayIndex];
      } else {
        card._favFetch = {
          signature, attempts: 0,
          nextAt: Date.now() + FAVICON_RETRY_DELAYS[0],
          inFlight: false,
        };
      }
    }
  });
  iconImg.addEventListener('load', () => {
    iconImg._failedSrc = '';
    card._favFailedAt = '';
  });
  const iconGlyph = el('span', 'app-icon-glyph');
  iconGlyph.hidden = true;
  const iconTxt = el('span', 'app-icon-letter');
  iconBox.append(iconImg, iconGlyph, iconTxt);

  const meta = el('div', 'app-meta');
  const name = el('div', 'app-name');
  const status = el('div', 'app-status');
  const dot = el('span', 'status-dot');
  const stText = el('span', 'st-text');
  const stPort = el('button', 'st-port');
  stPort.type = 'button';
  const stUp = el('span', 'st-up');
  status.append(dot, stText, stPort, stUp);
  const taskHistory = el('div', 'task-history');
  taskHistory.hidden = true;
  meta.append(name, status, taskHistory);
  head.append(iconBox, meta);

  const cmd = el('div', 'app-cmd');

  const actions = el('div', 'app-actions');
  const primary = el('button', 'btn app-primary');
  primary.type = 'button';
  const sub = el('div', 'app-sub-actions');
  const bCopy = iconBtn('copy', '复制链接');
  const bLogs = iconBtn('file-text', '日志');
  const bDiag = iconBtn('activity', '启动诊断');
  bDiag.hidden = true;
  const bRestart = iconBtn('refresh-cw', '重启应用');
  bRestart.hidden = true;
  const bEdit = iconBtn('pencil', '编辑');
  const bDel = iconBtn('trash-2', '删除', 'danger');
  sub.append(bCopy, bLogs, bDiag, bRestart, bEdit, bDel);
  actions.append(primary, sub);

  card.append(head, cmd, actions);
  card._r = { iconBox, iconImg, iconGlyph, iconTxt, name, status, dot,
    stText, stPort, stUp, taskHistory, cmd, primary, copy: bCopy, logs: bLogs,
    diag: bDiag, restart: bRestart, edit: bEdit, del: bDel };

  const id = () => card.dataset.key;
  primary.addEventListener('click', () => toggleApp(id(), primary));
  bCopy.addEventListener('click', async () => {
    const a = findApp(id());
    const p = preferredOpenPort(a);
    if (!p) return;
    const url = localServiceUrl(a, p);
    try {
      await navigator.clipboard.writeText(url);
      toast('已复制 ' + url);
    } catch (e) {
      toast('复制失败：' + e.message);
    }
  });
  stPort.addEventListener('click', () => {
    const a = findApp(id());
    const p = preferredOpenPort(a);
    if (a && (a.kind || 'service') === 'service' && a.running && a.statusKnown !== false && portIsOpenable(a)) {
      void executeWindow(a.id, 'focus');
      return;
    }
    if (a && (a.portConflict || a.portOccupied)) {
      openPortDiagnostic(a);
      return;
    }
    /* listening 是新后端字段；旧进程热加载前会缺失，缺失时保持兼容。 */
    if (portIsOpenable(a) && p) {
      window.open(localServiceUrl(a, p), '_blank', 'noopener,noreferrer');
    }
  });
  bLogs.addEventListener('click', () => { const a = findApp(id()); if (a) openLogs(a); });
  bDiag.addEventListener('click', () => { const a = findApp(id()); if (a) openAppDiagnosis(a); });
  bRestart.addEventListener('click', () => {
    const a = findApp(id());
    if (a) confirmRestartApp(a);
  });
  bEdit.addEventListener('click', () => { const a = findApp(id()); if (a) openAppModal(a); });
  bDel.addEventListener('click', () => { const a = findApp(id()); if (a) confirmDeleteApp(a); });
  return card;
}

/* 主按钮：服务 = 启动/停止；批处理 = 运行/中止。 */
function setPrimary(btn, running, kind) {
  const sig = running + '|' + kind;
  if (btn._sig === sig) return;
  btn._sig = sig;
  const label = running ? (kind === 'task' ? '中止' : '停止')
    : (kind === 'task' ? '运行' : '启动');
  setChildren(btn, icon(running ? 'square' : 'play', 13));
  btn.appendChild(document.createTextNode(label));
  btn.classList.toggle('btn-stop', running);
  btn.classList.toggle('btn-accent', !running);
}

function updateAppCard(card, app) {
  const r = card._r;
  /* 图标优先级：上传图片 > glyph（Lucide）> 站点 favicon（自动抓取）> 名称首字 */
  const v = getIconVer(app.id);
  if (app.icon) {
    r.iconImg.classList.remove('fav');
    const src = app.icon + (v ? '?v=' + v : '');
    if (r.iconImg.getAttribute('src') !== src) {
      r.iconImg._failedSrc = '';
      r.iconImg.src = src;
    }
    const failed = r.iconImg._failedSrc === src;
    r.iconImg.hidden = failed;
    r.iconGlyph.hidden = true;
    r.iconTxt.hidden = !failed;
    if (failed) setText(r.iconTxt, app.name ? [...app.name][0].toUpperCase() : '?');
  } else if (app.glyph && window.LUCIDE && window.LUCIDE[app.glyph]) {
    if (r._glyph !== app.glyph) {
      r._glyph = app.glyph;
      setChildren(r.iconGlyph, icon(app.glyph, 22));
    }
    r.iconGlyph.hidden = false;
    r.iconImg.hidden = true;
    r.iconTxt.hidden = true;
  } else if (app.favicon) {
    r.iconImg.classList.add('fav');
    if (r.iconImg.getAttribute('src') !== app.favicon) {
      r.iconImg._failedSrc = '';
      r.iconImg.src = app.favicon;
    }
    const failed = r.iconImg._failedSrc === app.favicon;
    r.iconImg.hidden = failed;
    r.iconGlyph.hidden = true;
    r.iconTxt.hidden = !failed;
    if (failed) setText(r.iconTxt, app.name ? [...app.name][0].toUpperCase() : '?');
  } else {
    r._glyph = null;
    r.iconImg.hidden = true;
    r.iconGlyph.hidden = true;
    r.iconTxt.hidden = false;
    setText(r.iconTxt, app.name ? [...app.name][0].toUpperCase() : '?');
  }
  setText(r.name, app.name || '');
  r.name.title = app.name || '';
  setText(r.cmd, app.command || '');
  r.cmd.hidden = !app.command;
  r.cmd.title = app.command || '';
  /* 状态副行：运行态、端口冲突，以及服务/任务上次退出结果。 */
  const kind = app.kind || 'service';
  const isTask = kind === 'task';
  const interfaceOpen = app.running && !app.backgroundOnly;
  const taskStatus = isTask && app.lastExit ? taskExitStatus(app.lastExit) : '';
  const taskFinished = isTask && !app.running && !!app.lastExit;
  const taskFailed = taskFinished && taskStatus === 'failed';
  const taskSucceeded = taskFinished && taskStatus === 'succeeded';
  const healthIssues = app.health && Array.isArray(app.health.issues)
    ? app.health.issues : [];
  const healthIssue = app.canStart !== false && app.health && app.health.blocking && healthIssues.length
    ? healthIssues[0] : null;
  const portMismatch = hasPortMismatch(app);
  r.dot.classList.toggle('running', !!interfaceOpen);
  r.dot.classList.toggle('success', taskSucceeded);
  r.dot.classList.toggle('danger', taskFailed);
  let stTxt = app.backgroundOnly ? '后台驻留' : app.running ? '运行中' : app.canStart === false ? '观察卡片 · 未配置启动命令' : (app.port ? '已停止' : '未运行');
  let stFail = false;
  let taskHistoryText = '';
  if (app.portConflict) {
    stTxt = '配置冲突';
    stFail = true;
  } else if (app.portOccupied) {
    stTxt = '端口被占用';
    stFail = true;
  } else if (portMismatch) {
    stTxt = '端口配置不一致';
    stFail = true;
  } else if (app.running && app.port && app.listening === false) {
    stTxt = '等待端口';
  } else if (!app.running && healthIssue) {
    stTxt = healthIssue.title || '配置不可用';
    stFail = true;
  } else if (taskFinished && (taskStatus === 'canceled' || taskStatus === 'stopped')) {
    stTxt = taskStatus === 'canceled' ? '已取消' : '已中止';
    const endedAt = Number(app.lastExit.at);
    if (Number.isFinite(endedAt) && endedAt > 0) {
      const ago = fmtUptime(Date.now() / 1000 - endedAt);
      taskHistoryText = ago === '刚刚' ? ago : ago + '前';
    }
  } else if (!app.running && app.lastExit) {
    const ok = isTask ? taskStatus === 'succeeded' : app.lastExit.code === 0;
    stFail = !ok;
    const ago = fmtUptime(Date.now() / 1000 - app.lastExit.at);
    const agoText = ago === '刚刚' ? ago : ago + '前';
    const what = app.port
      ? (ok ? '服务已退出'
        : (app.lastExit.code < 0 ? '服务被终止' : '启动失败 exit ' + app.lastExit.code))
      : (ok ? '运行成功'
        : (app.lastExit.code < 0 ? '运行被终止' : '运行失败 exit ' + app.lastExit.code));
    if (isTask) {
      stTxt = what;
      const duration = fmtDuration(app.lastExit.durationSec);
      taskHistoryText = agoText + (duration ? ' · 用时 ' + duration : '');
    } else {
      stTxt = what + ' · ' + agoText;
    }
  }
  if (app.statusKnown === false) { stTxt = '状态未知'; stFail = false; r.dot.classList.remove('running', 'success', 'danger'); }
  setText(r.stText, stTxt);
  r.stText.classList.toggle('fail', stFail);
  setText(r.taskHistory, taskHistoryText);
  r.taskHistory.hidden = !taskHistoryText;
  r.taskHistory.title = taskHistoryText;
  r.status.title = taskHistoryText ? stTxt + ' · ' + taskHistoryText : stTxt;
  card.setAttribute('aria-label', (app.name || '未命名应用') + '，' + stTxt +
    '。按空格开始排序');
  /* 运行中展示并打开实际监听端口；停止时才展示配置端口。 */
  const effPorts = displayedPorts(app);
  const effPort = preferredOpenPort(app);
  r.copy.hidden = !effPort;
  if (effPort) {
    r.stPort.hidden = kind === 'service' || !configuredPort(app);
    setText(r.stPort, portMismatch
      ? ':' + effPort + (effPorts.length > 1 ? ' +' + (effPorts.length - 1) : '') +
        ' ≠ :' + configuredPort(app)
      : ':' + effPort + (effPorts.length > 1 ? ' +' + (effPorts.length - 1) : ''));
    const openable = portIsOpenable(app);
    const diagnostic = !!app.portConflict || !!app.portOccupied;
    r.stPort.classList.toggle('clickable', openable && !diagnostic);
    r.stPort.classList.toggle('diagnostic', diagnostic);
    if (app.portConflict) {
      r.stPort.title = '与“' + (app.portConflictApps || []).join('、') +
        '”重复，请编辑端口';
    } else if (app.portOccupied) {
      r.stPort.title = '端口被 PID ' + (app.portOccupiedPid || '?') + ' 占用';
    } else if (portMismatch) {
      r.stPort.title = '配置端口 :' + configuredPort(app) +
        ' 未监听；实际监听：' + effPorts.map(port => ':' + port).join('、');
    } else if (openable) {
      r.stPort.title = '打开 ' + localServiceUrl(app, effPort) +
        (effPorts.length > 1 ? '（全部: ' + effPorts.join(', ') + '）' : '');
    } else {
      r.stPort.title = '端口 ' + effPort;
    }
    r.stPort.setAttribute('aria-label', diagnostic
      ? '诊断 ' + (app.name || '应用') + ' 的端口 ' + effPort
      : openable
        ? '打开 ' + (app.name || '应用') + '，' +
          (portMismatch ? '实际端口 ' : '端口 ') + effPort
        : (app.name || '应用') + ' 的端口 ' + effPort);
  } else {
    r.stPort.hidden = true;
    r.stPort.removeAttribute('aria-label');
  }
  if (app.running) {
    r.stUp.hidden = false;
    setText(r.stUp, isTask ? fmtDuration(app.uptimeSec) : fmtUptime(app.uptimeSec));
  } else {
    r.stUp.hidden = true;
    setText(r.stUp, '');
  }
  setPrimary(r.primary, !!interfaceOpen, kind);
  const appName = app.name || (isTask ? '任务' : '应用');
  const primaryVerb = interfaceOpen ? (isTask ? '中止' : '停止')
    : (isTask ? '运行' : '启动');
  r.primary.setAttribute('aria-label', primaryVerb + ' ' + appName);
  r.copy.setAttribute('aria-label', '复制 ' + appName + ' 的链接');
  r.logs.setAttribute('aria-label', (taskFailed ? '查看失败日志：' : '查看日志：') + appName);
  r.diag.setAttribute('aria-label',
    (isTask ? '配置与运行诊断：' : '配置与启动诊断：') + appName);
  r.restart.setAttribute('aria-label', '重启 ' + appName);
  r.edit.setAttribute('aria-label', '编辑 ' + appName);
  r.del.setAttribute('aria-label', '删除 ' + appName);
  card.setAttribute('aria-label', appName + '，' + stTxt);
  r.restart.hidden = !app.running || kind === 'task';
  r.restart.disabled = app.canStart === false || !!app.health?.blocking;
  const blocked = !interfaceOpen &&
    (!!app.portConflict || !!app.portOccupied || !!healthIssue);
  r.primary.disabled = r.primary.dataset.busy === 'true' || blocked || (!interfaceOpen && app.canStart === false) || app.statusKnown === false;
  r.primary.title = app.portConflict
    ? '端口配置重复，请先编辑其中一项'
    : app.portOccupied ? '端口已被其他进程占用；可打开端口诊断或修改当前卡片端口'
      : healthIssue ? healthIssue.detail || healthIssue.title : '';
  const launchFailed = !app.running && !!app.lastExit
    && (isTask ? taskStatus === 'failed' : app.lastExit.code !== 0);
  card.classList.toggle('running', !!interfaceOpen);
  card.classList.toggle('has-error', !!app.portConflict || !!app.portOccupied
    || portMismatch || launchFailed || !!healthIssue);
  r.diag.hidden = !launchFailed && !healthIssue;
  updateCardGlow(card, app);
  r.logs.classList.toggle('attention', taskFailed);
  r.logs.title = taskFailed ? '查看失败日志' : '日志';
  maybeFetchExeIcon(card, app);
  maybeFetchFavicon(card, app);
  updateCardExtras(card, app);
}

async function toggleApp(id, button, windowsStopConfirmed = false, requestedAction = null) {
  const app = findApp(id);
  if (!app) return;
  if (requestedAction === 'stop' && !app.running) return;
  if (requestedAction === 'start' && app.running && !app.backgroundOnly) return;
  const isTask = (app.kind || 'service') === 'task';
  if (button && button.dataset.busy === 'true') return;
  if (!app.running && app.portConflict) {
    toast('端口配置重复，请先编辑其中一项');
    return;
  }
  if (!app.running && app.portOccupied) {
    toast('端口已被 PID ' + (app.portOccupiedPid || '?') + ' 占用');
    return;
  }
  const starting = requestedAction ? requestedAction === 'start' : !app.running || app.backgroundOnly;
  if (!starting && state.data && state.data.platform === 'win32' &&
      !windowsStopConfirmed) {
    openConfirm({
      title: isTask ? '中止 Windows 任务' : '停止 Windows 服务',
      bodyHtml: '总控台会执行已配置的退出动作，或尝试正常关闭已验证的应用。' +
        '<div class="confirm-detail">配置的进程关闭脚本会直接结束已核实的实例，请先保存工作；失败会保留管理状态。</div>',
      okText: isTask ? '确认中止' : '确认停止',
      onOk: () => toggleApp(id, button, true, 'stop'),
    });
    return;
  }
  if (button) {
    button.dataset.busy = 'true';
    button.disabled = true;
    const card = button.closest('.app-card');
    if (card) updateCardExtras(card, app);
  }
  const targetName = app.name || (isTask ? '任务' : '应用');
  toast(starting
    ? (isTask ? '正在运行 ' : '正在启动 ') + targetName + '…'
    : (isTask ? '正在中止 ' : '正在停止 ') + targetName + '…');
  try {
    const result = await act(post('/api/apps/' + id + '/' + (starting ? 'start' : 'stop')));
    if (result && result.ok !== false) {
      if (starting) {
        toast(isTask
          ? targetName + '已开始运行'
          : '启动命令已执行，正在等待' + (app.port ? ' :' + app.port : '服务'));
        await window.__poll();
        setTimeout(window.__poll, 700);
        setTimeout(window.__poll, 1800);
      } else {
        await window.__poll();
        toast((isTask ? '已中止 ' : '已停止 ') + targetName);
      }
    } else {
      await window.__poll();
    }
  } finally {
    if (button) {
      delete button.dataset.busy;
      const latest = findApp(id);
      button.disabled = !!(latest && (!latest.running || latest.backgroundOnly) &&
        (latest.portConflict || latest.portOccupied ||
          latest.canStart === false || (latest.health && latest.health.blocking))) || latest?.statusKnown === false;
      const card = button.closest('.app-card');
      if (card && latest) updateCardExtras(card, latest);
    }
  }
}
export { toggleApp };

function confirmRestartApp(app) {
  openConfirm({
    title: '重启应用',
    bodyHtml: '确定要重启 <b>' + escapeHtml(app.name || '') + '</b> 吗？' +
      '<div class="confirm-detail">总控台会等待旧进程完全退出，然后使用当前配置重新启动。</div>',
    okText: '重新启动',
    onOk: async () => {
      const r = await act(post('/api/apps/' + app.id + '/restart'));
      if (r && r.ok !== false) toast('已重启 ' + (app.name || '应用'));
      window.__poll();
    },
  });
}

function confirmDeleteApp(app) {
  openConfirm({
    title: '删除应用',
    bodyHtml: '确定要删除 <b>' + escapeHtml(app.name || '') + '</b> 吗？' +
      '<div class="confirm-detail">将先停止该应用，并删除其图标与日志。</div>',
    okText: '删除',
    onOk: async () => {
      await act(del('/api/apps/' + app.id));
      window.__poll();
    },
  });
}

/* ---------------- 端口诊断模态 ---------------- */
const portDiagMask = $('#portDiagMask'), portDiagTitle = $('#portDiagTitle');
const diagDot = $('#diagDot'), diagSummary = $('#diagSummary'), diagPort = $('#diagPort');
const diagPidRow = $('#diagPidRow'), diagPid = $('#diagPid');
const diagNameRow = $('#diagNameRow'), diagName = $('#diagName');
const diagAppRow = $('#diagAppRow'), diagApp = $('#diagApp');
const diagUptimeRow = $('#diagUptimeRow'), diagUptime = $('#diagUptime');
const diagCwdRow = $('#diagCwdRow'), diagCwd = $('#diagCwd');
const diagCmdRow = $('#diagCmdRow'), diagCmd = $('#diagCmd');
const diagNote = $('#diagNote'), diagCopy = $('#diagCopy');
const diagOpen = $('#diagOpen'), diagEdit = $('#diagEdit');
const diagAttach = $('#diagAttach');
const diagKill = $('#diagKill'), diagClose = $('#diagClose');

let diagCurrentApp = null;

function setDiagRow(row, node, value) {
  const present = value !== null && value !== undefined && value !== '';
  row.hidden = !present;
  if (present) setText(node, String(value));
}

function openPortDiagnostic(app) {
  diagCurrentApp = app;
  const owner = app.portOwner || null;
  const conflict = !!app.portConflict;
  const occupied = !!app.portOccupied;
  portDiagTitle.textContent = '端口 ' + (app.port || '--') + ' 诊断';
  setText(diagPort, app.port ? ':' + app.port : '--');
  diagDot.classList.toggle('danger', conflict || occupied);
  setText(diagSummary, conflict ? '启动台配置重复'
    : occupied ? '端口被其他进程占用' : '端口状态正常');

  setDiagRow(diagPidRow, diagPid, owner && owner.pid);
  setDiagRow(diagNameRow, diagName, owner && owner.name);
  setDiagRow(diagAppRow, diagApp, owner && owner.appName);
  setDiagRow(diagUptimeRow, diagUptime,
    owner && owner.uptimeSec != null ? fmtUptime(owner.uptimeSec) : null);
  setDiagRow(diagCwdRow, diagCwd, owner && owner.cwd);
  setDiagRow(diagCmdRow, diagCmd, owner && owner.cmd);

  if (conflict) {
    diagNote.textContent = '同一端口还被“' +
      (app.portConflictApps || []).join('、') +
      '”配置。端口同一时间只能由一个服务监听，请修改当前卡片或另一张卡片。';
  } else if (owner && owner.pid === (state.data && state.data.consolePid)) {
    diagNote.textContent = '该端口属于当前总控台。你可以修改当前卡片端口，不能在这里结束总控台。';
  } else if (owner && owner.currentUser) {
    const ownerLabel = owner.project || owner.appName || owner.name || ('PID ' + owner.pid);
    diagNote.textContent = owner.appId
      ? '端口正在由另一个受管应用“' + ownerLabel +
        '”使用。两张卡片可以保存相同端口；若要现在启动当前项目，请等待它停止、' +
        '修改当前项目端口，或确认后停止占用应用。'
      : '当前监听者“' + ownerLabel + '”并不是由这张卡片启动的。' +
        '它仍会作为独立服务显示，两张卡片也可以保存相同端口。如果它正是本项目的服务，' +
        '可以认领为本卡片；若要现在启动当前项目，' +
        '请等待它停止、修改当前项目端口，或确认后结束该进程。';
  } else if (owner) {
    diagNote.textContent = '该进程不属于当前用户。你可以打开它或修改当前卡片端口，总控台不会结束它。';
  } else {
    diagNote.textContent = '暂时无法读取占用者详情，可稍后刷新重试。';
  }
  diagOpen.hidden = !(occupied && owner && app.port);
  diagAttach.hidden = !(occupied && owner && owner.currentUser && !owner.appId
    && owner.pid !== (state.data && state.data.consolePid));
  diagEdit.hidden = !(conflict || occupied);
  diagKill.hidden = !(occupied && owner && owner.currentUser
    && owner.pid !== (state.data && state.data.consolePid));
  diagKill.textContent = owner && owner.appId ? '停止占用应用' : '结束占用进程';
  openLayer(portDiagMask, diagClose);
}

function closePortDiagnostic() {
  closeLayer(portDiagMask);
  diagCurrentApp = null;
}
export { closePortDiagnostic };

diagClose.addEventListener('click', closePortDiagnostic);
portDiagMask.addEventListener('mousedown', e => {
  if (e.target === portDiagMask) closePortDiagnostic();
});
diagOpen.addEventListener('click', () => {
  const app = diagCurrentApp;
  if (!app || !app.port) return;
  window.open(localServiceUrl(app.portOwner, app.port), '_blank', 'noopener,noreferrer');
});
diagEdit.addEventListener('click', () => {
  const app = diagCurrentApp;
  if (!app) return;
  closePortDiagnostic();
  openAppModal(app);
});
diagAttach.addEventListener('click', () => {
  const app = diagCurrentApp;
  const owner = app && app.portOwner;
  if (!app || !owner) return;
  closePortDiagnostic();
  openConfirm({
    title: '认领为本卡片',
    bodyHtml: '把 PID ' + escapeHtml(owner.pid) +
      '（' + escapeHtml(owner.name || '') + '）认领为「' + escapeHtml(app.name) +
      '」的受管进程？<div class="confirm-detail">认领后卡片显示运行中，可正常停止/重启；' +
      '若卡片目录与进程实际目录不一致，会自动同步为实际目录。</div>',
    okText: '认领',
    onOk: async () => {
      const r = await act(post('/api/apps/' + app.id + '/attach', { pid: owner.pid }));
      if (r && r.ok) {
        toast(r.cwdUpdated ? '已认领，卡片目录已同步为进程实际目录' : '已认领为本卡片');
      }
      window.__poll();
    },
  });
});
diagCopy.addEventListener('click', async () => {
  const app = diagCurrentApp;
  if (!app) return;
  const owner = app.portOwner || {};
  const lines = [
    '端口: ' + (app.port || '--'),
    owner.pid ? 'PID: ' + owner.pid : '',
    owner.name ? '程序: ' + owner.name : '',
    owner.cwd ? '目录: ' + owner.cwd : '',
    owner.cmd ? '命令: ' + owner.cmd : '',
    app.portConflict ? '配置冲突: ' + (app.portConflictApps || []).join('、') : '',
  ].filter(Boolean).join('\n');
  try {
    await navigator.clipboard.writeText(lines);
    toast('已复制端口诊断信息');
  } catch (e) {
    toast('复制失败：' + e.message);
  }
});
diagKill.addEventListener('click', () => {
  const app = diagCurrentApp;
  const owner = app && app.portOwner;
  if (!owner) return;
  closePortDiagnostic();
  openConfirm({
    title: owner.appId ? '停止占用应用' : '结束占用进程',
    bodyHtml: '确定要释放端口 <b>:' + escapeHtml(app.port) + '</b> 吗？' +
      '<div class="confirm-detail mono">PID ' + escapeHtml(owner.pid) +
      ' · ' + escapeHtml(owner.name || '') + '</div>',
    okText: owner.appId ? '停止应用' : '结束进程',
    onOk: async () => {
      await act(post('/api/kill', { pid: owner.pid, created: owner.created, appId: owner.appId || null, force: false }));
      window.__poll();
    },
  });
});

/* ---------------- 启动诊断模态 ---------------- */
const appDiagMask = $('#appDiagMask'), appDiagList = $('#appDiagList');
const appDiagTitle = $('#appDiagTitle');
const appDiagSummary = $('#appDiagSummary'), appDiagLogs = $('#appDiagLogs');
const appDiagClose = $('#appDiagClose');
let appDiagApp = null;
let appDiagRequestSeq = 0;

async function openAppDiagnosis(app) {
  const requestSeq = ++appDiagRequestSeq;
  appDiagApp = app;
  const isTask = (app.kind || 'service') === 'task';
  setText(appDiagTitle, (isTask ? '配置与运行诊断 · ' : '配置与启动诊断 · ') +
    (app.name || '应用'));
  appDiagList.replaceChildren();
  appDiagList.setAttribute('aria-busy', 'true');
  setText(appDiagSummary, '正在分析日志与配置…');
  openLayer(appDiagMask, appDiagClose);
  let r = null;
  try {
    r = await post('/api/apps/' + app.id + '/diagnose', {});
  } catch (e) {
    if (requestSeq === appDiagRequestSeq && appDiagApp && appDiagApp.id === app.id) {
      toast('诊断请求失败：' + e.message);
    }
  }
  if (requestSeq !== appDiagRequestSeq || !appDiagApp || appDiagApp.id !== app.id) return;
  appDiagList.setAttribute('aria-busy', 'false');
  if (!r || r.ok === false) {
    setText(appDiagSummary, (r && r.error) || '诊断失败，请打开日志人工排查');
    return;
  }
  appDiagList.replaceChildren();
  for (const issue of r.issues || []) {
    const box = el('div', 'appdiag-issue');
    const h = el('h4');
    h.textContent = issue.title;
    const d = el('p', 'appdiag-detail');
    d.textContent = issue.detail;
    const f = el('p', 'appdiag-fix');
    f.textContent = '修复建议：' + issue.fix;
    box.append(h, d, f);
    if (issue.action) {
      const repair = el('button', 'btn appdiag-repair');
      repair.type = 'button';
      repair.textContent = issue.action === 'pick-script' ? '重新选择脚本'
        : issue.action === 'pick-cwd' ? '重新选择工作区' : '编辑执行命令';
      repair.addEventListener('click', () => {
        const target = appDiagApp;
        closeAppDiagnosis();
        if (target) openAppModal(target, null, issue.action);
      });
      box.appendChild(repair);
    }
    appDiagList.appendChild(box);
  }
  setText(appDiagSummary, r.summary || '');
}
function closeAppDiagnosis() {
  appDiagRequestSeq += 1;
  appDiagList.setAttribute('aria-busy', 'false');
  closeLayer(appDiagMask);
  appDiagApp = null;
}
export { closeAppDiagnosis };

appDiagClose.addEventListener('click', closeAppDiagnosis);
appDiagMask.addEventListener('mousedown', e => {
  if (e.target === appDiagMask) closeAppDiagnosis();
});
appDiagLogs.addEventListener('click', () => {
  const a = appDiagApp;
  closeAppDiagnosis();
  if (a) openLogs(a);
});

/* ---------------- 卡片拖拽排序（pointer 实现：滑块式跟手 + 虚线占位） ---------------- */
let drag = null;  // { card, ph, grid, dx, dy, originIndex }
let keyboardSort = null;  // { card, grid, originalIds }
let pendingOrder = null;
let suppressDragClick = false;
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// A dropped card is detached from the grid: the trailing click can hit another
// card or its buttons, so consume it before any target's click handler runs.
function blockDragClick(e) {
  if (!suppressDragClick || e.detail === 0) return;
  suppressDragClick = false;
  e.preventDefault();
  e.stopImmediatePropagation();
}
document.addEventListener('click', blockDragClick, true);
document.addEventListener('pointerdown', () => { suppressDragClick = false; }, true);

function gridAppCards(grid) {
  return [...grid.querySelectorAll('.app-card[data-key]')];
}

function persistGridOrder(ids) {
  pendingOrder = ids;
  return post('/api/apps/reorder', { ids })
    .then(() => window.__poll())
    .catch(e => { if (pendingOrder === ids) pendingOrder = null; toast('排序保存失败，请重试'); });
}

function preservePendingOrder(apps) {
  if (!pendingOrder) return apps;
  const order = new Map(pendingOrder.map((id, i) => [id, i]));
  const received = apps.filter(app => order.has(app.id)).map(app => app.id);
  const expected = pendingOrder.filter(id => apps.some(app => app.id === id));
  if (received.every((id, i) => id === expected[i])) { pendingOrder = null; return apps; }
  return [...apps].sort((a, b) => (order.get(a.id) ?? order.size) - (order.get(b.id) ?? order.size));
}

function announceReorder(message) {
  if (!reorderStatus) return;
  reorderStatus.textContent = '';
  requestAnimationFrame(() => { reorderStatus.textContent = message; });
}

/* FLIP 让位动画：重排前记录视觉位置，重排后从旧位置滑到新位置。 */
function stopFlip(card) {
  cancelAnimationFrame(card._flipFrame);
  clearTimeout(card._flipT);
  card.style.transition = 'none';
  card.style.transform = 'none';
}

function flip(grid, mutate) {
  if (reduceMotion) { mutate(); return; }
  const cards = [...grid.querySelectorAll('.app-card')];
  const first = new Map(cards.map(c => [c, c.getBoundingClientRect()]));
  for (const c of cards) stopFlip(c);
  mutate();
  const moved = [];
  for (const c of cards) {
    if (!c.isConnected) continue;
    const f = first.get(c), l = c.getBoundingClientRect();
    const dx = f.left - l.left, dy = f.top - l.top;
    if (dx || dy) {
      c.style.transform = 'translate(' + dx + 'px,' + dy + 'px)';
      moved.push(c);
    } else {
      c.style.transition = '';
      c.style.transform = '';
    }
  }
  for (const c of moved) {
    c._flipFrame = requestAnimationFrame(() => {
      c.style.transition = 'var(--reorder-transition)';
      c.style.transform = '';
      const duration = parseFloat(getComputedStyle(c).getPropertyValue('--reorder-duration-ms')) || 0;
      c._flipT = setTimeout(() => { c.style.transition = ''; c.style.transform = ''; }, duration + 20);
    });
  }
}

function cardPointerDown(e) {
  if (e.button !== 0 || drag || keyboardSort) return;
  if (e.target.closest('button, [role="button"], a, summary, input, select, textarea, label, [contenteditable]')) return;
  const card = e.currentTarget;
  const canDrag = !e.target.closest('details') && !card._ops?.flipping
    && (e.pointerType !== 'touch' || !!e.target.closest('.ops-drag-handle'));
  const sx = e.clientX, sy = e.clientY;
  let moved = false;
  const clearListeners = () => {
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    window.removeEventListener('pointercancel', onCancel);
  };
  const onMove = ev => {
    if (ev.pointerId !== e.pointerId) return;
    if (Math.abs(ev.clientX - sx) + Math.abs(ev.clientY - sy) >= 6) moved = true;
    if (!moved || !canDrag) return;
    if (!drag) {
      beginDrag(card, ev);
    }
    moveDrag(ev);
  };
  const onUp = ev => {
    if (ev.pointerId !== e.pointerId) return;
    clearListeners();
    suppressDragClick = moved;
    if (drag) endDrag();
  };
  const onCancel = ev => {
    if (ev.pointerId !== e.pointerId) return;
    clearListeners();
    suppressDragClick = moved;
    if (drag) cancelPointerDrag();
  };
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
  window.addEventListener('pointercancel', onCancel);
}

function beginDrag(card, e) {
  const menu = card.querySelector('.ops-more'); if (menu) menu.open = false;
  const grid = card.parentNode;
  const rect = card.getBoundingClientRect();
  stopFlip(card);                    // 接管位移，旧动画不能再清除拖拽坐标
  card.classList.remove('anim-in');
  const originIndex = gridAppCards(grid).indexOf(card);
  const ph = el('div', 'drop-placeholder');
  ph.style.height = rect.height + 'px';
  grid.insertBefore(ph, card);
  document.body.appendChild(card);   // 卡片脱离 grid，fixed 跟随指针
  const s = card.style;
  s.width = rect.width + 'px';
  s.height = rect.height + 'px';
  s.position = 'fixed';
  s.left = '0';
  s.top = '0';
  s.margin = '0';
  s.zIndex = '200';
  s.pointerEvents = 'none';
  card.classList.add('lifted');
  document.body.classList.add('dragging-on');
  drag = {
    card, ph, grid, originIndex,
    dx: e.clientX - rect.left,
    dy: e.clientY - rect.top,
  };
  moveDrag(e);
}

function moveDrag(e) {
  const d = drag;
  d.card.style.transform =
    'translate(' + (e.clientX - d.dx) + 'px,' + (e.clientY - d.dy) + 'px)';
  // 占位框不参与动画；用它将指针转换成同网格的布局坐标（含滚动偏移）。
  // 不命中正在让位的视觉表面，否则跨行时会反复选中不同卡片。
  const origin = d.ph.getBoundingClientRect();
  const x = e.clientX - origin.left + d.ph.offsetLeft;
  const y = e.clientY - origin.top + d.ph.offsetTop;
  const over = [...d.grid.children].find(c => c.offsetWidth && c.offsetHeight
    && x >= c.offsetLeft && x < c.offsetLeft + c.offsetWidth
    && y >= c.offsetTop && y < c.offsetTop + c.offsetHeight);
  if (!over || over === d.ph) return;
  if (over.matches('.app-card[data-key]')) {
    const before = over.offsetTop < d.ph.offsetTop
      || (over.offsetTop === d.ph.offsetTop && over.offsetLeft < d.ph.offsetLeft);
    const ref = before ? over : over.nextSibling;
    if (ref !== d.ph && d.ph.nextSibling !== ref) {
      flip(d.grid, () => d.grid.insertBefore(d.ph, ref));
    }
  } else if (over.classList.contains('add-card')) {
    /* 添加卡上 → 网格末尾。添加卡被 prepend 到网格首位，
       insertBefore(d.ph, over) 会把卡片插到首位，与“末尾”意图相反。 */
    if (d.ph !== d.grid.lastChild) {
      flip(d.grid, () => d.grid.appendChild(d.ph));
    }
  }
}

function resetPointerDragCard(d) {
  const s = d.card.style;
  s.position = s.left = s.top = s.width = s.height = s.margin =
    s.zIndex = s.transform = s.transition = s.pointerEvents = '';
  d.card.classList.remove('lifted');
  document.body.classList.remove('dragging-on');
}

function cancelPointerDrag() {
  const d = drag;
  drag = null;
  const remaining = gridAppCards(d.grid);
  const anchor = remaining[d.originIndex] || null;
  if (anchor) d.grid.insertBefore(d.card, anchor);
  else d.grid.appendChild(d.card);
  d.ph.remove();
  resetPointerDragCard(d);
  d.card.focus({ preventScroll: true });
  announceReorder('已取消排序，顺序未保存');
}

/* drop 瞬间的最终顺序：卡片脱离 grid 时占位框位置即目标位置。
   必须在 180ms 滑入动画开始前快照——动画窗口内轮询可能按服务端旧顺序
   重排 DOM，届时重读 DOM 会把被撤销的顺序 POST 回去，排序静默丢失。 */
function dragDropOrder(d) {
  const ids = gridAppCards(d.grid).map(card => card.dataset.key);
  const children = [...d.grid.children];
  const before = children.slice(0, children.indexOf(d.ph))
    .filter(child => child.matches('.app-card[data-key]')).length;
  ids.splice(before, 0, d.card.dataset.key);
  return ids;
}

function endDrag() {
  const d = drag;
  const orderSnapshot = dragDropOrder(d);
  const finish = () => {
    d.grid.insertBefore(d.card, d.ph);
    d.ph.remove();
    resetPointerDragCard(d);
    persistGridOrder(orderSnapshot);
    drag = null;
  };
  if (reduceMotion) { finish(); return; }
  const t = d.ph.getBoundingClientRect();   // 滑入占位框
  d.card.style.transition = 'var(--drop-transition)';
  d.card.style.transform = 'translate(' + t.left + 'px,' + t.top + 'px)';
  setTimeout(finish, parseFloat(getComputedStyle(d.card).getPropertyValue('--drop-duration-ms')) || 0);
}

function cardSortKeyDown(e) {
  if (e.target !== e.currentTarget) return;
  const card = e.currentTarget;
  const isSpace = e.key === ' ' || e.key === 'Spacebar';
  if (!keyboardSort) {
    if (!isSpace) return;
    e.preventDefault();
    const grid = card.parentNode;
    const cards = gridAppCards(grid);
    keyboardSort = {
      card,
      grid,
      originalIds: cards.map(item => item.dataset.key),
    };
    card.classList.add('keyboard-sorting');
    const position = cards.indexOf(card) + 1;
    announceReorder('已抓取 ' + (findApp(card.dataset.key)?.name || '应用') +
      '，当前位置 ' + position + '，共 ' + cards.length + ' 项');
    return;
  }
  if (keyboardSort.card !== card) return;
  if (isSpace || e.key === 'Enter') {
    e.preventDefault();
    finishKeyboardSort(true);
    return;
  }
  if (e.key === 'Escape') {
    e.preventDefault();
    finishKeyboardSort(false);
    return;
  }
  const direction = (e.key === 'ArrowLeft' || e.key === 'ArrowUp') ? -1
    : (e.key === 'ArrowRight' || e.key === 'ArrowDown') ? 1 : 0;
  if (!direction) return;
  e.preventDefault();
  moveKeyboardSort(direction);
}

function moveKeyboardSort(direction) {
  const { card, grid } = keyboardSort;
  const cards = gridAppCards(grid).filter(c => !c.hidden && !c.classList.contains('ops-filtered'));
  const current = cards.indexOf(card);
  const targetIndex = Math.max(0, Math.min(cards.length - 1, current + direction));
  if (targetIndex === current) {
    announceReorder(direction < 0 ? '已经是第一项' : '已经是最后一项');
    return;
  }
  const target = cards[targetIndex];
  flip(grid, () => {
    if (direction < 0) grid.insertBefore(card, target);
    else grid.insertBefore(card, target.nextSibling);
  });
  card.focus({ preventScroll: true });
  announceReorder((findApp(card.dataset.key)?.name || '应用') +
    ' 已移动到第 ' + (targetIndex + 1) + ' 项，共 ' + cards.length + ' 项');
}

function finishKeyboardSort(commit) {
  const session = keyboardSort;
  keyboardSort = null;
  if (!commit) {
    const byId = new Map(gridAppCards(session.grid)
      .map(card => [card.dataset.key, card]));
    for (const id of session.originalIds) {
      const card = byId.get(id);
      if (card) session.grid.appendChild(card);
    }
  }
  session.card.classList.remove('keyboard-sorting');
  session.card.focus({ preventScroll: true });
  if (commit) {
    persistGridOrder(gridAppCards(session.grid).map(card => card.dataset.key));
    announceReorder('排序已保存');
  } else {
    announceReorder('已取消排序，顺序未保存');
  }
}

export function renderLaunchpad(apps, firstRender) {
  if (drag || keyboardSort) return;  // 排序中轮询不打乱 DOM
  apps = preservePendingOrder(apps);
  const svcs = apps.filter(a => (a.kind || 'service') !== 'task');
  const tasks = apps.filter(a => a.kind === 'task');
  const addSvc = $('#addSvcCard');
  const addTask = $('#addTaskCard');
  addSvc.remove();
  addTask.remove();
  reconcile(svcGrid, svcs, a => a.id, createAppCard, updateAppCard, firstRender);
  svcGrid.prepend(addSvc);                  // 新增入口始终优先可见
  reconcile(taskGrid, tasks, a => a.id, createAppCard, updateAppCard, firstRender);
  taskGrid.prepend(addTask);                // 批处理新增入口始终优先可见
  latestSvcs = svcs;
  latestTasks = tasks;
  syncSvcFilterUI();
  syncTaskFilterUI();
  setText($('#svcSecCount'), svcs.length ? String(svcs.length) : '');
  setText($('#taskSecCount'), tasks.length ? String(tasks.length) : '');
}

function syncSvcFilterUI() {
  renderFilterChips($('#svcFilter'), SVC_FILTERS, latestSvcs, svcFilter, matchSvcFilter,
    f => { svcFilter = f; syncSvcFilterUI(); });
  applyGridFilter(svcGrid, latestSvcs, matchSvcFilter, svcFilter);
}
function syncTaskFilterUI() {
  renderFilterChips($('#taskFilter'), TASK_FILTERS, latestTasks, taskFilter, matchTaskFilter,
    f => { taskFilter = f; syncTaskFilterUI(); });
  applyGridFilter(taskGrid, latestTasks, matchTaskFilter, taskFilter);
}

/* ---------------- 分区过滤芯片 ---------------- */
const SVC_FILTERS = [['all', '全部'], ['running', '运行中'],
  ['stopped', '已停止'], ['error', '异常']];
const TASK_FILTERS = [['all', '全部'], ['running', '运行中'],
  ['succeeded', '成功'], ['failed', '失败'], ['canceled', '已取消']];
let svcFilter = 'all', taskFilter = 'all';
/* 芯片按钮只创建一次，点击时必须读取当轮数据而不是首次渲染的闭包快照 */
let latestSvcs = [], latestTasks = [];

function svcHasError(app) {
  if (app.alerts?.length) return true;
  if (app.portConflict || app.portOccupied || hasPortMismatch(app)) return true;
  if (!app.running && app.canStart !== false && app.health && app.health.blocking) return true;
  if (!app.running && app.lastExit) {
    const isTask = (app.kind || 'service') === 'task';
    return isTask ? taskExitStatus(app.lastExit) === 'failed'
      : app.lastExit.code !== 0;
  }
  return false;
}
function matchSvcFilter(app, filter) {
  if (filter === 'running') return !!app.running;
  if (filter === 'stopped') return !app.running;
  if (filter === 'error') return svcHasError(app);
  return true;
}
function matchTaskFilter(app, filter) {
  if (filter === 'running') return !!app.running;
  if (filter === 'all') return true;
  if (app.running || !app.lastExit) return false;
  const status = taskExitStatus(app.lastExit);
  if (filter === 'canceled') return status === 'canceled' || status === 'stopped';
  return status === filter;
}

function renderFilterChips(row, defs, apps, active, match, onPick) {
  if (!row) return;
  if (row._sig !== defs) {
    row.replaceChildren();
    row._sig = defs;
    row._btns = new Map();
    for (const [key, label] of defs) {
      const btn = el('button', 'fchip');
      btn.type = 'button';
      const text = el('span');
      text.textContent = label;
      const count = el('span', 'fc-n');
      btn.append(text, count);
      btn.addEventListener('click', () => onPick(key));
      row.appendChild(btn);
      row._btns.set(key, { btn, count });
    }
  }
  for (const [key] of defs) {
    const item = row._btns.get(key);
    item.btn.classList.toggle('active', key === active);
    setText(item.count, String(apps.filter(a => match(a, key)).length));
  }
}

function applyGridFilter(grid, apps, match, filter) {
  if (!grid) return;
  const byId = new Map(apps.map(a => [a.id, a]));
  for (const card of grid.querySelectorAll('.app-card[data-key]')) {
    const app = byId.get(card.dataset.key);
    card.hidden = app ? !match(app, filter) : false;
  }
}
