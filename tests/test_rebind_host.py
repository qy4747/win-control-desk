"""Manual check, with fake process identities; never starts/stops applications."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from ops_api import import_process


class RebindHostTest(unittest.TestCase):
    def test_explicit_parent_rebind_preserves_running_tree(self):
        app = dict(id='old', name='AstrBot', actions=[], stopAction=None)
        data = {'apps': [app]}
        api = SimpleNamespace(IS_WIN=True, SELF_PID=1, SELF_UID=7,
            _win_process_table=lambda **kw: {20: dict(exe='desktop.exe', identity='created')},
            process_uid=lambda pid: 7, validate_app_fields=lambda *a, **kw: ({}, None),
            external_pids=lambda a: [20, 10], managed_pids=lambda a: [10],
            app_running=lambda a: True, find_app=lambda c, ident: app,
            # One registered card: there are no independent child-card boundaries.
            card_process_members=lambda a, members, apps: list(members))
        monitor = SimpleNamespace(api=api, cfg=SimpleNamespace(update=lambda fn: fn(data)),
            host=SimpleNamespace(try_app_operation=lambda ident: Mock()))
        request = dict(appId='old', pid=20, created='created')
        with self.assertRaises(ValueError):
            import_process(monitor, request)
        with patch('ops_api.capture_instance_match', return_value={}):
            saved = import_process(monitor, dict(request, replaceRunning=True))
        self.assertEqual(saved['externalIdentity']['pid'], 20)
        self.assertEqual(saved['id'], 'old')


if __name__ == '__main__':
    unittest.main()
