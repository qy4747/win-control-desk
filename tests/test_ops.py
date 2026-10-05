import copy
import json
import os
import tempfile
import time
import types
import unittest
from unittest import mock

import server
from ops_model import DEFAULT_RULES, local_url, http_action, validate_app_extra, validate_rules, validate_presets
from ops_monitor import Alerts, Monitor, directory_size


class Contracts(unittest.TestCase):
    def test_v2_to_v3_preserves_new_fields_and_blocks_old_writer(self):
        buttons = [dict(action='stop', name='关闭', placement='primary', when='running')]
        ignored = {'app:aaaaaaaa:cpu': {'incident': 'saved-incident'}}
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as td:
                path = os.path.join(td, 'config.json')
                original = dict(schemaVersion=2, apps=[dict(id='aaaaaaaa', runToken='token', lastPid=123)])
                if existing:
                    original['apps'][0]['cardButtons'] = buttons
                    original['ignoredAlerts'] = ignored
                with open(path, 'w', encoding='utf8') as f:
                    json.dump(original, f)
                cfg = server.Config(path)
                migrated = cfg.snapshot()
                self.assertEqual(migrated['schemaVersion'], server.CURRENT_SCHEMA_VERSION)
                self.assertEqual(migrated['apps'][0]['cardButtons'], buttons if existing else None)
                self.assertEqual(migrated['ignoredAlerts'], ignored if existing else {})
                self.assertEqual(migrated['apps'][0]['runToken'], 'token')
                self.assertEqual(migrated['apps'][0]['lastPid'], 123)
                with open(path+'.bak', encoding='utf8') as f:
                    self.assertEqual(json.load(f), original)
                self.assertIsNone(server.Config(path).health_info()['migratedFromSchema'])
                with mock.patch.object(server, 'CURRENT_SCHEMA_VERSION', 2):
                    old = server.Config(path)
                    self.assertFalse(old.health_info()['writable'])
                    with self.assertRaises(OSError):
                        old.update(lambda c: c.update(ignoredAlerts={}))
                with open(path, encoding='utf8') as f:
                    self.assertEqual(json.load(f), migrated)
                with open(path+'.bak', encoding='utf8') as f:
                    self.assertEqual(json.load(f), original)

    def test_card_buttons_roundtrip_and_validation(self):
        buttons = [dict(action='stop', name='关闭', placement='primary', when='running'),
                   dict(action='custom:reload', name='重载', placement='menu', when='always')]
        with tempfile.TemporaryDirectory() as td:
            cfg = server.Config(os.path.join(td, 'config.json'))
            app = dict(server.Config.APP_DEFAULT, id='aaaaaaaa', name='sample')
            app.update(validate_app_extra({'cardButtons': buttons}))
            cfg.update(lambda c: c['apps'].append(app))
            self.assertEqual(server.Config(os.path.join(td, 'config.json')).snapshot()['apps'][0]['cardButtons'], buttons)
        for bad in [[dict(action='force')], [dict(action='stop', placement='wrong')],
                    [dict(action='start', placement='primary'), dict(action='stop', placement='primary')]]:
            with self.assertRaises(ValueError):
                validate_app_extra({'cardButtons': bad})

    def test_migration_keeps_runtime_and_backup(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'config.json')
            original = {'schemaVersion': 1, 'apps': [{'id': 'aaaaaaaa', 'name': 'old', 'command': 'echo ok',
                         'kind': 'service', 'runToken': 'secret', 'lastPid': 123}], 'watchedKeywords': ['old']}
            with open(path, 'w', encoding='utf8') as f:
                json.dump(original, f)
            cfg = server.Config(path)
            self.assertEqual(cfg.snapshot()['apps'][0]['runToken'], 'secret')
            self.assertTrue(cfg.snapshot()['apps'][0]['expectedRunning'])
            self.assertEqual(cfg.snapshot()['rules'], DEFAULT_RULES)
            with open(path+'.bak', encoding='utf8') as f:
                self.assertEqual(json.load(f), original)

    def test_loopback_and_header_boundary(self):
        self.assertEqual(local_url('http://localhost:8000/a'), 'http://127.0.0.1:8000/a')
        for url in ['https://example.com', 'http://127.0.0.1.evil.test', 'file:///C:/secret', 'http://user:pass@127.0.0.1', 'http://10.0.0.1']:
            with self.assertRaises(ValueError):
                local_url(url)
        with self.assertRaises(ValueError):
            validate_app_extra({'probe': {'url': 'http://127.0.0.1', 'headers': {'X-Auth': 'x\r\nHost: evil'}}})

    def test_invalid_rules_and_presets_are_rejected(self):
        for threshold in [float('nan'), float('inf'), True, -1]:
            with self.assertRaises(ValueError):
                validate_rules([dict(DEFAULT_RULES[0], threshold=threshold)])
        with self.assertRaises(ValueError):
            validate_presets([dict(id='x', name='x', steps=[dict(appId='missing', action='stop')])], [], DEFAULT_RULES)
        with self.assertRaises(ValueError):
            validate_app_extra({'actions': [{'id': '../evil', 'name': 'bad', 'type': 'command', 'command': 'echo ok'}]})

    def test_observation_and_desktop_type(self):
        fields, error = server.validate_app_fields({'name': 'desktop', 'command': '', 'kind': 'desktop'}, False)
        self.assertIsNone(error)
        self.assertEqual(fields['kind'], 'desktop')
        self.assertTrue(server.inspect_app_health(fields)['blocking'])

    def test_noop_config_update_does_not_rewrite_files_after_exit(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = server.Config(os.path.join(td, 'config.json'))
            with mock.patch.object(cfg, '_write_atomic') as write:
                cfg.update(lambda c: None)
                write.assert_not_called()


class AlertTests(unittest.TestCase):
    def test_ignore_only_current_incident_and_silence_recovery(self):
        events = []
        alerts = Alerts(events.append)
        rule = dict(name='disk')
        alerts.check('disk', True, 5, rule, 0)
        incident = alerts.active()[0]['incident']
        alerts.ignore('disk', incident)
        alerts = Alerts(events.append, json.loads(json.dumps(alerts.ignored())))
        self.assertTrue(alerts.active()[0]['ignored'])
        alerts.check('disk', None, None, rule, 1)
        self.assertTrue(alerts.active()[0]['ignored'])
        alerts.check('disk', True, 4, rule, 2)
        self.assertEqual(len(events), 1)
        alerts.check('disk', False, 30, rule, 3)
        self.assertFalse(alerts.ignored())
        self.assertEqual(len(events), 1)  # A restored ignored incident also stays quiet on recovery.
        alerts.check('disk', True, 3, rule, 4)
        self.assertFalse(alerts.active()[0]['ignored'])
        self.assertNotEqual(alerts.active()[0]['incident'], incident)
        self.assertFalse(events[-1]['muted'])
        with self.assertRaises(ValueError):
            alerts.ignore('disk', incident)

    def test_duration_unknown_dedup_recovery_and_mute(self):
        events = []
        a = Alerts(events.append)
        rule = dict(name='cpu', durationSec=60, muted=True)
        a.check('cpu', True, 95, rule, 0)
        a.check('cpu', True, 95, rule, 59)
        self.assertFalse(events)
        a.check('cpu', None, None, rule, 60)
        a.check('cpu', True, 95, rule, 70)
        a.check('cpu', True, 95, rule, 130)
        a.check('cpu', True, 95, rule, 140)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]['muted'])
        a.check('cpu', False, 20, rule, 150, recover=2)
        self.assertEqual(len(events), 1)
        a.check('cpu', False, 20, rule, 160, recover=2)
        self.assertEqual(events[-1]['phase'], 'recovered')

    def monitor(self):
        m = Monitor.__new__(Monitor)
        m.events = []
        m.alerts = Alerts(m.events.append)
        m.previous_config, m.exit_baseline, m.probes = {}, {}, {}
        m.initial = False
        return m

    def app(self, kind='service'):
        return dict(id='a', name='sample', kind=kind, running=True, expectedRunning=True,
                    startedAt=time.time()-100, port=8000, listening=True, canStart=True,
                    health={'blocking': False}, resources={'cpu': 1, 'memoryBytes': 100}, alertPolicy={})

    def test_exit_policy_manual_stop_desktop_and_task(self):
        m = self.monitor()
        service = self.app()
        m.check_apps([service], 0, True)
        service['running'] = False
        m.check_apps([service], 10, True)
        self.assertEqual(m.events[-1]['key'], 'app:a:exit')
        service['expectedRunning'] = False
        m.check_apps([service], 20, True)
        self.assertEqual(m.events[-1]['phase'], 'recovered')
        m = self.monitor()
        desktop = self.app('desktop'); desktop.update(running=False)
        m.check_apps([desktop], 0, True)
        self.assertFalse(m.events)
        task = self.app('task'); task.update(running=False, lastExit={'code': 130, 'at': 123})
        m.check_apps([task], 0, True)
        self.assertFalse(m.events)
        task['lastExit'] = {'code': 1, 'at': 124}
        m.check_apps([task], 1, True)
        self.assertEqual(m.events[-1]['phase'], 'alert')

    def test_port_debounce_stopped_and_unknown(self):
        m, app = self.monitor(), self.app()
        app['listening'] = False
        for t in [0, 10]:
            m.check_apps([app], t, True)
        self.assertFalse(m.events)
        m.check_apps([app], 20, True)
        self.assertEqual(m.events[-1]['key'], 'app:a:port')
        app['listening'] = True
        m.check_apps([app], 30, False)
        self.assertEqual(len(m.events), 1)
        m.check_apps([app], 40, True)
        m.check_apps([app], 50, True)
        self.assertEqual(m.events[-1]['phase'], 'recovered')

    def test_manual_stop_pauses_alerts_until_success_or_failure_is_known(self):
        for success in (True, False):
            with self.subTest(success=success):
                m, app = self.monitor(), self.app()
                m.check_apps([app], 0, True)
                app.update(lifecycleChanging=True, listening=False)
                for now in (1, 2, 3, 4):
                    m.check_apps([app], now, True)
                app.update(running=False, lastExit={'code': 1, 'at': 5})
                m.check_apps([app], 5, True)
                self.assertFalse(m.events)
                app.update(lifecycleChanging=False, expectedRunning=not success)
                if success:
                    app['lastExit'] = {'status': 'stopped', 'code': 1, 'at': 5}
                m.check_apps([app], 6, True)
                if success:
                    self.assertFalse(m.events)
                else:
                    self.assertEqual(m.events[-1]['key'], 'app:a:exit')
                    self.assertEqual(m.events[-1]['phase'], 'alert')

    def test_initial_config_failure_is_silent_but_later_failure_alerts(self):
        m, app = self.monitor(), self.app()
        app['health']['blocking'] = True
        m.check_apps([app], 0, True)
        self.assertFalse(m.events)
        app['health']['blocking'] = False
        m.check_apps([app], 1, True)
        self.assertFalse(m.events)
        app['health']['blocking'] = True
        m.check_apps([app], 2, True)
        self.assertEqual(m.events[-1]['key'], 'app:a:config')

    def test_http_samples_count_once(self):
        m, app = self.monitor(), self.app()
        app['probe'] = {'url': 'http://127.0.0.1:1'}
        app['pid'] = 100
        signature = json.dumps(app['probe'], sort_keys=True)+str(app['startedAt'])+'100'
        for timestamp in [1, 1, 1, 2]:
            m.probes['a'] = dict(ok=False, checkedAt=timestamp, signature=signature)
            m.check_apps([app], timestamp, True)
        self.assertFalse(m.events)
        m.probes['a']['checkedAt'] = 3
        m.check_apps([app], 3, True)
        self.assertEqual(m.events[-1]['key'], 'app:a:http')


