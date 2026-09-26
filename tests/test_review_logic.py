"""Offline regression checks only; no real application operations. Run manually."""
import copy
import os
import shlex
import json
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import server
from ops_entries import service_identity, instance_candidates, verify_instance_ownership, refresh_instance
from ops_model import reconcile_app_presets, validate_presets
from ops_monitor import Monitor


class ReviewLogic(unittest.TestCase):
    def test_npx_old_entry_recovers_saved_remote_arguments_without_starting(self):
        api = SimpleNamespace(_simple_command_tokens=shlex.split,
            _resolve_command_path=lambda p, base: os.path.join(base, p))
        with tempfile.TemporaryDirectory() as root:
            package = os.path.join(root, 'node_modules', '@example', 'tool')
            os.makedirs(package)
            with open(os.path.join(package, 'package.json'), 'w', encoding='utf8') as file:
                json.dump(dict(name='@example/tool', bin={'tool': 'dist/index.js'}), file)
            entry = os.path.join(package, 'dist', 'index.js')
            identity = service_identity(api, 'npx --yes @example/tool@latest remote', root, entry_hint=entry)
            expected = service_identity(api, 'node ' + shlex.quote(entry) + ' remote', root)
            self.assertEqual(identity, expected)
            self.assertNotEqual(identity, service_identity(api, 'node ' + shlex.quote(entry), root))
            self.assertIsNone(service_identity(api, 'npx @example/other remote', root, entry_hint=entry))

    def test_missing_legacy_instance_does_not_block_start_but_unverified_match_does(self):
        cwd = os.path.abspath('sample')
        rows = {}
        api = SimpleNamespace(IS_WIN=True, SELF_UID=7, _simple_command_tokens=shlex.split,
            _resolve_command_path=lambda p, base: os.path.join(base, p), _win_process_table=lambda: rows,
            _win_cwd=lambda _: cwd, process_uid=lambda _: 7,
            app_running=lambda _: False, app_identity_uncertain=lambda _: False)
        signature = service_identity(api, 'node service.js --profile work', cwd)
        legacy = {k: v for k, v in signature.items() if k != 'argsHash'}
        app = dict(id='a', kind='service', command='wrapper.cmd', cwd=cwd, instanceMatch={'service': legacy})
        self.assertIsNone(refresh_instance(api, None, app)[1])
        rows[20] = dict(exe='node.exe', args='node service.js --profile other')
        self.assertIn('缺少参数身份', refresh_instance(api, None, app)[1])

    def test_service_profiles_do_not_rebind_even_before_listening(self):
        cwd = os.path.abspath('sample')
        row = dict(exe='node.exe', args='node.exe service.js --profile personal', identity='new', ppid=0)
        api = SimpleNamespace(SELF_PID=1, SELF_UID=7, _win_process_table=lambda: {20: row},
            process_uid=lambda _: 7, _win_cwd=lambda _: cwd, scan_listeners=lambda: [],
            _win_tree_of=lambda pid, table: [pid], _simple_command_tokens=shlex.split,
            _resolve_command_path=lambda p, base: os.path.join(base, p))
        work = service_identity(api, 'node.exe service.js --profile work', cwd)
        self.assertEqual(work, service_identity(api, 'node.exe service.js --profile=work', cwd))
        for port in (None, 8765):
            self.assertEqual(instance_candidates(api, dict(service=work, port=port)), [])
        row['args'] = 'node.exe service.js --profile work'
        self.assertEqual(instance_candidates(api, dict(service=work)), [20])

    def test_overlap_without_an_independent_boundary_is_rejected(self):
        api = SimpleNamespace(external_pids=lambda _: [200, 201], managed_pids=lambda _: [201],
            card_process_members=lambda app, members, apps: members)
        with self.assertRaisesRegex(ValueError, '其他卡片'):
            verify_instance_ownership(api, {'apps': [{'id': 'b', 'name': 'B'}]}, {}, 'a')

    def test_legacy_service_rule_learns_only_from_verified_running_tree(self):
        cwd = os.path.abspath('sample')
        row = dict(exe='node.exe', args='node.exe service.js --profile work', identity='old')
        api = SimpleNamespace(IS_WIN=True, _simple_command_tokens=shlex.split,
            _resolve_command_path=lambda p, base: os.path.join(base, p), _win_process_table=lambda: {10: row},
            _win_cwd=lambda _: cwd, managed_pids=lambda _: [10], app_running=lambda _: True,
            app_identity_uncertain=lambda _: False, find_app=server.find_app)
        expected = service_identity(api, row['args'], cwd)
        legacy = {k: v for k, v in expected.items() if k != 'argsHash'}
        data = {'apps': [dict(id='a', kind='service', instanceMatch={'service': legacy})]}
        cfg = SimpleNamespace(snapshot=lambda: copy.deepcopy(data), update=lambda fn: fn(data))
        updated, error = refresh_instance(api, cfg, copy.deepcopy(data['apps'][0]))
        self.assertIsNone(error)
        self.assertEqual(updated['instanceMatch']['service'], expected)

    def test_expired_confirmation_never_enters_operation(self):
        operation = Mock()
        with patch.object(server, 'IS_WIN', False), patch.object(server, 'run_cmd', return_value='new creation'):
            with self.assertRaisesRegex(ValueError, '变化'):
                with server.confirmed_process(200, 'old creation'):
                    operation()
        operation.assert_not_called()

    def test_removing_or_converting_last_member_keeps_valid_empty_package(self):
        pack = dict(id='pack', name='Pack', type='package', steps=[dict(appId='a', action='start')])
        scene = dict(id='scene', name='Scene', steps=[], packageSteps=[dict(packageId='pack', action='stop')])
        for apps in ([], [dict(id='a', kind='task')]):
            data = dict(apps=apps, rules=[], presets=copy.deepcopy([pack, scene]))
            reconcile_app_presets(data, 'a')
            self.assertEqual(data['presets'][0]['steps'], [])
            self.assertEqual(data['presets'][1]['packageSteps'][0]['packageId'], 'pack')
            validate_presets(data['presets'], apps, [])

    def test_only_scene_waits_for_an_existing_service_probe(self):
        app = dict(id='a', kind='service', running=True, probe={'url': 'http://localhost/health'})
        for kind, expected in (('scene', 'succeeded'), ('package', 'skipped')):
            api = SimpleNamespace(find_app=lambda *_: app, app_running=lambda _: True,
                app_identity_uncertain=lambda _: False, desktop_background_only=lambda _: False,
                operate_app=Mock())
            def lock(_):
                result = threading.Lock(); result.acquire(); return result
            monitor = SimpleNamespace(api=api, cfg=SimpleNamespace(snapshot=lambda: {}),
                host=SimpleNamespace(try_app_operation=lock), cancel=threading.Event(),
                stopped=threading.Event(), wake=threading.Event(),
                run={'steps': [dict(appId='a', action='start')]})
            with patch('ops_monitor.refresh_instance', return_value=(app, None)), patch('ops_monitor.http_action', return_value={'ok': True}) as probe:
                Monitor._preset_worker(monitor, dict(type=kind, timeoutSec=1))
            self.assertEqual(monitor.run['steps'][0]['status'], expected)
            self.assertEqual(probe.call_count, int(kind == 'scene'))
            api.operate_app.assert_not_called()


if __name__ == '__main__':
    unittest.main()
