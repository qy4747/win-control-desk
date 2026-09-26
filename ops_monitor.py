"""Shared background snapshots, explicit alert rules and manual presets."""
import collections
import concurrent.futures
import copy
import datetime
import json
import logging
import os
import stat
import threading
import time
import uuid

from ops_model import http_action, number, script_command, preset_steps
from ops_entries import refresh_instance, browser_card_rule, desktop_rule_upgrade_needed
from win_notify import Notifier

LOG = logging.getLogger('console')
SNAPSHOT_METRIC = 'directorySnapshotGrowthBytes'


def snapshot_slot(now, times):
    """Latest local clock slot: a resume catches up once, never once per missed slot."""
    today = datetime.datetime.fromtimestamp(now).date()
    return max(datetime.datetime.combine(today - datetime.timedelta(days=day),
               datetime.time.fromisoformat(t)).timestamp()
               for day in (0, 1) for t in times
               if datetime.datetime.combine(today - datetime.timedelta(days=day),
                  datetime.time.fromisoformat(t)).timestamp() <= now)


def snapshot_delta(history, window):
    if not history:
        return None
    at, size = history[-1]
    baseline = next((p for p in reversed(history[:-1]) if p[0] <= at-window), None)
    # ponytail: sparse clock samples approximate a window; reject baselines over 12 h late.
    if baseline is None or at-baseline[0] > window+43200:
        return None
    return dict(bytes=size-baseline[1], fromAt=baseline[0], toAt=at)


def take_directory_snapshot(path, cancel=None):
    started = time.monotonic()
    result = directory_size(path, budget=60, cancel=cancel)
    return dict(result, durationMs=round((time.monotonic()-started)*1000, 1))


def directory_size(path, budget=2, cancel=None):
    deadline, total, todo = time.monotonic()+budget, 0, [path]
    try:
        parent = os.path.abspath(path)
        while parent != os.path.dirname(parent):
            s = os.stat(parent, follow_symlinks=False)
            if stat.S_ISLNK(s.st_mode) or getattr(s, 'st_file_attributes', 0) & 0x400:
                return {'status': 'unavailable', 'bytes': None}
            parent = os.path.dirname(parent)
        while todo:
            if time.monotonic() > deadline or (cancel is not None and cancel.is_set()):
                return {'status': 'incomplete', 'bytes': None}
            root = todo.pop()
            attrs = os.stat(root, follow_symlinks=False)
            if stat.S_ISLNK(attrs.st_mode) or getattr(attrs, 'st_file_attributes', 0) & 0x400:
                if root == path:
                    return {'status': 'unavailable', 'bytes': None}
                continue
            with os.scandir(root) as entries:
                for entry in entries:
                    if time.monotonic() > deadline or (cancel is not None and cancel.is_set()):
                        return {'status': 'incomplete', 'bytes': None}
                    s = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(s.st_mode) or getattr(s, 'st_file_attributes', 0) & 0x400:
                        continue
                    if stat.S_ISDIR(s.st_mode):
                        todo.append(entry.path)
                    elif stat.S_ISREG(s.st_mode):
                        total += s.st_size
        return {'status': 'ok', 'bytes': total}
    except OSError:
        return {'status': 'unavailable', 'bytes': None}


