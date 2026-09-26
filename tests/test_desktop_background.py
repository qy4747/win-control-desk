"""Run with python -m unittest discover -s tests -p test_desktop_background.py."""
import unittest
from unittest import mock
from types import SimpleNamespace

import server
import ops_entries


class DesktopBackgroundTests(unittest.TestCase):
    def test_window_card_rebinds_when_old_launcher_survives(self):
        app = dict(id='codex', kind='desktop', lastPid=10, runToken='old',
                   instanceMatch={'exe': 'ChatGPT.exe', 'windowClass': 'Chrome_WidgetWin_1'})
        data = {'apps': [app]}
        cfg = SimpleNamespace(snapshot=lambda: data, update=lambda fn: fn(data))
        api = SimpleNamespace(IS_WIN=True, app_running=lambda _: True,
            desktop_background_only=lambda _: True, find_app=server.find_app,
            _win_process_table=lambda: {20: dict(exe='ChatGPT.exe', identity='new')})
        with mock.patch.object(ops_entries, 'instance_candidates', return_value=[20]), \
             mock.patch.object(ops_entries, 'verify_instance_ownership') as verify:
            updated, error = ops_entries.refresh_instance(api, cfg, app)
        self.assertIsNone(error)
        self.assertEqual(updated['externalIdentity']['pid'], 20)
        self.assertIsNone(updated['runToken'])
        verify.assert_called_once()

    def test_codex_deck_counts_desktop_window_not_terminals(self):
        exe = 'C:/Program Files/WindowsApps/OpenAI.Codex_1/app/ChatGPT.exe'
        app = dict(kind='desktop', command='start "" /wait "Codex Deck.lnk"',
                   windowBinding={'exe': exe})
        table = {10: {'exe': exe}, 11: {'exe': 'C:/Windows/System32/cmd.exe'},
                 12: {'exe': 'C:/Codex/codex.exe'}}
        with mock.patch.object(server, 'IS_WIN', True), mock.patch.object(server, '_win_process_table', return_value=table):
            self.assertTrue(server.desktop_background_only(app, [10, 11, 12], {11: [(1, 'Codex Deck')], 12: [(2, 'Codex CLI')]}))
            self.assertFalse(server.desktop_background_only(app, [10, 11, 12], {10: [(3, 'Codex')]}))

    def test_only_owned_client_windows_count_as_open(self):
        for exe in ('msedge.exe',):
            app = dict(kind='desktop', command=exe)
            table = {10: {'exe': exe}, 11: {'exe': 'helper.exe'}}
            with mock.patch.object(server, 'IS_WIN', True), mock.patch.object(server, '_win_process_table', return_value=table):
                self.assertTrue(server.desktop_background_only(app, [10, 11], {}))
                self.assertTrue(server.desktop_background_only(app, [10, 11], {11: [(2, 'helper')], 99: [(3, 'other app')]}))
                # Minimized user windows are still visible to EnumWindows.
                self.assertFalse(server.desktop_background_only(app, [10, 11], {10: [(1, 'window')]}))
                self.assertFalse(server.desktop_background_only(app, [], {}))
                self.assertFalse(server.desktop_background_only(dict(app, kind='service'), [10], {}))
                self.assertFalse(server.desktop_background_only(dict(app, command='ToDesk.exe'), [10], {}))

    def test_reopening_preserves_existing_process_ownership(self):
        for exe, flag in (('msedge.exe', '--new-window'),):
            app = dict(id='a', kind='desktop', command=exe)
            cfg = mock.Mock()
            with mock.patch('ops_entries.refresh_instance', return_value=(app, None)), \
                 mock.patch.object(server, 'app_alive_sign', return_value=True), \
                 mock.patch.object(server, 'desktop_background_only', return_value=True), \
                 mock.patch.object(server, 'inspect_app_health', return_value={'blocking': False}), \
                 mock.patch.object(server, 'independent_windows_flags', return_value=0), \
                 mock.patch.object(server.subprocess, 'Popen') as launch, \
                 mock.patch.object(server.threading, 'Thread'), \
                 mock.patch.object(server, 'persist_started_app') as persist:
                result, status = server.operate_app(cfg, app, 'start')
                self.assertEqual(status, 200)
                self.assertTrue(result['reopened'])
                self.assertEqual(launch.call_args.args[0], [exe, flag])
                persist.assert_not_called()
                cfg.update.assert_not_called()


if __name__ == '__main__':
    unittest.main()
