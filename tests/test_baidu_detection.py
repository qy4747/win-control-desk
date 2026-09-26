"""Offline check: python -m unittest discover -s tests -p test_baidu_detection.py"""
import copy
import unittest
from types import SimpleNamespace

import ops_entries as entries
import server


class BaiduDetectionTests(unittest.TestCase):
    def test_live_legacy_rule_upgrade_and_launch_variants(self):
        exe = 'C:/Users/example/Baidu/BaiduNetdisk.exe'
        command = '"' + exe + '"'
        row = dict(exe=exe, args='"' + exe.lower() + '" NoUpdate', identity='current', ppid=1)
        app = dict(id='baidu', kind='desktop', command=command,
                   instanceMatch=dict(exe=exe, argsHash='old'), externalIdentity={'pid': 10})
        data = {'apps': [copy.deepcopy(app)]}
        cfg = SimpleNamespace(snapshot=lambda: copy.deepcopy(data), update=lambda fn: fn(data))
        api = SimpleNamespace(IS_WIN=True, SELF_PID=99, SELF_UID='me',
            _simple_command_tokens=server._simple_command_tokens,
            _win_process_table=lambda: {10: row}, process_uid=lambda _: 'me',
            app_running=lambda _: True, managed_pids=lambda _: [10], find_app=server.find_app)
        updated, error = entries.refresh_instance(api, cfg, app)
        self.assertIsNone(error)
        rule = updated['instanceMatch']
        self.assertEqual(rule['argsHashVersion'], 3)
        self.assertFalse(entries.desktop_rule_upgrade_needed(updated))
        for args in (command, command + ' NoUpdate', row['args']):
            row['args'] = args
            self.assertEqual(entries.instance_candidates(api, rule), [10])
        row['args'] = command + ' --profile=other'
        self.assertEqual(entries.instance_candidates(api, rule), [])
        row['args'] = command + ' --type=renderer'
        self.assertEqual(entries.instance_candidates(api, rule), [])
        # Unassociated old hashes are never reinterpreted as the new version.
        api.app_running = lambda _: False
        api.app_identity_uncertain = lambda _: False
        _, error = entries.refresh_instance(api, cfg, app)
        self.assertIsNone(error)
        self.assertNotIn('argsHashVersion', app['instanceMatch'])


if __name__ == '__main__':
    unittest.main()