class IdentityTests(unittest.TestCase):
    @unittest.skipUnless(server.IS_WIN, 'Windows only')
    def test_pid_reuse_and_parent_reuse_never_adopt(self):
        identity = dict(pid=42, created='100', exe='C:\\app.exe')
        table = {42: dict(identity='101', exe='C:\\app.exe', created=100, ppid=1)}
        with mock.patch.object(server, '_win_process_table', return_value=table), mock.patch.object(server, 'process_uid', return_value=server.SELF_UID):
            self.assertEqual(server.external_pids({'externalIdentity': identity}), [])
        table = {42: dict(created=100, ppid=1), 43: dict(created=90, ppid=42), 44: dict(created=110, ppid=43)}
        self.assertEqual(server._win_tree_of(42, table), [42])

    @unittest.skipUnless(server.IS_WIN, 'Windows only')
    def test_normal_stop_never_escalates(self):
        with mock.patch.object(server, '_win_taskkill', return_value=(False, 'no window')) as kill, mock.patch.object(server, 'pid_alive', return_value=True):
            self.assertFalse(server._win_stop_process(123)[0])
            kill.assert_called_once_with(123, tree=True, force=False)

    def test_directory_timeout_does_not_publish_partial_size(self):
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, 'file'), 'wb') as f:
                f.write(b'abc')
            self.assertEqual(directory_size(td)['bytes'], 3)
            self.assertEqual(directory_size(td, budget=-1), {'status': 'incomplete', 'bytes': None})

    @unittest.skipUnless(server.IS_WIN, 'Windows only')
    def test_force_checks_creation_time_on_the_open_handle(self):
        import win_metrics
        api = mock.Mock()
        api.OpenProcess.return_value = 123
        def times(handle, created, *others):
            created._obj.value = 200
            return 1
        api.GetProcessTimes.side_effect = times
        with mock.patch.object(win_metrics.C, 'WinDLL', return_value=api):
            self.assertEqual(win_metrics.terminate_verified({42: '100'}), [42])
        api.TerminateProcess.assert_not_called()
        api.CloseHandle.assert_called_once_with(123)


