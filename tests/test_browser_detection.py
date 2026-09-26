"""Offline check: python -m unittest discover -s tests -p test_browser_detection.py"""
import copy
import unittest
from types import SimpleNamespace
from unittest import mock

import ops_entries as entries
import server
import service_web


class BrowserDetectionTests(unittest.TestCase):
    def test_quark_brand_flag_migration_preserves_old_hashes(self):
        exe = 'C:/Quark/quark_cloud_drive.exe'
        command = '"' + exe + '"'
        digest = lambda args, version: entries.instance_args_hash(exe, args, server._simple_command_tokens, version)
        branded = command + ' --launch-from=startmenu --brand-clouddrive'
        self.assertEqual(digest(command, 4), digest(branded, 4))
        self.assertNotEqual(digest(command, 3), digest(branded, 3))
        self.assertNotEqual(digest(command, 4), digest(branded + ' --type=renderer', 4))

    def test_default_browser_follows_windows_not_initial_app_url(self):
        for name, app_id in (('chrome.exe', 'Chrome'), ('msedge.exe', 'MSEdge')):
            exe = 'C:/Browser/' + name
            app = dict(id='browser', kind='desktop', command='"' + exe + '"',
                       instanceMatch=dict(exe=exe, argsHash='old-startup-hash'))
            table = {10: dict(exe=exe, identity='now', args='"' + exe + '" --app=http://127.0.0.1:9600/', ppid=1)}
            window = dict(pid=10, hwnd=20, exe=exe, windowClass='Chrome_WidgetWin_1', toolWindow=False)
            api = SimpleNamespace(IS_WIN=True, SELF_PID=99, SELF_UID='me',
                _simple_command_tokens=server._simple_command_tokens,
                _win_process_table=lambda: table, process_uid=lambda _: 'me',
                app_running=lambda _: False, app_identity_uncertain=lambda _: False, find_app=server.find_app)
            rule = entries.browser_card_rule(api, app)
            self.assertTrue(rule['browserMain'])
            for changed in (dict(app, kind='service'), dict(app, command=app['command'] + ' --user-data-dir=C:/Separate'),
                            dict(app, command=app['command'] + ' --app=http://localhost/')):
                self.assertIsNone(entries.browser_card_rule(api, changed))
            with mock.patch.object(entries, 'list_windows', return_value=[window]), \
                 mock.patch.object(service_web, 'window_app_property', return_value=app_id) as prop:
                self.assertEqual(entries.instance_candidates(api, rule), [10])
                for suffix in ('.127.0.0.1_/', '._crx_installedapp'):
                    prop.return_value = app_id + suffix
                    self.assertEqual(entries.instance_candidates(api, rule), [])
                prop.return_value = app_id
                original = table[10]['args']
                for suffix in (' --type=renderer', ' --user-data-dir=C:/Separate', ' --user-data-dir C:/Separate'):
                    table[10]['args'] = original + suffix
                    self.assertEqual(entries.instance_candidates(api, rule), [])
                table[10]['args'] = original
                data = {'apps': [copy.deepcopy(app)]}
                cfg = SimpleNamespace(snapshot=lambda: copy.deepcopy(data), update=lambda fn: fn(data))
                with mock.patch.object(entries, 'verify_instance_ownership'):
                    updated, error = entries.refresh_instance(api, cfg, app)
                self.assertIsNone(error)
                self.assertEqual(updated['externalIdentity']['pid'], 10)
                self.assertTrue(updated['instanceMatch']['browserMain'])
                with mock.patch.object(server, 'IS_WIN', True):
                    self.assertFalse(server.desktop_background_only(app, [10]))
                    prop.return_value = app_id + '._crx_installedapp'
                    self.assertTrue(server.desktop_background_only(app, [10]))


if __name__ == '__main__':
    unittest.main()
