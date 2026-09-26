"""Additional routes, using the server's existing auth and per-object locks."""
import copy
import os
import secrets
import time
import urllib.parse

from ops_model import validate_rules, validate_presets, validate_stop_action, reconcile_app_presets
from ops_entries import list_windows, bind_window, operate_window, capture_instance_match, refresh_instance, service_identity, verify_instance_ownership, same_window_executable


def runtime(handler):
    monitor = getattr(handler.server.cfg, 'monitor', None)
    if monitor is None:
        handler.send_err(503, '后台采集尚未就绪')
    return monitor


def get(handler, path, query):
    monitor = runtime(handler)
    if monitor is None:
        return
    if path == '/api/ops/discover':
        params = urllib.parse.parse_qs(query)
        handler.send_json({'items': monitor.discover(params.get('all') == ['1'])})
    elif path == '/api/ops/windows':
        handler.send_json({'items': list_windows(monitor.api)})
    elif path == '/api/ops/config':
        cfg = monitor.cfg.snapshot()
        handler.send_json({k: cfg.get(k) for k in ('rules', 'presets', 'activePreset')})
    elif path == '/api/ops/events':
        handler.send_json({'events': monitor.snapshot()['events']})
    else:
        handler.send_err(404, '接口不存在')


def post(handler, path):
    monitor = runtime(handler)
    if monitor is None:
        handler.discard_body()
        return
    data, error = handler.read_json_body()
    if error:
        handler.send_err(400, error)
        return
    api, cfg = monitor.api, monitor.cfg
    try:
        if path == '/api/ops/discover/import':
            handler.send_json(import_process(monitor, data))
        elif path == '/api/ops/alerts/ignore':
            if not isinstance(data.get('key'), str) or not isinstance(data.get('incident'), str):
                raise ValueError('缺少异常标识')
            monitor.ignore_alert(data['key'], data['incident'])
            handler.send_json({'ok': True})
        elif path == '/api/ops/alerts/accept':
            if not isinstance(data.get('key'), str):
                raise ValueError('缺少异常标识')
            monitor.accept_alert(data['key'], data.get('incident'), data.get('mode'), data.get('threshold'))
            handler.send_json({'ok': True})
        elif path == '/api/ops/rules':
            rules = validate_rules(data.get('rules'))
            if any(r['metric'] == 'gpuPercent' for r in rules) and not any(
                    g.get('capacityBytes') and g.get('dedicatedBytes') is not None
                    for g in monitor.snapshot().get('system', {}).get('gpus', [])):
                raise ValueError('显存容量不可可靠读取，目前仅支持显示用量')
            def save(c):
                # Reject dangling overrides instead of silently changing a mode.
                validate_presets(c.get('presets', []), c['apps'], rules)
                c['rules'] = rules
            cfg.update(save)
            monitor.rule_next.clear()
            handler.send_json({'ok': True})
        elif path == '/api/ops/presets':
            def save(c):
                c['presets'] = validate_presets(data.get('presets'), c['apps'], c['rules'])
                if c.get('activePreset') not in {p['id'] for p in c['presets'] if p.get('type') != 'package'}:
                    c['activePreset'] = None
            cfg.update(save)
            handler.send_json({'ok': True})
        elif path == '/api/ops/presets/run':
            handler.send_json({'ok': True, 'run': monitor.start_preset(data.get('id'), data.get('action'))})
        elif path == '/api/ops/presets/cancel':
            monitor.cancel.set()
            handler.send_json({'ok': True})
        elif path in ('/api/ops/action', '/api/ops/force', '/api/ops/window', '/api/ops/window/bind', '/api/ops/instance'):
            ident = data.get('appId')
            if not isinstance(ident, str):
                raise ValueError('缺少应用 ID')
            lock = handler.server.try_app_operation(ident)
            if lock is None:
                handler.send_err(409, '应用已有其他操作正在执行')
                return
            try:
                app = api.find_app(cfg.snapshot(), ident)
                if app is None:
                    handler.send_err(404, '应用不存在')
                    return
                if path == '/api/ops/instance':
                    if type(data.get('enabled')) is not bool:
                        raise ValueError('请明确是否跟随应用重启')
                    rule = None
                    if data['enabled']:
                        members = api.managed_pids(app)
                        pid = (app.get('externalIdentity') or {}).get('pid') or api.legacy_managed_pid(app)
                        # A managed launch owns an anchor, but matching must describe the app itself.
                        if not pid and members:
                            expected_rule = app.get('instanceMatch') or {}
                            expected_exe = expected_rule.get('exe')
                            table = api._win_process_table()
                            candidates = [p for p in members if expected_exe and (
                                same_window_executable(table.get(p, {}).get('exe'), expected_exe) if expected_rule.get('windowClass')
                                else os.path.normcase(table.get(p, {}).get('exe') or '') == os.path.normcase(expected_exe))]
                            roots = [p for p in candidates if not any(
                                p in api._win_tree_of(other, table) for other in candidates if other != p)]
                            if len(roots) == 1:
                                pid = roots[0]
                        if app.get('kind') == 'service' and members:
                            table = api._win_process_table()
                            expected = service_identity(api, app.get('command'), app.get('cwd'))
                            candidates = []
                            for member in members:
                                row = table.get(member, {})
                                signature = service_identity(api, row.get('args'), api._win_cwd(member), row.get('exe'))
                                if signature and (expected is None or signature == expected):
                                    candidates.append((member, signature))
                            if candidates and all(signature == candidates[0][1] for _, signature in candidates):
                                pid = candidates[0][0]
                        if not pid or not api.app_running(app):
                            raise ValueError('请先从运行中关联此应用，再启用自动识别')
                        rule = capture_instance_match(api, app, pid)
                    cfg.update(lambda c: api.find_app(c, ident).update(instanceMatch=rule))
                    monitor.wake.set()
                    handler.send_json({'ok': True, 'instanceMatch': rule})
                elif path == '/api/ops/window/bind':
                    if 'window' not in data:
                        raise ValueError('缺少窗口选择；解除关联请明确传入 null')
                    binding = bind_window(api, ident, data['window'], app) if data.get('window') is not None else None
                    cfg.update(lambda c: api.find_app(c, ident).update(windowBinding=binding))
                    monitor.wake.set()
                    handler.send_json({'ok': True, 'windowBinding': binding})
                elif path == '/api/ops/window':
                    app, error = refresh_instance(api, cfg, app)
                    if error:
                        raise ValueError(error)
                    if app.get('kind', 'service') == 'service' and data.get('operation') == 'focus':
                        from service_web import focus_service
                        handler.send_json(focus_service(api, cfg, app))
                    else:
                        handler.send_json(operate_window(api, app, data.get('operation'), cfg))
                elif path.endswith('/force'):
                    if data.get('confirmed') is not True:
                        raise ValueError('请明确确认强制结束')
                    body, status = api.operate_app(cfg, app, 'stop', force=True)
                    handler.send_json(body, status)
                else:
                    if app.get('stopAction') and data.get('actionId') == app['stopAction']:
                        body, status = api.operate_app(cfg, app, 'stop')
                    else:
                        body = monitor.execute_action(app, data.get('actionId'))
                        status = 200 if body.get('ok') else 409
                    handler.send_json(body, status)
            finally:
                lock.release()
        else:
            handler.send_err(404, '接口不存在')
    except (ValueError, TypeError, KeyError) as exc:
        handler.send_err(400, str(exc))