class SnapshotTests(unittest.TestCase):
    def test_resources_are_deduplicated_and_unknown_does_not_mean_zero(self):
        import threading
        m = Monitor.__new__(Monitor)
        app = dict(id='a', running=True, pids=[11, 11, 12], kind='service')
        m.cfg = types.SimpleNamespace(snapshot=lambda: {'apps': [app]}, health_info=lambda: {})
        m.host = types.SimpleNamespace(console_port=9600)
        m.api = types.SimpleNamespace(IS_WIN=True, find_app=lambda c, ident: app,
            _simple_command_tokens=server._simple_command_tokens,
            MANUAL_STOP_LOCK=threading.RLock(), MANUAL_STOP_TOKENS=set(),
            build_state=lambda *args: {'apps': [app]}, _NATIVE_METRICS=types.SimpleNamespace(system={}),
            _win_process_table=lambda: {11: {'cpu': 1, 'ws': 10, 'ioWriteBytes': 20}, 12: {'cpu': None, 'ws': 30, 'ioWriteBytes': 40}})
        m.async_checks = m.check_apps = m.check_system = lambda *args: None
        m.directories, m.state = {}, {}
        m.directory_snapshots, m.snapshot_job = {}, None
        m.alerts = Alerts(lambda e: None)
        m.lock = threading.Lock()
        m.collect()
        self.assertEqual(app['resources'], {'cpu': None, 'memoryBytes': 40, 'gpuMemoryBytes': None, 'ioWriteBytes': 60})

    def test_requests_only_read_shared_snapshot(self):
        monitor = mock.Mock()
        cfg = types.SimpleNamespace(monitor=monitor)
        monitor.snapshot.return_value = {'apps': []}
        with mock.patch.object(server, 'build_state') as build:
            for _ in range(4):
                self.assertEqual(server.get_state_snapshot(cfg, 9600), {'apps': []})
            build.assert_not_called()

    def test_package_failure_continues_and_untargeted_app_is_untouched(self):
        import threading
        m = Monitor.__new__(Monitor)
        m.run = dict(status='running', steps=[dict(appId='a', action='stop'), dict(appId='b', action='start')])
        m.cancel, m.stopped, m.wake = threading.Event(), threading.Event(), threading.Event()
        apps = [{'id': 'a', 'running': True}, {'id': 'b', 'running': False}, {'id': 'c', 'running': True}]
        m.cfg = types.SimpleNamespace(snapshot=lambda: {'apps': apps})
        def acquire(_):
            lock = threading.Lock()
            lock.acquire()
            return lock
        m.host = types.SimpleNamespace(try_app_operation=acquire)
        calls = []
        def operate(cfg, app, action):
            calls.append((app['id'], action))
            if app['id'] == 'a':
                return {'ok': False, 'error': 'refused'}, 409
            app['running'] = True
            return {'ok': True}, 200
        m.api = types.SimpleNamespace(find_app=lambda cfg, ident: next(a for a in cfg['apps'] if a['id'] == ident),
                                     IS_WIN=False, app_identity_uncertain=lambda a: False,
                                     desktop_background_only=lambda a: False,
                                     app_running=lambda a: a['running'], operate_app=operate)
        # Packages contain independent operations; scenes stop on first failure.
        m._preset_worker({'type': 'package', 'timeoutSec': 1})
        self.assertEqual(calls, [('a', 'stop'), ('b', 'start')])
        self.assertEqual([s['status'] for s in m.run['steps']], ['failed', 'succeeded'])
        self.assertTrue(apps[2]['running'])

    def test_task_preset_does_not_accept_old_success_and_cancel_stops_future_steps(self):
        import threading
        m = Monitor.__new__(Monitor)
        m.run = dict(status='running', steps=[dict(appId='a', action='start'), dict(appId='b', action='start')])
        m.cancel, m.stopped, m.wake = threading.Event(), threading.Event(), threading.Event()
        apps = [dict(id='a', kind='task', startedAt=100, lastExit={'startedAt': 1000, 'status': 'succeeded'}), {'id':'b'}]
        m.cfg = types.SimpleNamespace(snapshot=lambda: {'apps': apps})
        def acquire(_):
            lock = threading.Lock(); lock.acquire(); return lock
        m.host = types.SimpleNamespace(try_app_operation=acquire)
        calls = []
        def operate(cfg, app, action):
            calls.append(app['id']); return {'ok':True}, 200
        m.api = types.SimpleNamespace(find_app=lambda c, ident: next(a for a in apps if a['id']==ident),
            IS_WIN=False, app_identity_uncertain=lambda a: False,
            desktop_background_only=lambda a: False,
            app_running=lambda a: False, operate_app=operate, public_last_exit=lambda a: a.get('lastExit'))
        with mock.patch.object(m.cancel, 'wait', side_effect=lambda _: m.cancel.set()):
            m._preset_worker({'timeoutSec':1})
        self.assertEqual(calls, ['a'])
        self.assertEqual(m.run['status'], 'canceled')


