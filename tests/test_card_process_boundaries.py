"""Offline card ownership checks; never terminate real processes."""
import copy
import os
import shlex
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import server
from ops_entries import instance_candidates, service_identity, verify_instance_ownership


class CardProcessBoundaries(unittest.TestCase):
    def test_registered_child_is_independent_in_both_directions_and_stop_targets(self):
        rows = {
            100: dict(ppid=1, exe='astr.exe', identity='1000', created=1),
            110: dict(ppid=100, exe='backend.exe', identity='1100', created=2),
            200: dict(ppid=110, exe='python.exe', identity='2000', created=3),
            210: dict(ppid=200, exe='worker.exe', identity='2100', created=4),
        }
        parent = dict(id='astr', externalIdentity=dict(pid=100, created='1000', exe='astr.exe'))
        child = dict(id='comfy', externalIdentity=dict(pid=200, created='2000', exe='python.exe'))
        cfg = {'apps': [parent, child]}
        with patch.object(server, 'IS_WIN', True), patch.object(server, '_win_process_table', return_value=rows), \
                patch.object(server, 'process_uid', return_value=server.SELF_UID), \
                patch.object(server, '_PROCESS_CONFIG', SimpleNamespace(snapshot=lambda: copy.deepcopy(cfg))):
            self.assertEqual(server.managed_pids(parent), [100, 110])
            self.assertEqual(server.managed_pids(child), [200, 210])
            self.assertEqual(server.resolve_app_stop_target(parent)[0]['members'], [100, 110])
            self.assertEqual(server.resolve_app_stop_target(child)[0]['members'], [200, 210])
            self.assertEqual(verify_instance_ownership(server, cfg, child['externalIdentity'], 'comfy'), {200, 210})
            self.assertEqual(verify_instance_ownership(server, cfg, parent['externalIdentity'], 'astr'), {100, 110})
            with self.assertRaisesRegex(ValueError, '其他卡片'):
                verify_instance_ownership(server, cfg, child['externalIdentity'], 'duplicate')
            # Even before auto-rebinding, a known service entry reserves its branch.
            child.pop('externalIdentity')
            child['instanceMatch'] = {'service': {'runtime': 'python'}}
            with patch('ops_entries.instance_candidates', return_value=[200]):
                self.assertEqual(server.managed_pids(parent), [100, 110])
                self.assertEqual(verify_instance_ownership(server, cfg,
                    dict(pid=200, created='2000', exe='python.exe'), 'comfy'), {200, 210})

    def test_absolute_service_entry_ignores_launcher_cwd_but_keeps_arguments(self):
        project = os.path.abspath('workbench')
        entry = os.path.join(project, 'http_server.py').replace('\\', '/')
        command = 'pythonw.exe "' + entry + '" --host 127.0.0.1 --port 8765'
        rows = {200: dict(exe='pythonw.exe', args=command, identity='2000', ppid=1)}
        api = SimpleNamespace(SELF_PID=1, SELF_UID=7, _win_process_table=lambda: rows,
            process_uid=lambda _: 7, _win_cwd=lambda _: os.path.abspath('another-launcher'),
            scan_listeners=lambda: [(200, 8765)], _win_tree_of=lambda pid, _: [pid],
            _simple_command_tokens=shlex.split,
            _resolve_command_path=lambda path, cwd: path if os.path.isabs(path) else os.path.join(cwd, path))
        rule = dict(service=service_identity(api, command, project), port=8765)
        self.assertEqual(instance_candidates(api, rule), [200])
        rows[200]['args'] = command + ' --profile personal'
        self.assertEqual(instance_candidates(api, rule), [])

    def test_scoped_group_stop_does_not_use_tree_kill(self):
        target = dict(kind='group', id=100, members=[100, 110], scoped=True)
        with patch.object(server, 'IS_WIN', True), patch('win_metrics.close_windows', return_value=False), \
                patch.object(server, '_win_stop_process', return_value=(True, None)) as stop, \
                patch.object(server, 'stop_pid_tree') as tree:
            self.assertTrue(server.signal_app_stop(target)[0])
            self.assertEqual([call.args[0] for call in stop.call_args_list], [110, 100])
            self.assertTrue(all(call.kwargs['tree'] is False for call in stop.call_args_list))
            tree.assert_not_called()


if __name__ == '__main__':
    unittest.main()