def import_process(monitor, data):
    api, cfg = monitor.api, monitor.cfg
    if not api.IS_WIN:
        raise ValueError('运行进程导入仅在 Windows 可用')
    pid = data.get('pid')
    if type(pid) is not int or pid <= 0 or pid == api.SELF_PID:
        raise ValueError('进程 ID 无效')
    row = api._win_process_table(refresh=True).get(pid)
    if not row or not row.get('exe') or data.get('created') != row['identity'] or api.process_uid(pid) != api.SELF_UID:
        raise ValueError('进程已退出、身份变化或不属于当前用户，请重新发现')
    current_id = data.get('appId')
    fields, error = api.validate_app_fields(data, partial=bool(current_id))
    if error:
        raise ValueError(error)
    identity = dict(pid=pid, created=row['identity'], exe=row['exe'])
    replace_running = data.get('replaceRunning', False)
    if type(replace_running) is not bool:
        raise ValueError('replaceRunning 必须是布尔值')
    def save(c):
        selected_members = verify_instance_ownership(api, c, identity, current_id)
        app = api.find_app(c, current_id) if current_id else None
        if current_id and app is None:
            raise ValueError('卡片不存在')
        if app and api.app_running(app):
            current_members = set(api.managed_pids(app))
            if not replace_running or not current_members or not current_members.issubset(selected_members):
                raise ValueError('卡片已有运行实例；仅可明确改关联到包含原实例的宿主进程')
        if not app:
            app = copy.deepcopy(api.Config.APP_DEFAULT)
            app.update(id=secrets.token_hex(4), createdAt=int(time.time()))
            c['apps'].append(app)
        app.update(fields)
        validate_stop_action(app)
        reconcile_app_presets(c, app['id'])
        app.update(externalIdentity=identity, attached=True, lastPid=pid,
                   lastPgid=None, runToken=None, expectedRunning=True, startedAt=time.time())
        try:
            app['instanceMatch'] = capture_instance_match(api, app, pid)
        except ValueError:
            app['instanceMatch'] = None  # Keep one-instance import available when metadata is unreadable.
        return copy.deepcopy(app)
    lock = monitor.host.try_app_operation(current_id) if current_id else None
    if current_id and lock is None:
        raise ValueError('卡片已有其他操作正在执行')
    try:
        return cfg.update(save)
    finally:
        if lock:
            lock.release()