class Alerts:
    def __init__(self, emit, ignored=None, overrides=None):
        self.states = {}
        self.emit = emit
        self.overrides = copy.deepcopy(overrides or {})
        for key, saved in (ignored or {}).items():
            if isinstance(saved, dict) and all(isinstance(saved.get(k), str) for k in ('incident', 'target', 'title')):
                self.states[key] = dict(active=True, since=None, failures=0, successes=0,
                    incident=saved['incident'], target=saved['target'], title=saved['title'],
                    value=None, ignored=True, unknown=True, muted=False, reported=False)

    def check(self, key, bad, value, rule, now, fail=1, recover=1, silent=False):
        state = self.states.setdefault(key, dict(active=False, since=None, failures=0, successes=0))
        state.update(title=rule['name'], value=value, target=rule.get('appId', 'system'), muted=rule.get('muted', False))
        for field in ('metric', 'threshold', 'recoveryThreshold'):
            state[field] = rule.get(field)
        state['comparison'] = 'below' if rule.get('metric') == 'diskFreePercent' else 'above'
        state['ruleSignature'] = self.signature(rule)
        override = self.overrides.get(key)
        if override and override['mode'] == 'temporary' and override.get('signature') != self.signature(rule):
            self.overrides.pop(key)
            override = None
        if override and override['mode'] == 'temporary' and bad is not None:
            # Recovery is measured against the original rule, not the relaxed threshold.
            restored = not bad
            if rule.get('threshold') is not None and value is not None:
                recovery = rule.get('recoveryThreshold', rule['threshold'])
                restored = value >= recovery if state['comparison'] == 'below' else value <= recovery
            override['recoveries'] = override.get('recoveries', 0) + 1 if restored else 0
            if override['recoveries'] >= recover:
                self.overrides.pop(key)
                override = None
            elif override.get('threshold') is not None:
                bad = value < override['threshold'] if state['comparison'] == 'below' else value > override['threshold']
        state['ignored'] = bool(override and (override['mode'] == 'permanent' or override.get('threshold') is None)) or state.get('ignored', False)
        if not override and state.get('overrideMode'):
            state['ignored'] = False
        state['overrideMode'] = override['mode'] if override else None
        state['temporaryThreshold'] = override.get('threshold') if override else None
        if bad is None:
            if override: override['recoveries'] = 0
            state.update(since=None, failures=0, successes=0, unknown=True)
            return
        state['unknown'] = False
        if bad:
            state['successes'] = 0
            state['failures'] += 1
            if state['since'] is None:
                state['since'] = now
            if not state['active'] and state['failures'] >= fail and now-state['since'] >= rule.get('durationSec', 0):
                state['active'] = True
                state.update(incident=uuid.uuid4().hex, ignored=bool(override and (override['mode'] == 'permanent' or override.get('threshold') is None)))
                state['reported'] = not silent
                if not silent:
                    self.emit(dict(key=key, target=state['target'], title=rule['name'], phase='alert',
                                   value=value, detail=str(value), muted=state['muted'] or state['ignored']))
        else:
            state['since'], state['failures'] = None, 0
            state['successes'] += 1
            if state['active'] and state['successes'] >= recover:
                state['active'] = False
                if not silent and state.get('reported'):
                    self.emit(dict(key=key, target=state['target'], title=rule['name']+' 已恢复', phase='recovered',
                                   value=value, detail=str(value), muted=state['muted'] or state.get('ignored', False)))

    @staticmethod
    def signature(rule):
        return [rule.get(k) for k in ('metric', 'threshold', 'recoveryThreshold', 'durationSec')]

    def accept(self, key, incident, mode, threshold=None):
        state = self.states.get(key)
        if not state or not state['active'] or state.get('incident') != incident:
            raise ValueError('异常已恢复或发生变化，请刷新后重试')
        if mode not in ('temporary', 'permanent'):
            raise ValueError('接受方式无效')
        if mode == 'temporary' and state.get('threshold') is not None:
            if state.get('unknown') or state.get('value') is None:
                raise ValueError('采集不可用，不能调整临时阈值')
            high = 100 if state['metric'] in ('cpu', 'memoryPercent', 'gpuPercent', 'diskFreePercent') else 1e18
            number(threshold, '临时阈值', high=high)
            if (state['comparison'] == 'below' and threshold > min(state['value'], state['threshold'])) or (state['comparison'] == 'above' and threshold < max(state['value'], state['threshold'])):
                raise ValueError('临时阈值必须容纳当前读数，且不能比原阈值更严格')
        else:
            threshold = None
        self.overrides[key] = dict(mode=mode, threshold=threshold, target=state['target'], title=state['title'], signature=state.get('ruleSignature'), recoveries=0)
        state.update(ignored=True, overrideMode=mode, since=None, failures=0, successes=0)
        if threshold is not None:
            # Accepting a baseline is not a recovery event.
            state.update(active=False, reported=False, ignored=False)

    def revoke(self, key):
        if key not in self.overrides:
            raise ValueError('接受规则不存在')
        self.overrides.pop(key)
        if key in self.states:
            self.states[key].update(active=False, ignored=False, reported=False, since=None, failures=0, successes=0, overrideMode=None)

    def ignore(self, key, incident):
        state = self.states.get(key)
        if not state or not state['active'] or state.get('incident') != incident:
            raise ValueError('异常已恢复或发生变化，请刷新后重试')
        state['ignored'] = True

    def ignored(self):
        return {key: {k: state[k] for k in ('incident', 'target', 'title')}
                for key, state in self.states.items() if state['active'] and state.get('ignored') and not state.get('overrideMode')}

    def active(self, target=None):
        return [dict(key=k, **v) for k, v in self.states.items()
                if v['active'] and (target is None or v['target'] == target)]