@unittest.skipUnless(server.IS_WIN, 'Windows integration')
class WindowsOpsIntegration(unittest.TestCase):
    def test_external_identity_actions_graceful_restart_and_shared_snapshot(self):
        import subprocess
        import sys
        from test_hardening import HttpHarness
        from pathlib import Path
        h = HttpHarness()
        monitor = None
        children = []
        watchers = []
        original_watch = server.watch_app_exit
        def track_watch(cfg, app_id, proc, token, started_at=None):
            thread = original_watch(cfg, app_id, proc, token, started_at)
            watchers.append((proc, thread))
            return thread
        watcher_patch = mock.patch.object(server, 'watch_app_exit', side_effect=track_watch)
        watcher_patch.start()
        self.addCleanup(watcher_patch.stop)
        fixture = Path(h.tmp.name, 'fixture.py')
        fixture.write_text('''import sys, threading, json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
 def log_message(self, *args): pass
 def do_GET(self): self.send_response(200); self.end_headers()
 def do_POST(self):
  self.send_response(200); self.end_headers()
  if self.path == '/stop': threading.Thread(target=self.server.shutdown).start()
s=ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), Handler)
p=Path(sys.argv[2]+'.tmp'); p.write_text(str(s.server_port)); p.replace(sys.argv[2])
s.serve_forever(); s.server_close()
''', encoding='utf8')
        try:
            with mock.patch.object(server, 'LOGS_DIR', h.tmp.name):
                monitor = Monitor(h.httpd, server, notifications=False)
                ports = []
                for i in range(2):
                    ready = Path(h.tmp.name, 'ready'+str(i))
                    child = subprocess.Popen([sys.executable, str(fixture), '0', str(ready)], creationflags=0x08000000)
                    children.append(child)
                    deadline = time.monotonic()+5
                    while not ready.exists() and time.monotonic() < deadline: time.sleep(.02)
                    ports.append(int(ready.read_text()))
                monitor.collect()
                _, _, headers = h.request('GET', '/api/state')
                headers = {'Content-Type':'application/json', 'Origin':'http://127.0.0.1:'+str(h.port),
                           'Sec-Fetch-Site':'same-origin', 'Cookie':headers['Set-Cookie'].split(';')[0]}
                def request(path, body):
                    return h.request('POST', path, json.dumps(body), headers)[:2]
                row = server._win_process_table(refresh=True)[children[0].pid]
                action = dict(id='quit', name='quit', type='http', url='http://127.0.0.1:'+str(ports[0])+'/stop', method='POST')
                command = subprocess.list2cmdline([sys.executable, str(fixture), str(ports[0]), str(Path(h.tmp.name, 'restarted'))])
                payload = dict(pid=children[0].pid, created=row['identity'], name='fixture', kind='service',
                               command=command, shell='cmd', cwd=h.tmp.name, port=ports[0],
                               actions=[action, dict(id='echo',name='echo',type='command',command='echo action-ok',shell='cmd')], stopAction='quit',
                               probe=dict(url='http://127.0.0.1:'+str(ports[0])))
                code, app = request('/api/ops/discover/import', dict(payload, created='stale'))
                self.assertEqual(code, 400)
                code, app = request('/api/ops/discover/import', payload)
                self.assertEqual(code, 200, app)
                # Windows may create a console host beneath this Python instance.
                self.assertIn(children[0].pid, server.managed_pids(app))
                self.assertNotIn(children[1].pid, server.managed_pids(app))
                self.assertNotIn(os.getpid(), server.managed_pids(app))
                monitor.collect()
                with mock.patch.object(server, 'build_state') as build:
                    for _ in range(3): self.assertEqual(h.request('GET', '/api/state')[0], 200)
                    build.assert_not_called()
                self.assertTrue(request('/api/ops/action', dict(appId=app['id'], actionId='echo'))[1]['ok'])
                self.assertEqual(h.request('POST','/api/ops/force',json.dumps({'appId':app['id'],'confirmed':True}),
                    dict(headers, Cookie='console_session=expired', Origin='https://example.invalid', **{'Sec-Fetch-Site':'cross-site'}))[0],403)
                self.assertEqual(request('/api/ops/force', {'appId':app['id']})[0],400)
                self.assertTrue(request('/api/apps/'+app['id']+'/restart', {})[1]['ok'])
                self.assertIsNotNone(children[0].poll())
                self.assertIsNone(children[1].poll())
                # Start acknowledges the process; the HTTP endpoint may still be warming up.
                deadline = time.monotonic()+5
                while time.monotonic() < deadline:
                    try:
                        if http_action(payload['probe'])['ok']: break
                    except OSError: pass
                    time.sleep(.05)
                else: self.fail('Restarted fixture did not become HTTP-ready')
                stopped = request('/api/apps/'+app['id']+'/stop', {})
                self.assertTrue(stopped[1]['ok'], stopped)
                self.assertFalse(server.find_app(h.cfg.snapshot(), app['id'])['expectedRunning'])
                self.assertIsNone(children[1].poll())
                _, task = request('/api/apps', dict(name='force fixture', kind='task', shell='cmd',
                    command=subprocess.list2cmdline([sys.executable, '-c', 'import time; time.sleep(60)'])))
                self.assertTrue(request('/api/apps/'+task['id']+'/start', {})[1]['ok'])
                self.assertTrue(request('/api/ops/force', dict(appId=task['id'], confirmed=True))[1]['ok'])
                self.assertIsNone(children[1].poll())
                self.assertEqual(server.find_app(h.cfg.snapshot(), task['id'])['lastExit']['status'], 'stopped')
                self.assertTrue(request('/api/apps/'+app['id']+'/start', {})[1]['ok'])
                monitor.close()
                h.httpd.shutdown()
                self.assertTrue(server.app_running(server.find_app(h.cfg.snapshot(), app['id'])))
        finally:
            # All cleanup targets were created by this test; never other Python processes.
            for app in h.cfg.snapshot()['apps']:
                if server.app_running(app): server.operate_app(h.cfg, app, 'stop', force=True)
            if monitor:
                monitor.close(); monitor.pool.shutdown(wait=True)
            for child in children:
                if child.poll() is None: child.terminate()
                child.wait(timeout=5)
            # Await the fixture's own launchers and completion writers before
            # removing their logs; Windows keeps inherited log handles locked.
            for proc, thread in watchers:
                proc.wait(timeout=5)
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive(), 'fixture exit writer did not stop')
            h.close()


if __name__ == '__main__':
    unittest.main()
