"""Run: python -m unittest discover -s tests -p test_memory_health.py"""
import copy
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import server
from ops_model import MEMORY_RULES, validate_rules
from ops_monitor import Alerts, Monitor
from win_metrics import Metrics, ServiceEntry, ServiceStatus

GIB = 1024**3


def monitor():
    m = object.__new__(Monitor)
    m.api = types.SimpleNamespace(SELF_PID=42)
    m.events = []
    m.emit = m.events.append
    m.alerts = Alerts(m.emit)
    m.histories, m.rule_next = {}, {}
    m.disk_time, m.disk_total = None, 0
    return m


def process(private=7.2*GIB, identity='created-1', ws=.3*GIB):
    return dict(name='svchost.exe', identity=identity, privateBytes=private, ws=ws)


class MemoryHealthTests(unittest.TestCase):
    def test_low_resident_high_commit_and_console_do_not_need_cards(self):
        m = monitor()
        rows = {4708: process(), 42: process(300*1024**2)}
        for now in range(0, 141, 10):
            m.check_system({'commitPercent': 20}, MEMORY_RULES, now, rows, set(rows))
        active = m.alerts.active()
        self.assertEqual(len(active), 2)
        alert = next(a for a in active if a['process']['pid'] == 4708)
        self.assertEqual(alert['target'], 'system')
        self.assertEqual(alert['value'], 7.2*GIB)
        self.assertIn('驻留 0.30 GiB', alert['detail'])
        self.assertEqual(len(m.events), 2)  # Sustained readings do not spam notifications.
        self.assertIn('总控台', next(a for a in active if a['process']['pid'] == 42)['title'])

    def test_unknown_reuse_recovery_and_gaps_keep_identity(self):
        m = monitor()
        rule = copy.deepcopy(MEMORY_RULES[1])
        rows = {4708: process()}
        for now in range(0, 121, 10):
            m.check_process_memory(rule, rows, {4708}, now)
        key = m.alerts.active()[0]['key']
        m.check_process_memory(rule, {}, {4708}, 130)
        self.assertTrue(m.alerts.active()[0]['unknown'])
        m.check_process_memory(rule, {4708: process(0, identity='new')}, {4708}, 140)
        self.assertNotIn(key, m.alerts.states)
        self.assertFalse(m.alerts.active())
        self.assertIn('本次观察结束', m.events[-1]['title'])

        for now in range(150, 281, 10):
            m.check_process_memory(rule, rows, {4708}, now)
        rows[4708]['privateBytes'] = 3.5*GIB
        m.check_process_memory(rule, rows, {4708}, 290)
        self.assertTrue(m.alerts.active())  # Recovery uses 3 GiB, not the 4 GiB trigger.
        rows[4708]['privateBytes'] = 2*GIB
        for now in (300, 310): m.check_process_memory(rule, rows, {4708}, now)
        self.assertFalse(m.alerts.active())
        rows[4708]['privateBytes'] = 7.2*GIB
        for now in (320, 1000): m.check_process_memory(rule, rows, {4708}, now)
        self.assertFalse(m.alerts.active())  # Sleep/missing observations cannot satisfy duration.

    def test_busy_app_plateau_does_not_warn_but_pressure_or_sustained_growth_does(self):
        m = monitor()
        rows = {100: process(8*GIB, ws=7*GIB)}
        for now in range(0, 141, 10):
            m.check_system({'commitPercent': 40, 'memoryPercent': 50}, MEMORY_RULES, now, rows, set(rows))
        self.assertFalse(m.alerts.active())  # A large working application is not itself abnormal.
        for now in range(150, 291, 10):
            m.check_system({'commitPercent': 90, 'memoryPercent': 50}, MEMORY_RULES[1:2], now, rows, set(rows), {100: '演示渲染器'})
        self.assertEqual(m.alerts.active()[0]['title'], '演示渲染器 · 内存需要检查')
        self.assertIn('PID 100', m.alerts.active()[0]['detail'])
        alert = m.alerts.active()[0]
        m.alerts.accept(alert['key'], alert['incident'], 'temporary', 10*GIB)
        rows[100] = process(12*GIB, ws=11*GIB)
        for now in (300, 310):
            m.check_system({'commitPercent': 40, 'memoryPercent': 50}, MEMORY_RULES[1:2], now, rows, set(rows))
            self.assertFalse(m.alerts.active())  # A numeric override must not bypass the context gate.
        self.assertNotIn(alert['key'], m.alerts.overrides)

        m = monitor(); rule = MEMORY_RULES[2]
        for now in range(0, 4001, 10):
            rows[100] = process((1 if now < 900 else 8)*GIB, ws=7*GIB)
            m.check_process_memory(rule, rows, set(rows), now)
        self.assertFalse(m.alerts.active())  # One load followed by a plateau is filtered.
        self.assertFalse(m.events)
        for now in range(4010, 8001, 10):
            rows[100] = process((8+4*(now-4000)/1800)*GIB, ws=7*GIB)
            m.check_process_memory(rule, rows, set(rows), now)
        self.assertTrue(m.events)
        self.assertIn('多个时间段持续增长', m.events[0]['detail'])

    def test_service_names_are_read_only_cached_and_pid_identity_scoped(self):
        metrics = object.__new__(Metrics)
        metrics.table = {4708: dict(identity='first')}
        metrics.service_cache, metrics.service_cache_at = {}, float('-inf')
        entries = [ServiceEntry('netprofm', 'Network List Service', ServiceStatus(pid=4708)),
                   ServiceEntry('other', 'Other Service', ServiceStatus(pid=4708))]
        def enumerate_services(handle, level, kind, state, buf, size, needed, count, resume, group):
            self.assertEqual((level, kind, state, size), (0, 0x30, 1, 256*1024))
            C.cast(buf, C.POINTER(ServiceEntry))[0] = entries[0]
            C.cast(buf, C.POINTER(ServiceEntry))[1] = entries[1]
            count._obj.value = 2
            return 1
        metrics.scm = types.SimpleNamespace(OpenSCManagerW=mock.Mock(return_value=123),
            EnumServicesStatusExW=mock.Mock(side_effect=enumerate_services), CloseServiceHandle=mock.Mock())
        with mock.patch('win_metrics.time.monotonic', return_value=100):
            self.assertEqual(len(metrics.service_names(4708, 'first')), 2)
            self.assertEqual(metrics.service_names(4708, 'new'), [])
            self.assertEqual(len(metrics.service_names(4708, 'first')), 2)
        metrics.scm.EnumServicesStatusExW.assert_called_once()
        metrics.scm.OpenSCManagerW.assert_called_once_with(None, None, 4)
        metrics.scm.CloseServiceHandle.assert_called_once_with(123)
        m = monitor(); m.api._NATIVE_METRICS = metrics
        with mock.patch('win_metrics.time.monotonic', return_value=101):
            for now in range(0, 141, 10):
                m.check_process_memory(MEMORY_RULES[1], {4708: process(identity='first')}, {4708}, now)
        self.assertIn('共享服务宿主', m.alerts.active()[0]['title'])
        self.assertIn('不能据此定位其中某项服务', m.alerts.active()[0]['detail'])
        metrics.scm.EnumServicesStatusExW.return_value = 0
        metrics.scm.EnumServicesStatusExW.side_effect = None
        with mock.patch('win_metrics.time.monotonic', return_value=161):
            self.assertEqual(metrics.service_names(4708, 'first'), [])

    def test_growth_warmup_bounds_churn_and_unreadable_reset(self):
        m = monitor()
        rule = copy.deepcopy(MEMORY_RULES[2])
        rows = {pid: process(.1*GIB, str(pid)) for pid in range(100, 1100)}
        m.check_process_memory(rule, rows, set(rows), 0)
        self.assertFalse(m.alerts.active())
        for now in range(10, 7001, 10):
            rows[100]['privateBytes'] = (.1+2*now/1800)*GIB
            m.check_process_memory(rule, rows, set(rows), now)
        self.assertEqual(len(m.histories), 1000)
        self.assertLessEqual(max(map(len, m.histories.values())), 32)
        self.assertEqual(len(m.alerts.active()), 1)
        self.assertIn('净增长', m.alerts.active()[0]['detail'])
        rows[100]['privateBytes'] = None
        m.check_process_memory(rule, rows, set(rows), 7010)
        self.assertTrue(m.alerts.active()[0]['unknown'])
        self.assertEqual(len(m.histories[(rule['id'], '100@100')]), 0)
        for i in range(200):
            m.check_process_memory(rule, {1: process(.1*GIB, str(i))}, {1}, 7100+i*10)
            self.assertEqual(len(m.histories), 1)
        self.assertFalse(m.alerts.active())
        m.check_process_memory(rule, {}, set(), 9200)
        self.assertEqual(m.histories, {})

    def test_commit_pressure_scope_validation_and_user_acceptance(self):
        rules = validate_rules(MEMORY_RULES)
        self.assertEqual(rules[1]['intervalSec'], 10)
        for patch in ({'processScope': 'other'},):
            with self.assertRaises(ValueError): validate_rules([dict(rules[1], **patch)])
        with self.assertRaises(ValueError): validate_rules([dict(rules[0], threshold=101)])
        m = monitor()
        for now in range(0, 61, 10): m.check_system({'commitPercent': 90}, rules[:1], now)
        a = m.alerts.active()[0]
        with self.assertRaises(ValueError): m.alerts.accept(a['key'], a['incident'], 'temporary', 101)
        m.alerts.accept(a['key'], a['incident'], 'temporary', 95)
        self.assertFalse(m.alerts.active())
        m.check_system({'commitPercent': None}, rules[:1], 70)
        self.assertTrue(m.alerts.states[a['key']]['unknown'])

    def test_schema_upgrade_preserves_user_rules_backup_and_is_not_repeated(self):
        custom = dict(MEMORY_RULES[1], threshold=8*GIB, muted=True)
        original = dict(schemaVersion=8, apps=[], rules=[custom], ignoredAlerts={}, alertOverrides={})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, 'config.json')
            path.write_text(json.dumps(original), encoding='utf-8')
            cfg = server.Config(str(path))
            rules = cfg.snapshot()['rules']
            # schema 10 adds the early commit warning on top of the memory rules.
            self.assertEqual(len(rules), len(MEMORY_RULES) + 1)
            self.assertEqual(rules[0]['threshold'], 8*GIB)
            self.assertTrue(rules[0]['muted'])
            self.assertEqual(json.loads(Path(str(path)+'.bak').read_text(encoding='utf-8')), original)
            cfg.update(lambda c: c.update(rules=[]))
            self.assertEqual(server.Config(str(path)).snapshot()['rules'], [])

    @unittest.skipUnless(sys.platform == 'win32', 'Native Windows memory counters')
    def test_native_commit_counts_untouched_pages_and_stable_types(self):
        k = C.WinDLL('kernel32', use_last_error=True)
        k.VirtualAlloc.argtypes = [C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
        k.VirtualAlloc.restype = C.c_void_p
        k.VirtualFree.argtypes = [C.c_void_p, C.c_size_t, W.DWORD]
        metrics = Metrics()
        address = None
        try:
            before = metrics.sample()[os.getpid()]
            cache_count = len(C._pointer_type_cache)
            address = k.VirtualAlloc(None, 64*1024**2, 0x3000, 4)
            self.assertTrue(address, C.get_last_error())
            after = metrics.sample()[os.getpid()]
            self.assertGreaterEqual(after['privateBytes']-before['privateBytes'], 60*1024**2)
            self.assertLess(after['ws']-before['ws'], 32*1024**2)
            self.assertGreaterEqual(after['peakPrivateBytes'], after['privateBytes'])
            self.assertGreater(metrics.system['commitLimitBytes'], metrics.system['commitBytes'])
            self.assertGreater(metrics.system['processMemoryCoverage']['readable'], 0)
            self.assertEqual(len(C._pointer_type_cache), cache_count)
            metrics.service_names(os.getpid(), after['identity'])
            self.assertTrue(metrics.service_cache)  # Real local SCM read; no service mutation.
        finally:
            if address: k.VirtualFree(address, 0, 0x8000)
            metrics.close()


if __name__ == '__main__':
    unittest.main()