class Monitor:
    def __init__(self, host, api, notifications=True):
        self.host, self.api, self.cfg = host, api, host.cfg
        self.lock = threading.RLock()
        self.wake, self.stopped = threading.Event(), threading.Event()
        self.last_active = 0
        self.state = dict(apps=[], services=[], watched=[], degraded=True,
                          degradedReasons=[{'component': 'apps'}], sampledAt=None)
        self.events = collections.deque(maxlen=300)
        self.event_path = os.path.join(api.LOGS_DIR, 'events.jsonl')
        try:
            for line in api._tail_file_lines(self.event_path, 300):
                self.events.append(json.loads(line))
        except (OSError, ValueError, TypeError):
            pass
        self.notifier = Notifier(notifications)
        self.alerts = Alerts(self.emit, self.cfg.snapshot().get('ignoredAlerts'), self.cfg.snapshot().get('alertOverrides'))
        self.probes, self.directories, self.jobs = {}, {}, {}
        self.snapshot_job = None
        self.directory_snapshots = self.cfg.snapshot().get('directorySnapshots', {})
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix='checks')
        self.previous_config = {}
        self.exit_baseline = {}
        self.rule_next = {}
        self.histories = {}
        self.disk_total = 0
        self.disk_time = None
        self.run = None
        self.cancel = threading.Event()
        self.started_mono = time.monotonic()
        self.initial = True
        self.cfg.monitor = self
        self.thread = threading.Thread(target=self.loop, daemon=True, name='monitor')

    def start(self):
        self.thread.start()

    def close(self):
        self.stopped.set()
        self.cancel.set()
        self.wake.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.notifier.close()

    def emit(self, event):
        event = dict(event, id=uuid.uuid4().hex, at=time.time())
        with self.lock:
            self.events.append(event)
            try:
                self.api.rotate_log_file(self.event_path, 5*1024*1024, 2)
                fd = os.open(self.event_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
                with os.fdopen(fd, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(event, ensure_ascii=False)+'\n')
            except OSError:
                LOG.exception('事件记录失败')
        if not event.get('muted'):
            self.notifier.send(event)

    def snapshot(self, active=False):
        with self.lock:
            if active:
                self.last_active = time.monotonic()
            data = copy.deepcopy(self.state)
            data['notificationStatus'] = self.notifier.status
            data['events'] = list(reversed(copy.deepcopy(self.events)))
            data['presetRun'] = copy.deepcopy(self.run)
            data['alerts'] = self.alerts.active()
            data['alertOverrides'] = copy.deepcopy(self.alerts.overrides)
            for app in data.get('apps', []):
                app['alerts'] = self.alerts.active(app['id'])
            data['stale'] = bool(data.get('stale')) or not data.get('sampledAt') or time.time()-data['sampledAt'] > 25
            return data

    def ignore_alert(self, key, incident):
        with self.lock:
            self.alerts.ignore(key, incident)
            try:
                saved = self.alerts.ignored()
                self.cfg.update(lambda c: c.update(ignoredAlerts=saved))
            except Exception:
                self.alerts.states[key]['ignored'] = False
                raise

    def accept_alert(self, key, incident=None, mode='temporary', threshold=None):
        with self.lock:
            saved_states, saved_overrides = copy.deepcopy(self.alerts.states), copy.deepcopy(self.alerts.overrides)
            try:
                if mode == 'revoke':
                    self.alerts.revoke(key)
                else:
                    self.alerts.accept(key, incident, mode, threshold)
                self.cfg.update(lambda c: c.update(alertOverrides=copy.deepcopy(self.alerts.overrides), ignoredAlerts=self.alerts.ignored()))
            except Exception:
                self.alerts.states, self.alerts.overrides = saved_states, saved_overrides
                raise

    def effective_config(self, cfg):
        cfg = copy.deepcopy(cfg)
        preset = next((p for p in cfg.get('presets', []) if p['id'] == cfg.get('activePreset')), None)
        if preset:
            for rule in cfg.get('rules', []):
                if rule['id'] in preset.get('ruleOverrides', {}):
                    rule['threshold'] = preset['ruleOverrides'][rule['id']]
                    rule['recoveryThreshold'] = rule['threshold']
            for app in cfg['apps']:
                app['alertPolicy'] = {**app.get('alertPolicy', {}), **preset.get('appOverrides', {}).get(app['id'], {})}
        return cfg

    def async_checks(self, apps, rules, now):
        self.check_directory_snapshots(rules)
        for key, job in list(self.jobs.items()):
            if not job[0].done():
                continue
            future, signature, due = self.jobs.pop(key)
            try:
                value = future.result()
            except Exception:
                value = {'ok': False, 'status': 'unavailable'}
            target = self.probes if key[0] == 'http' else self.directories
            target[key[1]] = dict(value, signature=signature, checkedAt=time.time(), nextAt=due)
        for app in apps:
            spec = app.get('probe')
            if not app['running'] or not spec:
                self.probes.pop(app['id'], None)
                continue
            signature = json.dumps(spec, sort_keys=True) + str(app.get('startedAt')) + str(app.get('pid'))
            old = self.probes.get(app['id'], {})
            key = ('http', app['id'])
            if key not in self.jobs and (old.get('signature') != signature or now >= old.get('nextAt', 0)):
                self.jobs[key] = (self.pool.submit(http_action, spec), signature, now+10)
        paths = {}
        for r in rules:
            if r['metric'].startswith('directory') and r['metric'] != SNAPSHOT_METRIC:
                paths[r['path']] = min(paths.get(r['path'], float('inf')), max(900, r['intervalSec']))
        for path, interval in paths.items():
            key = ('directory', path)
            if key not in self.jobs and now >= self.directories.get(path, {}).get('nextAt', 0):
                self.jobs[key] = (self.pool.submit(directory_size, path), path, now+interval)
        active_apps = {a['id'] for a in apps}
        for mapping, keep in ((self.probes, active_apps), (self.directories, paths),
                              (self.histories, {r['id'] for r in rules}),
                              (self.rule_next, {r['id'] for r in rules}),
                              (self.previous_config, active_apps), (self.exit_baseline, active_apps)):
            for key in list(mapping):
                if key not in keep: mapping.pop(key)

    def check_directory_snapshots(self, rules):
        paths = {}
        for rule in rules:
            if rule['metric'] == SNAPSHOT_METRIC:
                paths.setdefault(rule['path'], set()).update(rule['dailyTimes'])
        wall = time.time()
        saved = self.cfg.snapshot().get('directorySnapshots', {})
        changed = set(saved) - set(paths)
        if self.snapshot_job and self.snapshot_job[0].done():
            future, path = self.snapshot_job
            self.snapshot_job = None
            try:
                result = future.result()
            except Exception:
                result = dict(status='unavailable', bytes=None)
            if path in paths:
                record = dict(saved.get(path, {}), **result, checkedAt=wall)
                history = record.get('history', [])
                if result.get('status') == 'ok':
                    history = [p for p in history if wall-691200 <= p[0] < wall]
                    history.append([wall, result['bytes']])
                record['history'] = history[-40:]
                saved[path] = record
                changed = True
        if changed:
            # Filter against the latest configuration as a rule may be removed during a scan.
            def save(c):
                active = {r['path'] for r in c['rules'] if r['metric'] == SNAPSHOT_METRIC}
                c['directorySnapshots'] = {p: v for p, v in saved.items() if p in active}
            self.cfg.update(save)
        self.directory_snapshots = self.cfg.snapshot().get('directorySnapshots', {}) if changed else saved
        if self.snapshot_job or self.stopped.is_set():
            return
        for path, times in paths.items():
            record = self.directory_snapshots.get(path, {})
            if snapshot_slot(wall, times) <= record.get('attemptedAt', 0):
                continue
            record = dict(record, attemptedAt=wall)
            def reserve(c):
                if any(r['metric'] == SNAPSHOT_METRIC and r['path'] == path for r in c['rules']):
                    c['directorySnapshots'][path] = record
                    return True
                return False
            reserved = self.cfg.update(reserve)
            self.directory_snapshots = self.cfg.snapshot().get('directorySnapshots', {})
            if reserved:
                self.snapshot_job = (self.pool.submit(take_directory_snapshot, path, self.stopped), path)
            break

    def snapshot_readings(self):
        return {path: dict(record,
                    running=bool(self.snapshot_job and self.snapshot_job[1] == path),
                    day=snapshot_delta(record.get('history', []), 86400),
                    week=snapshot_delta(record.get('history', []), 604800))
                for path, record in self.directory_snapshots.items()}

    def loop(self):
        while not self.stopped.is_set():
            started = time.monotonic()
            try:
                self.collect()
            except Exception:
                LOG.exception('后台采集失败')
                with self.lock:
                    self.state['degraded'] = True
                    self.state['stale'] = True
                    for app in self.state.get('apps', []):
                        app['statusKnown'] = False
            interval = 2 if time.monotonic()-self.last_active < 8 else 10
            self.wake.wait(max(.1, interval-(time.monotonic()-started)))
            self.wake.clear()

    def collect(self):
        start = now = time.monotonic()
        with self.api.MANUAL_STOP_LOCK:
            stopping = {ident for ident, _ in self.api.MANUAL_STOP_TOKENS}
            cfg = self.effective_config(self.cfg.snapshot())
        data = self.api.build_state(cfg, self.host.console_port, self.cfg.health_info())
        matches, changed = {}, False
        if self.api.IS_WIN and not data.get('degraded'):
            for item in data['apps']:
                rule = item.get('instanceMatch') or {}
                service = rule.get('service') or {}
                needs_upgrade = service.get('runtime') in ('python', 'node') and 'argsHash' not in service
                needs_upgrade |= bool(not rule.get('browserMain') and browser_card_rule(self.api, item))
                needs_upgrade |= desktop_rule_upgrade_needed(item)
                if not rule or (item['running'] and not needs_upgrade
                                and not (item.get('backgroundOnly') and rule.get('windowClass'))):
                    continue
                lock = self.host.try_app_operation(item['id'])
                if lock is None:
                    continue
                try:
                    original = self.api.find_app(self.cfg.snapshot(), item['id'])
                    if original is None:
                        continue
                    updated, error = refresh_instance(self.api, self.cfg, original)
                    if error:
                        matches[item['id']] = error
                    changed |= (updated.get('externalIdentity') != original.get('externalIdentity')
                                or updated.get('instanceMatch') != original.get('instanceMatch'))
                finally:
                    lock.release()
            if changed:
                cfg = self.effective_config(self.cfg.snapshot())
                data = self.api.build_state(cfg, self.host.console_port, self.cfg.health_info())
        table = self.api._win_process_table() if self.api.IS_WIN else {}
        for service in data.get('services', []):
            service['gpuMemoryBytes'] = table.get(service['pid'], {}).get('gpuMemoryBytes')
        system = copy.deepcopy(self.api._NATIVE_METRICS.system) if self.api.IS_WIN and self.api._NATIVE_METRICS else {}
        valid = not data.get('degraded')
        if not data['apps'] and cfg['apps'] and not valid:
            previous = {a['id']: a for a in self.state.get('apps', [])}
            data['apps'] = [copy.deepcopy(previous[a['id']]) for a in cfg['apps'] if a['id'] in previous]
        for app in data['apps']:
            rows = [table[p] for p in set(app.get('pids', [])) if p in table]
            app['resources'] = dict(
                cpu=sum(r['cpu'] for r in rows) if rows and all(r.get('cpu') is not None for r in rows) else None,
                memoryBytes=sum(r['ws'] for r in rows) if rows and all(r.get('ws') is not None for r in rows) else None,
                gpuMemoryBytes=sum(r['gpuMemoryBytes'] for r in rows) if rows and all(r.get('gpuMemoryBytes') is not None for r in rows) else None,
                ioWriteBytes=sum(r['ioWriteBytes'] for r in rows) if rows and all(r.get('ioWriteBytes') is not None for r in rows) else None)
            original = self.api.find_app(cfg, app['id'])
            app['statusKnown'] = valid and (app['running'] or not self.api.app_identity_uncertain(original))
            app['associationState'] = 'unknown' if not app['statusKnown'] else 'verified' if app['running'] else 'stopped'
            app['associationDetail'] = matches.get(app['id'], '')
            if app['associationDetail']:
                app['statusKnown'] = False
                app['associationState'] = 'ambiguous'
            if app.get('kind') == 'desktop' and not app['running'] and app.get('expectedRunning') and (app.get('lastExit') or {}).get('durationSec', 999) < 5:
                app['associationState'] = 'pending'
        self.async_checks(data['apps'], cfg.get('rules', []), now)
        with self.lock:
            # A stop can finish while this sample is being collected. In that
            # case its old expectedRunning must not raise a late exit alert.
            with self.api.MANUAL_STOP_LOCK:
                stopping.update(ident for ident, _ in self.api.MANUAL_STOP_TOKENS)
                latest = {a['id']: a for a in self.cfg.snapshot()['apps']}
            lifecycle_fields = ('expectedRunning', 'runToken', 'externalIdentity', 'startedAt')
            for app in data['apps']:
                before = self.api.find_app(cfg, app['id']) or {}
                after = latest.get(app['id'], {})
                app['lifecycleChanging'] = app['id'] in stopping or any(
                    before.get(key) != after.get(key) for key in lifecycle_fields)
            self.check_apps(data['apps'], now, valid)
            self.check_system(system, cfg.get('rules', []), now)
            ignored = self.alerts.ignored()
            if ignored != self.cfg.snapshot().get('ignoredAlerts', {}) or self.alerts.overrides != self.cfg.snapshot().get('alertOverrides', {}):
                self.cfg.update(lambda c: c.update(ignoredAlerts=ignored, alertOverrides=copy.deepcopy(self.alerts.overrides)))
            data.update(system=system, rules=cfg.get('rules', []), presets=cfg.get('presets', []),
                        activePreset=cfg.get('activePreset'), alerts=self.alerts.active(),
                        directories=copy.deepcopy(self.directories), sampledAt=time.time(),
                        directorySnapshots=self.snapshot_readings(),
                        collectorDurationMs=round((time.monotonic()-start)*1000, 1))
            self.state = data
        self.initial = False

    def check_apps(self, apps, now, valid):
        ids = {a['id'] for a in apps}
        for mapping in (self.alerts.states, self.alerts.overrides):
            for key in list(mapping):
                if key.startswith('app:') and key.split(':')[1] not in ids:
                    mapping.pop(key)
        for app in apps:
            ident, policy = app['id'], app.get('alertPolicy') or {}
            muted = policy.get('muted', [])
            def check(kind, bad, value, label, duration=0, fail=1, recover=1, silent=False, metric=None, threshold=None):
                if app.get('lifecycleChanging') and kind in ('exit', 'port', 'http'):
                    bad = None  # Pause evaluation; do not fabricate recovery either.
                self.alerts.check('app:'+ident+':'+kind, bad if valid and app.get('statusKnown', True) else None, value,
                    dict(name=app['name']+' · '+label, appId=ident, muted=kind in muted, durationSec=duration, metric=metric, threshold=threshold),
                    now, fail, recover, silent)
            blocked = bool(app['health']['blocking']) and app.get('canStart', True)
            before = self.previous_config.get(ident)
            check('config', blocked, '配置不可用' if blocked else '配置有效', '配置异常', silent=before is None)
            if valid:
                self.previous_config[ident] = blocked
            kind, exit_policy = app.get('kind'), policy.get('exitPolicy', 'default')
            exit_info = app.get('lastExit') or {}
            signature = (exit_info.get('at'), exit_info.get('startedAt'))
            first = ident not in self.exit_baseline and self.initial
            if valid:
                self.exit_baseline[ident] = signature
            failed_exit = exit_info.get('code') not in (None, 0, 130) and exit_info.get('status') != 'stopped'
            expected = app.get('expectedRunning') and (exit_policy == 'always' or (exit_policy == 'default' and kind == 'service'))
            bad = not app['running'] and (bool(expected) or (exit_policy != 'never' and failed_exit))
            check('exit', bad, '意外退出' if bad else '运行状态正常', '运行异常', silent=first)
            grace = time.time()-(app.get('startedAt') or 0) < policy.get('graceSec', 30)
            probe = self.probes.get(ident)
            app['probeState'] = dict(status='not-configured') if not app.get('probe') else dict(status='stopped' if not app['running'] else 'pending')
            if probe and app['running']:
                expected_sig = json.dumps(app['probe'], sort_keys=True)+str(app.get('startedAt'))+str(app.get('pid'))
                if probe['signature'] == expected_sig:
                    app['probeState'] = dict(status='ok' if probe.get('ok') else 'error', checkedAt=probe['checkedAt'])
            check('port', bool(app.get('port') and not app.get('listening')) if app['running'] and not grace else False,
                  '配置端口未监听' if not app.get('listening') else '端口监听中', '端口异常', fail=3, recover=2)
            probe_key = 'app:'+ident+':http'
            latest = app['probeState'].get('checkedAt')
            if not app['running'] or not app.get('probe'):
                check('http', False, '探测未启用', '接口不可用', recover=1)
            elif latest and not grace and self.alerts.states.get(probe_key, {}).get('probeAt') != latest:
                check('http', app['probeState']['status'] != 'ok', app['probeState']['status'], '接口不可用', fail=3, recover=2)
                self.alerts.states[probe_key]['probeAt'] = latest
            for metric, setting, label in [('cpu', 'cpuPercent', 'CPU 持续超限'), ('memoryBytes', 'memoryBytes', '内存持续超限')]:
                threshold, value = policy.get(setting), app['resources'].get(metric)
                bad = False if threshold is None or not app['running'] else (None if value is None else value > threshold)
                check('cpu' if metric == 'cpu' else 'memory', bad, value, label, policy.get('durationSec', 60), metric=metric, threshold=threshold)
            app['alerts'] = self.alerts.active(ident)

    def increment(self, key, value, now, window):
        history = self.histories.setdefault(key, collections.deque(maxlen=9002))
        if value is None:
            history.clear()
            return None
        # ponytail: bound a day's samples to 9002 points; long windows use ~10 s resolution.
        if not history or now-history[-1][0] >= window/8999:
            history.append((now, value))
        while len(history) > 1 and history[1][0] <= now-window:
            history.popleft()
        return max(0, value-history[0][1]) if history and now-history[0][0] >= window else None

    def check_system(self, system, rules, now):
        rate = system.get('diskWriteBytesPerSec')
        if self.disk_time is not None and rate is not None:
            self.disk_total += rate*max(0, now-self.disk_time)
        self.disk_time = now if rate is not None else None
        keep = {r['id'] for r in rules}
        for mapping in (self.alerts.states, self.alerts.overrides):
            for key in list(mapping):
                if key.startswith('rule:') and key.split(':')[1] not in keep:
                    mapping.pop(key)
        for r in rules:
            metric = r['metric']
            if r['metric'].startswith('directory'):
                prefix = 'rule:'+r['id']+':'
                for mapping in (self.alerts.states, self.alerts.overrides):
                    for key in list(mapping):
                        if key.startswith(prefix) and key != prefix+r['path']:
                            mapping.pop(key)
                            self.histories.pop(r['id'], None)
            if metric == SNAPSHOT_METRIC:
                record = self.directory_snapshots.get(r['path'], {})
                stamp = (r['path'], record.get('checkedAt'))
                if self.rule_next.get(r['id']) == stamp:
                    continue
                self.rule_next[r['id']] = stamp
            else:
                next_check = self.rule_next.get(r['id'], 0)
                if isinstance(next_check, (int, float)) and now < next_check:
                    continue
                self.rule_next[r['id']] = now+r.get('intervalSec', 10)
            values = {'system': system.get(metric)}
            if metric == 'diskFreePercent':
                values = {d['path']: d['freePercent'] for d in system.get('disks', [])}
            elif metric == SNAPSHOT_METRIC:
                delta = snapshot_delta(record.get('history', []), r['windowSec']) if record.get('status') == 'ok' else None
                values = {r['path']: delta['bytes'] if delta else None}
            elif metric.startswith('directory'):
                d = self.directories.get(r['path'], {})
                value = d.get('bytes') if d.get('status') == 'ok' else None
                if metric == 'directoryGrowthBytes':
                    value = self.increment(r['id'], value, now, r.get('windowSec', 900))
                values = {r['path']: value}
            elif metric == 'diskWriteBytes':
                values = {'system': self.increment(r['id'], self.disk_total if rate is not None else None, now, r.get('windowSec', 60))}
            elif metric == 'gpuPercent':
                values = {g['id']: g['dedicatedBytes']/g['capacityBytes']*100 if g.get('capacityBytes') and g.get('dedicatedBytes') is not None else None for g in system.get('gpus', [])}
            prefix = 'rule:'+r['id']+':'
            for key in list(self.alerts.states):
                if key.startswith(prefix) and key[len(prefix):] not in values:
                    self.alerts.check(key, None, None, dict(r, name=r['name']+' · '+key[len(prefix):]), now)
            for target, value in values.items():
                key = 'rule:'+r['id']+':'+target
                active = self.alerts.states.get(key, {}).get('active')
                threshold = r.get('recoveryThreshold', r['threshold']) if active else r['threshold']
                bad = None if value is None else value < threshold if metric == 'diskFreePercent' else value > threshold
                self.alerts.check(key, bad, value, dict(r, name=r['name']+' · '+target), now)

    def discover(self, all_processes=False):
        if not self.api.IS_WIN:
            return []
        from win_metrics import windows
        table = self.api._win_process_table()
        visible = windows()
        services = self.snapshot().get('services', [])
        ports = {}
        for s in services:
            ports.setdefault(s['pid'], []).append(s['port'])
        rows = []
        for pid, p in table.items():
            if pid == self.api.SELF_PID or (not all_processes and pid not in visible and pid not in ports):
                continue
            if self.api.process_uid(pid) != self.api.SELF_UID:
                continue
            rows.append(dict(pid=pid, created=p['identity'], exe=p['exe'], command=p['args'],
                             name=visible.get(pid, [(None, p['name'])])[0][1], ports=ports.get(pid, []),
                             kind='desktop' if pid in visible else 'service'))
        return rows

    def execute_action(self, app, action_id):
        action = next((a for a in app.get('actions', []) if a['id'] == action_id), None)
        if not action:
            return {'ok': False, 'error': '操作不存在'}
        if action['type'] == 'script':
            app, error = refresh_instance(self.api, self.cfg, app)
            if error:
                return {'ok': False, 'error': error}
        running = self.api.app_running(app) if action['when'] != 'always' else False
        if (action['when'] == 'running' and not running) or (action['when'] == 'stopped' and running):
            return {'ok': False, 'error': '当前状态不允许此操作'}
        try:
            if action['type'] == 'url':
                return {'ok': True, 'url': action['url']}
            if action['type'] == 'http':
                result = http_action(action)
            elif action['type'] == 'location':
                from ops_entries import open_location
                result = open_location(action)
            else:
                extra_env = {}
                if action['type'] == 'script':
                    if not os.path.isfile(action['path']):
                        raise ValueError('脚本文件不存在')
                    command, shell = script_command(action)
                    context = dict(appId=app['id'], name=app['name'], cwd=app.get('cwd'),
                                   port=app.get('port'), processes=[])
                    if self.api.IS_WIN and self.api.app_running(app):
                        table = self.api._win_process_table(refresh=True)
                        target, error = self.api.resolve_app_stop_target(app)
                        if not target:
                            raise ValueError(error)
                        for pid in target['members']:
                            created = table.get(pid, {}).get('identity')
                            if not created or (target['kind'] == 'external' and pid == target['id']
                                    and created != target['identity']['created']):
                                raise ValueError('进程身份已变化，请刷新后重试')
                            context['processes'].append(dict(pid=pid, created=created))
                    extra_env['CDDECK_APP_CONTEXT'] = json.dumps(context, ensure_ascii=False)
                else:
                    command, shell = action['command'], action['shell']
                task = dict(app, id=app['id']+'-action', command=command, shell=shell)
                ok, error, proc, pgid, token = (self.api.start_app(task, extra_env=extra_env)
                    if extra_env else self.api.start_app(task))
                if not ok:
                    raise ValueError(error)
                try:
                    code = proc.wait(timeout=action.get('timeoutSec', 30))
                    result = dict(ok=code == 0, code=code)
                    if code != 0:
                        result['error'] = '脚本或命令退出码 %s，请查看 %s-action.log' % (code, app['id'])
                except Exception:
                    # Only the newly created action tree, never the managed app.
                    self.api.stop_pid_tree(pgid, force=True)
                    result = dict(ok=False, error='操作超时，已结束本次操作进程')
            if not result.get('ok') and not result.get('error'):
                result['error'] = '操作执行失败'
        except ValueError as exc:
            result = dict(ok=False, error=str(exc))
        except Exception as exc:
            # Do not echo requests, headers, bodies or arbitrary server responses.
            result = dict(ok=False, error='操作请求失败：'+type(exc).__name__)
        self.emit(dict(key='action:'+app['id'], target=app['id'], title=app['name']+' · '+action['name'],
                       phase='action', detail='成功' if result.get('ok') else result.get('error', '失败'), muted=True))
        return result

    def start_preset(self, ident, action=None):
        cfg = self.cfg.snapshot()
        preset = next((p for p in cfg.get('presets', []) if p['id'] == ident), None)
        if not preset:
            raise ValueError('预设不存在')
        steps = preset_steps(preset, cfg.get('presets', []), action)
        if preset.get('type') == 'package' and not steps:
            raise ValueError('预设包暂无应用，请先添加成员')
        with self.lock:
            if self.run and self.run['status'] == 'running':
                raise ValueError('已有预设正在执行')
            if preset.get('type') != 'package':
                self.cfg.update(lambda c: c.update(activePreset=ident))
            self.run = dict(id=uuid.uuid4().hex, presetId=ident, type=preset.get('type', 'scene'), action=action,
                            name=preset['name'], status='running',
                            steps=[dict(s, status='waiting') for s in steps])
            self.cancel.clear()
        threading.Thread(target=self._preset_worker, args=(preset,), daemon=True, name='preset').start()
        return self.run

    def _preset_worker(self, preset):
        try:
            failed = False
            for step in self.run['steps']:
                if failed and preset.get('type') != 'package':
                    step.update(status='skipped', detail='前一步失败，未继续切换场景')
                    continue
                if self.cancel.is_set() or self.stopped.is_set():
                    step.update(status='skipped', detail='已取消后续操作')
                    continue
                lock = self.host.try_app_operation(step['appId'])
                if lock is None:
                    step.update(status='failed', detail='对象有其他操作正在执行')
                    failed = True
                    continue
                try:
                    app = self.api.find_app(self.cfg.snapshot(), step['appId'])
                    if app is None:
                        raise ValueError('应用已被删除')
                    app, error = refresh_instance(self.api, self.cfg, app)
                    if error or self.api.app_identity_uncertain(app):
                        raise ValueError(error or '应用身份无法确认，未执行场景操作')
                    running = self.api.app_running(app)
                    if step['action'] == 'stop' and not running:
                        self.api.clear_app_runtime(self.cfg, app['id'])
                    already_running = step['action'] == 'start' and running and not self.api.desktop_background_only(app)
                    wait_existing = (preset.get('type') != 'package' and step['action'] == 'start'
                                     and already_running and bool(app.get('probe') or app.get('port')))
                    if step['action'] == 'keep' or (step['action'] == 'start' and already_running and not wait_existing) or (step['action'] == 'stop' and not running):
                        step.update(status='skipped', detail='已满足目标状态')
                        continue
                    step['status'] = 'running'
                    if not wait_existing:
                        result, _ = self.api.operate_app(self.cfg, app, step['action'])
                        if not result.get('ok'):
                            raise ValueError(result.get('error', '操作失败'))
                    if step['action'] == 'start':
                        deadline = time.monotonic()+preset.get('timeoutSec', 30)
                        while time.monotonic() < deadline:
                            if self.cancel.is_set() or self.stopped.is_set():
                                step.update(status='skipped', detail='已发出启动；取消后续等待，不回滚')
                                break
                            current = self.api.find_app(self.cfg.snapshot(), app['id'])
                            if current.get('kind') == 'task':
                                last = self.api.public_last_exit(current) or {}
                                if not self.api.app_running(current) and last.get('startedAt', 0) >= int(current.get('startedAt', 0)*1000):
                                    if last.get('status') == 'succeeded':
                                        break
                                    if last.get('status') in ('failed', 'stopped', 'canceled'):
                                        raise ValueError('任务未成功完成')
                            elif self.api.app_running(current) and not self.api.desktop_background_only(current):
                                if current.get('probe'):
                                    try:
                                        if http_action(current['probe'])['ok']:
                                            break
                                    except Exception:
                                        pass
                                elif not current.get('port') or any(p in self.api.managed_pids(current) and port == current['port'] for p, port in self.api.scan_listeners()):
                                    break
                            self.cancel.wait(.5)
                        else:
                            raise ValueError('启动已发出，但等待就绪超时')
                    if step['status'] != 'skipped':
                        step.update(status='succeeded', detail='操作完成')
                except Exception as exc:
                    step.update(status='failed', detail=str(exc))
                    failed = True
                finally:
                    lock.release()
                    self.wake.set()
            self.run['status'] = 'failed' if failed else 'canceled' if self.cancel.is_set() else 'completed'
        except Exception:
            LOG.exception('预设执行失败')
            self.run['status'] = 'failed'
