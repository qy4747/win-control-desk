"""Offline package contracts; no real app is started or stopped."""
import unittest
from unittest import mock
import types
import threading

from ops_model import validate_presets, preset_steps
from ops_monitor import Monitor


class PackageContracts(unittest.TestCase):
    def test_package_scene_expansion_and_scene_baseline_isolation(self):
        apps = [dict(id='a', kind='desktop'), dict(id='b', kind='service')]
        package = dict(id='music', name='Music', type='package', steps=[dict(appId='a', action='start')])
        second = dict(package, id='tools', steps=[dict(appId='a', action='start'), dict(appId='b', action='start')])
        scene = dict(id='game', name='Game', steps=[], packageSteps=[
            dict(packageId='music', action='stop'), dict(packageId='tools', action='stop')])
        presets = validate_presets([package, second, scene], apps, [])
        self.assertEqual(preset_steps(presets[2], presets), [dict(appId='a', action='stop'), dict(appId='b', action='stop')])
        self.assertEqual(preset_steps(presets[0], presets, 'stop'), [dict(appId='a', action='stop')])
        with self.assertRaises(ValueError):
            preset_steps(presets[0], presets)  # explicit desired state required
        with self.assertRaises(ValueError):
            validate_presets([scene], apps, [])  # cannot silently delete a referenced package
        with self.assertRaises(ValueError):
            validate_presets([dict(package, steps=[dict(appId='a', action='stop')])], apps, [])
        cfg = mock.Mock()
        cfg.snapshot.return_value = dict(presets=presets, activePreset='game')
        monitor = types.SimpleNamespace(cfg=cfg, lock=threading.Lock(), run=None,
                                        cancel=threading.Event(), _preset_worker=mock.Mock())
        with mock.patch('ops_monitor.threading.Thread') as thread:
            run = Monitor.start_preset(monitor, 'music', 'start')
        cfg.update.assert_not_called()  # opening a package never switches scene rules
        self.assertEqual(run['presetId'], 'music')
        self.assertEqual(run['steps'][0]['action'], 'start')
        thread.return_value.start.assert_called_once()


if __name__ == '__main__':
    unittest.main()
