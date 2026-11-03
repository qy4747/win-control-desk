"""Run: python -m unittest discover -s tests -p test_noise_rules.py"""
import copy
import time
import types
import unittest

import server
from ops_model import COMMIT_WATCH_RULE, DEFAULT_RULES, DISK_FREE_FLOOR_BYTES, validate_rules
from ops_monitor import Alerts, Monitor, commit_detail

GIB = 1024**3


def monitor():
    m = object.__new__(Monitor)
    m.api = types.SimpleNamespace(SELF_PID=42)
    m.events = []
    m.emit = m.events.append
    m.alerts = Alerts(m.emit)
    m.histories, m.rule_next = {}, {}
    m.disk_time, m.disk_total = None, 0
    m.previous_config, m.exit_baseline, m.probes = {}, {}, {}
    m.initial = False
    return m


def app(**extra):
    base = dict(id='a1', name='服务', kind='service', running=False, expectedRunning=True,
                startedAt=time.time() - 3600, health=dict(blocking=False), alertPolicy={},
                lastExit=None, port=None, probe=None, resources={})
    base.update(extra)
    return base


class NoiseRuleTests(unittest.TestCase):
    def test_v9_config_gains_disk_floor_and_commit_watch_once(self):
        raw = dict(schemaVersion=9, apps=[], rules=[dict(id='disk-free', name='磁盘', metric='diskFreePercent',
                                                     threshold=10, durationSec=60, intervalSec=60, muted=False)])
        migrated, source = server.migrate_config(raw)
        self.assertEqual(source, 9)
        self.assertEqual(migrated['schemaVersion'], server.CURRENT_SCHEMA_VERSION)
        disk = next(r for r in migrated['rules'] if r['id'] == 'disk-free')
        self.assertEqual(disk['minFreeBytes'], DISK_FREE_FLOOR_BYTES)
        self.assertIn(COMMIT_WATCH_RULE['id'], [r['id'] for r in migrated['rules']])
        custom = dict(raw, rules=[dict(raw['rules'][0], minFreeBytes=5*GIB)])
        self.assertEqual(server.migrate_config(custom)[0]['rules'][0]['minFreeBytes'], 5*GIB)
        validated = validate_rules(migrated['rules'])
        self.assertEqual(validated[0]['minFreeBytes'], DISK_FREE_FLOOR_BYTES)

    def test_large_disk_with_plenty_of_absolute_space_does_not_alert(self):
        m = monitor()
        rule = next(r for r in DEFAULT_RULES if r['id'] == 'disk-free')
        system = dict(disks=[dict(path='H:\\', freePercent=2.5, freeBytes=100*GIB),
                             dict(path='C:\\', freePercent=5.5, freeBytes=28*GIB)])
        for now in range(0, 181, 60):
            m.check_system(system, [rule], now)
        active = {a['key'] for a in m.alerts.active()}
        self.assertEqual(active, {'rule:disk-free:C:\\'})
        system['disks'][1]['freeBytes'] = 40*GIB
        for now in range(240, 361, 60):
            m.check_system(system, [rule], now)
        self.assertFalse(m.alerts.active())

    def test_commit_alert_names_largest_consumers(self):
        system = dict(commitPercent=90, commitTop=[
            dict(pid=1, name='chrome.exe', privateBytes=12*GIB, workingSetBytes=2*GIB),
            dict(pid=2, name='python.exe', privateBytes=5*GIB, workingSetBytes=5*GIB)],
            bootTime=time.time() - 9*86400)
        detail = commit_detail(system, {2: 'ComfyUI'})
        self.assertIn('chrome.exe 12.0 GiB', detail)
        self.assertIn('ComfyUI 5.0 GiB', detail)
        self.assertIn('9 天', detail)
        self.assertIsNone(commit_detail({}))
        m = monitor()
        rule = dict(COMMIT_WATCH_RULE, durationSec=0)
        m.check_system(system, [rule], 0, app_names={2: 'ComfyUI'})
        self.assertIn('ComfyUI', m.alerts.active()[0]['detail'])

    def test_service_started_before_boot_is_not_an_unexpected_exit(self):
        m = monitor()
        boot = time.time() - 600
        stale = app(id='old', startedAt=boot - 86400)
        crashed = app(id='new', startedAt=boot + 60)
        m.check_apps([stale, crashed], 0, True, boot)
        self.assertTrue(stale['stoppedByReboot'])
        self.assertFalse(crashed['stoppedByReboot'])
        self.assertEqual([a['key'] for a in m.alerts.active()], ['app:new:exit'])
        legacy = app(id='legacy', startedAt=boot - 86400)
        m.check_apps([legacy], 1, True, None)
        self.assertIn('app:legacy:exit', [a['key'] for a in m.alerts.active()])

    def test_service_layer_separates_system_components(self):
        windir = server.WIN_SYSTEM_DIR
        if server.IS_WIN:
            self.assertEqual(server.service_layer(windir + 'System32\\svc.exe', None, None), 'system')
            self.assertEqual(server.service_layer('C:\\Program Files\\X\\x.exe', None, dict(label='svchost.exe')), 'system')
            self.assertEqual(server.service_layer('C:\\Program Files\\X\\x.exe', None, dict(label='Explorer.EXE')), 'app')
            self.assertEqual(server.service_layer(windir + 'x.exe', dict(id='a'), None), 'app')


if __name__ == '__main__':
    unittest.main()
