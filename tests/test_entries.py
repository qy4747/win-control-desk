import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest import mock

import ops_entries as entries
from ops_model import validate_app_extra, validate_stop_action
from ops_monitor import Monitor
import server
import ops_api
import copy
import subprocess
import sys
import time


class EntryTests(unittest.TestCase):
    @unittest.skipUnless(server.IS_WIN, 'Windows process and HWND replacement')
    def test_native_process_restart_reconnects_window_without_controlling_personal_apps(self):
        child = '''import ctypes as C, json, os, sys
from ctypes import wintypes as W
from pathlib import Path
u=C.WinDLL('user32')
u.CreateWindowExW.argtypes=[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p]
u.CreateWindowExW.restype=W.HWND
h=u.CreateWindowExW(0x80,'STATIC','Cddeck restart fixture',0x90000000,-2000,-2000,20,20,None,None,None,None)
assert h
Path(sys.argv[1]).write_text(json.dumps(dict(pid=os.getpid(),hwnd=h)))
m=W.MSG()
while u.GetMessageW(C.byref(m),None,0,0)>0:
    u.TranslateMessage(C.byref(m)); u.DispatchMessageW(C.byref(m))
'''
        with tempfile.TemporaryDirectory() as td:
            ready = Path(td, 'ready.json')
            def launch():
                proc = subprocess.Popen([sys.executable, '-c', child, str(ready)], cwd=td,
                    creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                deadline = time.monotonic()+10
                while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
                    time.sleep(.05)
                if not ready.exists():
                    proc.terminate(); proc.wait(timeout=5)
                    self.fail('fixture window did not become ready')
                return proc
            proc = launch()
            try:
                cfg = server.Config(str(Path(td, 'config.json')))
                row = server._win_process_table(refresh=True)[proc.pid]
                app = dict(server.Config.APP_DEFAULT, id='restart-test', kind='desktop', name='fixture',
                    externalIdentity=dict(pid=proc.pid, created=row['identity'], exe=row['exe']))
                app['instanceMatch'] = entries.capture_instance_match(server, app, proc.pid)
                selected = next(w for w in entries.list_windows(server) if w['pid'] == proc.pid)
                app['windowBinding'] = entries.bind_window(server, app['id'], selected, app)
                cfg.update(lambda c: c['apps'].append(copy.deepcopy(app)))
                proc.terminate(); proc.wait(timeout=5); ready.unlink()
                proc = launch()
                server._win_process_table(refresh=True)
                updated, error = entries.refresh_instance(server, cfg, app)
                self.assertIsNone(error)
                self.assertEqual(updated['externalIdentity']['pid'], proc.pid)
                self.assertNotEqual(updated['externalIdentity']['created'], app['externalIdentity']['created'])
                bound = entries.resolve_window(server, updated)
                self.assertEqual(bound['pid'], proc.pid)
                self.assertNotEqual(bound['token'], app['windowBinding']['token'])
            finally:
                if proc.poll() is None: proc.terminate()
                proc.wait(timeout=5)

    def test_restart_matching_is_unique_owned_and_keeps_runtime_validation(self):
        rows = {10: dict(exe='app.exe', args='app.exe --profile work', identity='old', created=1, ppid=0)}
        api = types.SimpleNamespace(IS_WIN=True, SELF_PID=1, SELF_UID='mine',
            _win_process_table=lambda **kw: rows, _win_cwd=lambda pid: '/project',
            process_uid=lambda pid: 'other' if pid == 40 else 'mine', find_app=server.find_app,
            app_identity_uncertain=lambda app: False,
            # This fixture has only root identities; child boundaries have dedicated tests.
            card_process_members=lambda app, members, apps: list(members))
        app = dict(server.Config.APP_DEFAULT, id='eeee0001', name='sample', kind='desktop',
                   externalIdentity=dict(pid=10, created='old', exe='app.exe'))
        app['instanceMatch'] = entries.capture_instance_match(api, app, 10)
        self.assertNotIn('args', app['instanceMatch'])
        api.external_pids = lambda a: [a['externalIdentity']['pid']] if a.get('externalIdentity') and rows.get(a['externalIdentity']['pid'], {}).get('identity') == a['externalIdentity']['created'] else []
        api.managed_pids = api.external_pids
        api.app_running = lambda a: bool(api.external_pids(a))
        with tempfile.TemporaryDirectory() as td:
            cfg = server.Config(str(Path(td, 'config.json')))
            cfg.update(lambda c: c['apps'].append(copy.deepcopy(app)))
            rows.clear()
            rows[20] = dict(exe='app.exe', args='app.exe --profile work', identity='new', created=2, ppid=0)
            rows[21] = dict(rows[20], args='app.exe --type renderer', ppid=20)
            rows[30] = dict(rows[20], args='app.exe --profile other')
            rows[40] = dict(rows[20])  # foreign owner cannot become a candidate
            updated, error = entries.refresh_instance(api, cfg, app)
            self.assertIsNone(error)
            self.assertEqual(updated['externalIdentity']['pid'], 20)
            self.assertEqual(updated['externalIdentity']['created'], 'new')
            rows[20]['identity'] = 'reused'  # same PID also needs a new creation identity
            rows[50] = dict(rows[20], identity='second')
            unchanged, error = entries.refresh_instance(api, cfg, updated)
            self.assertIn('多个匹配', error)
            self.assertEqual(unchanged['externalIdentity']['created'], 'new')
            rows.pop(50)
            updated['instanceMatch']['cwd'] = '/different-project'
            self.assertEqual(entries.instance_candidates(api, updated['instanceMatch']), [])
            updated['instanceMatch']['cwd'] = '/project'
            cfg.update(lambda c: c['apps'].append(dict(app, id='other', externalIdentity=dict(pid=20, created='reused', exe='app.exe'))))
            _, error = entries.refresh_instance(api, cfg, updated)
            self.assertIn('设置已变化', error)
            updated = cfg.snapshot()['apps'][0]
            _, error = entries.refresh_instance(api, cfg, updated)
            self.assertIn('其他卡片', error)

    def test_window_replacement_uses_scope_and_rejects_ambiguous_terminals(self):
        row = dict(hwnd=123, pid=20, created='new', exe='app.exe', title='New document', windowClass='Main', toolWindow=False)
        rule = dict(exe='app.exe', windowClass='Main', toolWindow=False, scope='application', title='Old document')
        app = dict(id='test', windowBinding=dict(hwnd=99, pid=10, created='old', exe='app.exe', match=rule))
        api = types.SimpleNamespace(IS_WIN=True, managed_pids=lambda app: [20])
        with mock.patch.object(entries, 'list_windows', return_value=[row, dict(row, hwnd=124, toolWindow=True)]), mock.patch.object(entries, 'window_api') as native:
            native.return_value.SetPropW.return_value = True
            bound = entries.resolve_window(api, app)
            self.assertEqual(bound['hwnd'], 123)
            self.assertTrue(bound['token'])
        rule['scope'] = 'title'; rule['title'] = 'Terminal project'
        with mock.patch.object(entries, 'list_windows', return_value=[row]):
            with self.assertRaisesRegex(ValueError, '尚未找到'):
                entries.resolve_window(api, app)
        with mock.patch.object(entries, 'list_windows', return_value=[dict(row, title=rule['title']), dict(row, hwnd=125, title=rule['title'])]), mock.patch.object(entries, 'window_api') as native:
            with self.assertRaisesRegex(ValueError, '不唯一'):
                entries.resolve_window(api, app)
            native.assert_not_called()

    def test_desktop_window_identity_survives_changed_launch_arguments(self):
        for exe in ('C:/PixPin/PixPin.exe', 'C:/NetEase/cloudmusic.exe', 'C:/WindowsApps/OpenAI.Codex_1/app/ChatGPT.exe'):
            rows = {20: dict(exe=exe, args='new dynamic arguments', identity='new', ppid=0),
                    30: dict(exe=exe, args='renderer', identity='helper', ppid=20),
                    40: dict(exe=exe, args='other user', identity='foreign', ppid=0)}
            api = types.SimpleNamespace(IS_WIN=True, SELF_PID=1, SELF_UID='mine',
                _win_process_table=lambda **kw: rows, process_uid=lambda pid: 'other' if pid == 40 else 'mine')
            window = dict(exe=exe, windowClass='Main', toolWindow=False, scope='application')
            app = dict(kind='desktop', windowBinding={'match': window})
            rule = entries.capture_instance_match(api, app, 20)
            self.assertNotIn('argsHash', rule)
            windows = [dict(window, pid=20), dict(window, pid=40)]
            with mock.patch.object(entries, 'list_windows', return_value=windows):
                self.assertEqual(entries.instance_candidates(api, rule), [20])
                rows[21] = dict(rows[20], identity='second')
                windows.append(dict(window, pid=21))
                self.assertEqual(entries.instance_candidates(api, rule), [20, 21])

    def test_bambu_document_argument_is_not_application_identity(self):
        exe = 'C:/Bambu/bambu-studio.exe'
        row = dict(exe=exe, args='"' + exe + '" "C:/Models/model.stl"', identity='now', ppid=0)
        window = dict(exe=exe, windowClass='wxWindowNR', toolWindow=False, scope='application', pid=20)
        app = dict(kind='desktop', instanceMatch=dict(exe=exe, argsHash='old', argsHashVersion=2),
                   windowBinding={'match': window})
        api = types.SimpleNamespace(SELF_PID=1, SELF_UID='mine', _win_process_table=lambda: {20: row},
                                    process_uid=lambda _: 'mine')
        self.assertTrue(entries.desktop_rule_upgrade_needed(app))
        rule = entries.capture_instance_match(api, app, 20)
        self.assertNotIn('argsHash', rule)
        self.assertFalse(entries.desktop_rule_upgrade_needed(dict(app, instanceMatch=rule)))
        with mock.patch.object(entries, 'list_windows', return_value=[window]):
            row['args'] = '"' + exe + '" "C:/Models/different.3mf"'
            self.assertEqual(entries.instance_candidates(api, rule), [20])
        with mock.patch.object(entries, 'list_windows', return_value=[dict(window, windowClass='#32770')]):
            self.assertEqual(entries.instance_candidates(api, rule), [])

    def test_argument_spacing_keeps_identity_and_legacy_hashes_work(self):
        exe = 'C:/AutoHotkey/AutoHotkey64.exe'
        original = f'"{exe}"  "H:/scripts/media router.ahk"'
        rows = {20: dict(exe=exe, args=original, identity='new', ppid=0)}
        api = types.SimpleNamespace(SELF_PID=1, SELF_UID='mine',
            _win_process_table=lambda: rows, _win_cwd=lambda pid: 'H:/scripts',
            process_uid=lambda pid: 'mine', _simple_command_tokens=server._simple_command_tokens)
        rule = entries.capture_instance_match(api, {'kind': 'task'}, 20)
        legacy = dict(exe=exe, argsHash=entries.instance_args_hash(exe, original))
        self.assertEqual(entries.instance_candidates(api, legacy), [20])
        rows[20]['args'] = f'{exe} "H:/scripts/media router.ahk"'
        self.assertEqual(entries.instance_candidates(api, rule), [20])
        self.assertEqual(entries.instance_candidates(api, legacy), [])
        rows[20]['args'] = f'{exe} "H:/scripts/other.ahk"'
        self.assertEqual(entries.instance_candidates(api, rule), [])

    def test_tunnel_profile_identity_does_not_depend_on_launcher_directory(self):
        exe = os.path.abspath('tunnel-client.exe')
        directory = os.path.abspath('profiles')
        command = f'"{exe}" run --profile-dir "{directory}" --profile local-codex-bridge'
        rows = {20: dict(exe=exe, args=command, identity='new', ppid=0),
                30: dict(exe=exe, args=command.replace('local-codex-bridge', 'github-mcp'), identity='git', ppid=0)}
        api = types.SimpleNamespace(SELF_PID=1, SELF_UID='mine', _win_process_table=lambda: rows,
            process_uid=lambda pid: 'mine', _win_cwd=lambda pid: os.path.abspath('different-launcher'),
            _simple_command_tokens=server._simple_command_tokens, _resolve_command_path=server._resolve_command_path,
            _win_tree_of=server._win_tree_of)
        rule = entries.capture_instance_match(api, dict(kind='service'), 20)
        self.assertEqual(rule['service'], entries.service_identity(api, command, os.path.abspath('original-launcher'), exe))
        self.assertEqual(entries.instance_candidates(api, rule), [20])
        rows[20]['args'] = command.replace(f'"{directory}"', '"' + os.path.abspath('other-profiles') + '"')
        self.assertEqual(entries.instance_candidates(api, rule), [])

    def test_recapture_uses_app_root_inside_managed_anchor(self):
        app = dict(id='eeee0001', kind='desktop', instanceMatch={'exe': 'app.exe'})
        rows = {10: dict(exe='anchor.exe', ppid=0), 20: dict(exe='app.exe', ppid=10),
                21: dict(exe='app.exe', ppid=20)}
        cfg = mock.Mock()
        cfg.snapshot.return_value = {'apps': [app]}
        cfg.update.side_effect = lambda save: save({'apps': [app]})
        api = types.SimpleNamespace(find_app=server.find_app, managed_pids=lambda app: [10, 20, 21],
            legacy_managed_pid=lambda app: None, app_running=lambda app: True,
            _win_process_table=lambda: rows, _win_tree_of=lambda pid, table: {20: [20, 21], 21: [21]}[pid])
        monitor = types.SimpleNamespace(api=api, cfg=cfg, wake=threading.Event())
        handler = mock.Mock()
        handler.server.cfg = cfg
        cfg.monitor = monitor
        lock = threading.Lock(); lock.acquire()
        handler.server.try_app_operation.return_value = lock
        handler.read_json_body.return_value = ({'appId': app['id'], 'enabled': True}, None)
        with mock.patch.object(ops_api, 'capture_instance_match', return_value={'exe': 'app.exe'}) as capture:
            ops_api.post(handler, '/api/ops/instance')
            capture.assert_called_once_with(api, app, 20)
        handler.send_err.assert_not_called()
        self.assertFalse(lock.locked())

    def test_window_routes_preserve_process_ownership_and_require_explicit_unbind(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = server.Config(str(Path(td, 'config.json')))
            app = dict(server.Config.APP_DEFAULT, id='eeee0001', name='window only')
            cfg.update(lambda c: c['apps'].append(app))
            monitor = types.SimpleNamespace(api=server, cfg=cfg, wake=threading.Event())
            cfg.monitor = monitor
            handler = mock.Mock()
            handler.server.cfg = cfg
            def acquire(ident):
                lock = threading.Lock(); lock.acquire(); return lock
            handler.server.try_app_operation.side_effect = acquire
            handler.read_json_body.return_value = ({'appId': app['id']}, None)
            ops_api.post(handler, '/api/ops/window/bind')
            self.assertEqual(handler.send_err.call_args.args[0], 400)
            bound = dict(hwnd=123, pid=456, created='creation', exe='app.exe', title='terminal', token=789)
            handler.read_json_body.return_value = ({'appId': app['id'], 'window': bound}, None)
            with mock.patch.object(ops_api, 'bind_window', return_value=bound):
                ops_api.post(handler, '/api/ops/window/bind')
            saved = cfg.snapshot()['apps'][0]
            self.assertEqual(saved['windowBinding'], bound)
            self.assertIsNone(saved['externalIdentity']); self.assertIsNone(saved['lastPid'])
            handler.read_json_body.return_value = ({'appId': app['id'], 'window': None}, None)
            ops_api.post(handler, '/api/ops/window/bind')
            self.assertIsNone(cfg.snapshot()['apps'][0]['windowBinding'])

    def test_locations_roundtrip_migrate_and_validate(self):
        with tempfile.TemporaryDirectory() as td:
            action = dict(id='repo', name='仓库', type='location', path=td, mode='terminal')
            action = validate_app_extra({'actions': [action]})['actions'][0]
            self.assertEqual(action['when'], 'always')
            config = Path(td, 'config.json')
            old = dict(schemaVersion=4, apps=[dict(id='entry', name='entry', actions=[action], runToken='preserved')])
            config.write_text(json.dumps(old), encoding='utf8')
            cfg = server.Config(str(config))
            app = cfg.snapshot()['apps'][0]
            self.assertIsNone(app['windowBinding'])
            self.assertIsNone(app['instanceMatch'])
            self.assertEqual(app['actions'], [action])
            self.assertEqual(app['runToken'], 'preserved')
            self.assertEqual(json.loads(Path(str(config)+'.bak').read_text('utf8')), old)
            with self.assertRaises(ValueError):
                validate_stop_action(dict(app, stopAction='repo'))
            for updates in ({'path': 'relative'}, {'mode': 'shell'}, {'editor': 'relative.exe'}):
                with self.assertRaises(ValueError):
                    validate_app_extra({'actions': [dict(action, **updates)]})
            buttons = [dict(action='window:pin', name='', when='always', placement='menu')]
            self.assertEqual(validate_app_extra({'cardButtons': buttons})['cardButtons'], buttons)

    @unittest.skipUnless(server.IS_WIN, 'Windows launch arguments')
    def test_open_paths_are_arguments_and_never_managed_or_timed_out(self):
        with tempfile.TemporaryDirectory(prefix='位置 & 空格 ') as td:
            path = Path(td, '配置 & %PATH%.json'); path.write_text('{}', encoding='utf8')
            with mock.patch.object(entries.subprocess, 'Popen') as launch, mock.patch.object(entries.threading, 'Thread') as thread:
                for mode in ('explorer', 'terminal', 'editor'):
                    action = dict(id='config', name='配置', type='location', mode=mode, path=str(path), when='always')
                    m = object.__new__(Monitor)
                    m.api = mock.Mock(); m.api.app_running.side_effect = AssertionError('always must not depend on process state')
                    m.emit = mock.Mock()
                    result = m.execute_action(dict(id='app', name='app', actions=[action]), 'config')
                    self.assertTrue(result['ok'], result)
                    args, options = launch.call_args
                    self.assertEqual(options['cwd'], td)
                    self.assertFalse(options.get('shell'))
                    if mode != 'terminal': self.assertEqual(args[0][-1], str(path))
                    else: self.assertTrue(options['creationflags'] & entries.subprocess.CREATE_NEW_CONSOLE)
                    m.api.start_app.assert_not_called(); m.api.stop_pid_tree.assert_not_called()
                    launch.return_value.wait.assert_not_called()
                    self.assertEqual(thread.call_args.kwargs['target'], launch.return_value.wait)
                with self.assertRaisesRegex(ValueError, '位置不存在'):
                    entries.open_location(dict(path=str(path)+'missing', mode='explorer'))
                with self.assertRaisesRegex(ValueError, '指定.*编辑器'):
                    entries.open_location(dict(path=td, mode='editor'))

    def test_stale_or_foreign_window_is_rejected_before_native_control(self):
        row = dict(hwnd=123, pid=456, created='start', exe='app.exe', title='窗口')
        api = types.SimpleNamespace(IS_WIN=True)
        with mock.patch.object(entries, 'list_windows', return_value=[row]), mock.patch.object(entries, 'window_api') as native:
            for bad in (None, dict(row, pid=789), dict(row, created='stale'), dict(row, exe='other.exe'), dict(row, hwnd=True)):
                with self.assertRaises(ValueError): entries.bind_window(api, 'app', bad)
            native.assert_not_called()
            native.return_value.SetPropW.return_value = True
            bound = entries.bind_window(api, 'app', row)
            native.return_value.GetPropW.return_value = bound['token'] + 1
            with self.assertRaisesRegex(ValueError, '原窗口已失效'):
                entries.operate_window(api, dict(id='app', windowBinding=bound), 'focus')
            native.return_value.SetForegroundWindow.assert_not_called()
        with mock.patch('win_metrics.windows', return_value={456: [(123, '窗口')]}):
            api = types.SimpleNamespace(IS_WIN=True, SELF_PID=1, SELF_UID='mine',
                _win_process_table=lambda **kw: {456: dict(identity='start', exe='app.exe')}, process_uid=lambda pid: 'other')
            self.assertEqual(entries.list_windows(api), [])

    def test_focus_accepts_existing_foreground_but_reports_real_denial(self):
        row = dict(hwnd=123, pid=456, token=7)
        app = dict(id='app', windowBinding=row)
        with mock.patch.object(entries, 'resolve_window', return_value=row), \
             mock.patch.object(entries, 'verify_window', return_value=row), \
             mock.patch.object(entries, 'window_api') as native:
            user = native.return_value
            user.GetPropW.return_value = 7
            user.GetWindowThreadProcessId.side_effect = lambda hwnd, pid: setattr(pid._obj, 'value', 456) if pid is not None else 789
            user.AttachThreadInput.return_value = False
            user.IsIconic.return_value = False
            user.IsWindowVisible.return_value = True
            user.SetForegroundWindow.return_value = False
            user.GetForegroundWindow.return_value = 123
            self.assertTrue(entries.operate_window(None, app, 'focus')['ok'])
            user.SetForegroundWindow.assert_not_called()
            user.GetForegroundWindow.side_effect = [999, 123, 123]
            self.assertTrue(entries.operate_window(None, app, 'focus')['ok'])
            user.GetForegroundWindow.side_effect = None
            user.GetForegroundWindow.return_value = 999
            # Native success alone must not be reported as actual activation.
            user.SetForegroundWindow.return_value = True
            with mock.patch.object(entries.time, 'sleep'), self.assertRaisesRegex(ValueError, 'Windows 未允许'):
                entries.operate_window(None, app, 'focus')

    def test_tray_hidden_binding_is_verified_and_shown_before_activation(self):
        row = dict(hwnd=123, pid=456, created='start', exe='app.exe', token=7)
        api = types.SimpleNamespace(IS_WIN=True)
        with mock.patch.object(entries, 'list_windows', return_value=[row]) as listing:
            self.assertEqual(entries.verify_window(api, row), row)
            listing.assert_called_once_with(api, include_hidden=True)
        with mock.patch.object(entries, 'resolve_window', return_value=row), \
             mock.patch.object(entries, 'verify_window', return_value=row), \
             mock.patch.object(entries, 'window_api') as native:
            user = native.return_value
            user.GetPropW.return_value = 7
            user.GetWindowThreadProcessId.side_effect = lambda hwnd, pid: setattr(pid._obj, 'value', 456)
            user.IsIconic.return_value = False
            user.IsWindowVisible.return_value = False
            user.GetForegroundWindow.return_value = 999
            user.ShowWindowAsync.side_effect = lambda *args: setattr(user.IsWindowVisible, 'return_value', True)
            user.SetForegroundWindow.side_effect = lambda hwnd: setattr(user.GetForegroundWindow, 'return_value', hwnd)
            self.assertTrue(entries.operate_window(api, dict(id='app', windowBinding=row), 'focus')['ok'])
            user.ShowWindowAsync.assert_called_once_with(123, 5)

    def test_covered_window_attaches_both_threads_and_always_detaches(self):
        user = mock.Mock()
        user.GetForegroundWindow.return_value = 999
        user.GetWindowThreadProcessId.side_effect = lambda hwnd, _: {999: 789, 123: 987}[hwnd]
        user.AttachThreadInput.return_value = True
        user.SetForegroundWindow.side_effect = RuntimeError('denied')
        with mock.patch.object(entries.threading, 'get_native_id', return_value=456):
            with self.assertRaises(RuntimeError):
                entries.retry_foreground(user, 123)
        user.BringWindowToTop.assert_called_once_with(123)
        self.assertEqual(user.AttachThreadInput.call_args_list, [
            mock.call(456, 789, True), mock.call(456, 987, True),
            mock.call(456, 987, False), mock.call(456, 789, False)])

    def test_foreground_retry_detaches_on_success_failure_and_exception(self):
        user = mock.Mock()
        user.GetForegroundWindow.return_value = 999
        user.GetWindowThreadProcessId.return_value = 789
        with mock.patch.object(entries.threading, 'get_native_id', return_value=456):
            for outcome in (True, False, RuntimeError('native failure')):
                with self.subTest(outcome=outcome):
                    user.reset_mock()
                    user.AttachThreadInput.return_value = True
                    user.SetForegroundWindow.side_effect = outcome if isinstance(outcome, Exception) else None
                    user.SetForegroundWindow.return_value = outcome
                    if isinstance(outcome, Exception):
                        with self.assertRaises(RuntimeError): entries.retry_foreground(user, 123)
                    else:
                        self.assertEqual(entries.retry_foreground(user, 123), outcome)
                    self.assertEqual(user.AttachThreadInput.call_args_list,
                        [mock.call(456, 789, True), mock.call(456, 789, False)])
            user.reset_mock()
            user.AttachThreadInput.return_value = False
            self.assertFalse(entries.retry_foreground(user, 123))
            user.SetForegroundWindow.assert_not_called()

    @unittest.skipUnless(server.IS_WIN, 'Windows native window')
    def test_native_binding_and_destroyed_window_property(self):
        # Create only our own small test window; never change another application.
        user = entries.window_api()
        user.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p]
        user.CreateWindowExW.restype = W.HWND
        user.DestroyWindow.argtypes = [W.HWND]
        user.GetWindowLongPtrW.argtypes = [W.HWND, C.c_int]
        user.GetWindowLongPtrW.restype = C.c_ssize_t
        hwnd = user.CreateWindowExW(0x08000080, 'STATIC', 'Cddeck window test', 0x90000000, 0, 0, 20, 20, None, None, None, None)
        self.assertTrue(hwnd)
        api = types.SimpleNamespace(IS_WIN=True, SELF_PID=0, SELF_UID='test', process_uid=lambda pid: 'test',
            _win_process_table=lambda **kw: {os.getpid(): dict(identity='test-start', exe='test.exe')})
        try:
            selection = next(w for w in entries.list_windows(api) if w['hwnd'] == hwnd)
            bound = entries.bind_window(api, 'test', selection)
            app = dict(id='test', windowBinding=bound)
            for removed in ('pin', 'unpin', 'topmost'):
                with self.assertRaisesRegex(ValueError, '窗口操作无效'):
                    entries.operate_window(api, app, removed)
            with mock.patch.object(entries, 'window_api', wraps=entries.window_api) as native:
                user.DestroyWindow(hwnd)
                with self.assertRaises(ValueError): entries.operate_window(api, app, 'focus')
                native.assert_not_called()
        finally:
            user.DestroyWindow(hwnd)


if __name__ == '__main__':
    unittest.main()
