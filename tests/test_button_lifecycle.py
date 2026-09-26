"""Manual regression check; uses mocks only, never controls real processes."""
import threading
import shlex
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ops_entries import instance_args_hash
from ops_monitor import Monitor


class ButtonLifecycleTest(unittest.TestCase):
    def test_desktop_launch_modes_are_not_instance_identity(self):
        for exe, option in [('StreamDeck.exe', '--runinbk'), ('Typeless.exe', '--system-startup-silent-launch'),
                            ('quark_cloud_drive.exe', '--launch-from=loginitem'), ('steam.exe', '-silent'),
                            ('ToDesk.exe', '--hide --localPort=35600')]:
            def digest(args):
                return instance_args_hash(exe, exe + ' ' + args, shlex.split, launch_modes=True)
            self.assertEqual(digest(''), digest(option))
            self.assertNotEqual(digest(''), digest(option + ' --profile personal'))
            self.assertNotEqual(digest(''), digest(option + ' --type renderer'))
        self.assertNotEqual(instance_args_hash('node.exe', 'node.exe app.js --runinbk', shlex.split, launch_modes=True),
                            instance_args_hash('node.exe', 'node.exe app.js', shlex.split, launch_modes=True))

    def test_todesk_ipc_port_is_not_identity_but_service_arguments_are(self):
        gui = '"ToDesk.exe" --show --localPort='
        self.assertEqual(instance_args_hash('ToDesk.exe', gui + '1000'),
                         instance_args_hash('ToDesk.exe', gui + '2000'))
        self.assertNotEqual(instance_args_hash('ToDesk.exe', gui + '1000'),
                            instance_args_hash('ToDesk.exe', '"ToDesk.exe" --runservice'))
        self.assertNotEqual(instance_args_hash('node.exe', '--localPort=1000'),
                            instance_args_hash('node.exe', '--localPort=2000'))

    def test_scene_refreshes_identity_and_stops_after_failed_close(self):
        old, current = {'id': 'one'}, {'id': 'one', 'running': True}
        api = SimpleNamespace(find_app=Mock(return_value=old), app_running=lambda a: a.get('running', False),
                              app_identity_uncertain=lambda a: False,
                              operate_app=Mock(return_value=({'ok': False, 'error': 'close failed'}, 409)),
                              clear_app_runtime=Mock())
        monitor = SimpleNamespace(api=api, cfg=SimpleNamespace(snapshot=lambda: {}),
            host=SimpleNamespace(try_app_operation=lambda ident: threading.Lock()),
            cancel=threading.Event(), stopped=threading.Event(), wake=threading.Event(),
            run={'steps': [{'appId': 'one', 'action': 'stop'}, {'appId': 'two', 'action': 'start'}]})
        lock = threading.Lock()
        lock.acquire()
        monitor.host.try_app_operation = lambda ident: lock
        with patch('ops_monitor.refresh_instance', return_value=(current, None)):
            Monitor._preset_worker(monitor, {})
        api.operate_app.assert_called_once_with(monitor.cfg, current, 'stop')
        api.clear_app_runtime.assert_not_called()
        self.assertEqual(monitor.run['status'], 'failed')
        self.assertEqual(monitor.run['steps'][1]['status'], 'skipped')


if __name__ == '__main__':
    unittest.main()
