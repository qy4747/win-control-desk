"""Offline check: python -m unittest discover -s tests -p test_windows_app_update.py"""
import os
import unittest
from types import SimpleNamespace
from unittest import mock

import ops_entries as entries
import server


class WindowsAppUpdateTests(unittest.TestCase):
    def test_version_change_preserves_window_identity_and_guards(self):
        old = r'C:\Program Files\WindowsApps\OpenAI.Codex_26.915.4065.0_x64__publisher\app\ChatGPT.exe'
        new = old.replace('26.915.4065.0', '26.917.6896.0')
        rule = dict(exe=old, windowClass='Chrome_WidgetWin_1', toolWindow=False)
        window = dict(pid=20, hwnd=30, created='new', exe=new, title='ChatGPT',
                      windowClass=rule['windowClass'], toolWindow=False)
        table = {20: dict(exe=new, identity='new', ppid=1),
                 21: dict(exe=new, identity='helper', ppid=20)}
        api = SimpleNamespace(SELF_PID=99, SELF_UID='user', IS_WIN=True,
                              _win_process_table=lambda: table, process_uid=lambda _: 'user',
                              managed_pids=lambda _: [20, 21])
        app = dict(id='codex', kind='desktop', instanceMatch=rule,
                   windowBinding={'exe': old, 'match': dict(rule, scope='application', title='ChatGPT')})
        with mock.patch.dict(os.environ, {'ProgramFiles': r'C:\Program Files'}):
            self.assertTrue(entries.same_window_executable(old, new))
            for other in (new.replace('publisher', 'other'), new.replace('OpenAI.Codex', 'Other'),
                          new.replace('x64', 'arm64'), new.replace('app\\', 'helper\\'),
                          new.replace('C:\\Program Files', 'D:\\Copied'),
                          new.replace('WindowsApps', 'OtherApps')):
                self.assertFalse(entries.same_window_executable(old, other))
            self.assertFalse(entries.same_window_executable('C:/App/1/app.exe', 'C:/App/2/app.exe'))
            with mock.patch.object(entries, 'list_windows', return_value=[window]):
                self.assertEqual(entries.instance_candidates(api, rule), [20])
                self.assertEqual(entries.instance_candidates(api, dict(rule, toolWindow=True)), [])
                with mock.patch.object(entries, 'verify_window', side_effect=ValueError), \
                     mock.patch.object(entries, 'bind_window', return_value=window) as bind:
                    self.assertEqual(entries.resolve_window(api, app), window)
                    bind.assert_called_once_with(api, 'codex', window, app)
                # Two independent windows/processes remain ambiguous, never picked at random.
                table[22] = dict(exe=new, identity='second', ppid=1)
                with mock.patch.object(entries, 'list_windows', return_value=[window, dict(window, pid=22)]):
                    self.assertEqual(entries.instance_candidates(api, rule), [20, 22])
            with mock.patch.object(server, 'IS_WIN', True), \
                 mock.patch.object(server, '_win_process_table', return_value=table):
                self.assertFalse(server.desktop_background_only(app, [20], {20: [(30, 'ChatGPT')]}))
                self.assertTrue(server.desktop_background_only(app, [20], {99: [(31, 'Codex terminal')]}))


if __name__ == '__main__':
    unittest.main()
