import concurrent.futures
import datetime
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

import server
from ops_model import validate_rules
from ops_monitor import Alerts, Monitor, SNAPSHOT_METRIC, snapshot_slot, snapshot_delta, take_directory_snapshot


class DirectorySnapshots(unittest.TestCase):
    def rule(self, path, **values):
        return validate_rules([dict(id='logs', name='目录增长', metric=SNAPSHOT_METRIC,
            path=path, threshold=100, windowSec=86400, **values)])[0]

    def monitor(self, cfg):
        m = Monitor.__new__(Monitor)
        m.cfg, m.pool, m.snapshot_job = cfg, mock.Mock(), None
        m.stopped = threading.Event()
        m.directory_snapshots = cfg.snapshot()['directorySnapshots']
        m.pool.submit.side_effect = lambda *args: concurrent.futures.Future()
        m.rule_next, m.histories = {}, {}
        m.disk_time, m.disk_total = None, 0
        m.alerts = Alerts(mock.Mock())
        return m

    def test_schedule_restart_resume_and_failed_scan(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = os.path.join(td, 'config.json')
            cfg = server.Config(cfg_path)
            rule = self.rule(td)
            cfg.update(lambda c: c.update(rules=[rule]))
            m = self.monitor(cfg)
            now = datetime.datetime(2026, 9, 21, 8, 0).timestamp()
            with mock.patch('ops_monitor.time.time', return_value=now):
                m.check_directory_snapshots([rule])
                m.check_directory_snapshots([rule])
                self.assertEqual(m.pool.submit.call_count, 1)
                m.snapshot_job[0].set_result(dict(status='ok', bytes=500, durationMs=12))
                m.check_directory_snapshots([rule])
            saved = server.Config(cfg_path)
            self.assertEqual(saved.snapshot()['directorySnapshots'][td]['history'], [[now, 500]])
            m = self.monitor(saved)
            with mock.patch('ops_monitor.time.time', return_value=now+60):
                m.check_directory_snapshots([rule])
                m.pool.submit.assert_not_called()
            # Several missed days produce one scan; a failed scan keeps the last good baseline.
            with mock.patch('ops_monitor.time.time', return_value=now+3*86400):
                m.check_directory_snapshots([rule])
                self.assertEqual(m.pool.submit.call_count, 1)
                m.snapshot_job[0].set_result(dict(status='incomplete', bytes=None))
                m.check_directory_snapshots([rule])
                m.check_directory_snapshots([rule])
                self.assertEqual(m.pool.submit.call_count, 1)
            record = server.Config(cfg_path).snapshot()['directorySnapshots'][td]
            self.assertEqual(record['history'], [[now, 500]])
            self.assertIsNone(record['bytes'])
            self.assertEqual(record['status'], 'incomplete')

    def test_multiple_directories_are_serial_and_removed_result_is_discarded(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = server.Config(os.path.join(td, 'config.json'))
            rules = [self.rule(td), dict(self.rule(os.path.join(td, 'second')), id='second')]
            cfg.update(lambda c: c.update(rules=rules))
            m = self.monitor(cfg)
            m.check_directory_snapshots(rules)
            self.assertEqual(m.pool.submit.call_count, 1)
            cfg.update(lambda c: c.update(rules=rules[1:]))
            m.snapshot_job[0].set_result(dict(status='ok', bytes=123))
            m.check_directory_snapshots(rules[1:])
            self.assertNotIn(td, cfg.snapshot()['directorySnapshots'])
            self.assertEqual(m.pool.submit.call_count, 2)
            self.assertEqual(m.snapshot_job[1], rules[1]['path'])

    def test_daily_weekly_signed_growth_and_alerts_once_per_sample(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = server.Config(os.path.join(td, 'config.json'))
            m = self.monitor(cfg)
            rule = self.rule(td)
            week = 604800
            history = [[100, 100], [100+week-86400, 200], [100+week, 500]]
            self.assertEqual(snapshot_delta(history, 86400)['bytes'], 300)
            self.assertEqual(snapshot_delta(history, week)['bytes'], 400)
            self.assertIsNone(snapshot_delta(history[-1:], week))
            self.assertIsNone(snapshot_delta([[1, 0], [999999, 100]], 86400))
            m.directory_snapshots[td] = dict(status='ok', history=history, checkedAt=1)
            m.check_system({}, [rule], 1)
            m.check_system({}, [rule], 2)
            self.assertEqual(m.alerts.emit.call_count, 1)
            history.append([100+week+86400, 50])
            self.assertEqual(snapshot_delta(history, 86400)['bytes'], -450)
            m.directory_snapshots[td]['checkedAt'] = 2
            m.check_system({}, [rule], 3)
            self.assertFalse(m.alerts.active())
            self.assertEqual(m.alerts.emit.call_count, 2)

    def test_local_clock_validation_metadata_and_migration(self):
        times = ['03:00', '08:00', '12:30', '21:00']
        at = lambda d, h, minute=0: datetime.datetime(2026, 9, d, h, minute).timestamp()
        self.assertEqual(snapshot_slot(at(21, 1), times), at(20, 21))
        self.assertEqual(snapshot_slot(at(21, 12, 30), times), at(21, 12, 30))
        with tempfile.TemporaryDirectory() as td:
            for invalid in ([], ['24:00'], ['8:00'], times+['23:00'], '03:00'):
                with self.assertRaises(ValueError):
                    self.rule(td, dailyTimes=invalid)
            sub = os.path.join(td, '中文 空格')
            os.mkdir(sub)
            with open(os.path.join(sub, 'trace.log'), 'wb') as f:
                f.write(b'abc')
            self.assertEqual(take_directory_snapshot(sub)['bytes'], 3)
            canceled = threading.Event()
            canceled.set()
            self.assertEqual(take_directory_snapshot(sub, canceled)['status'], 'incomplete')
            path = os.path.join(td, 'config.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(dict(schemaVersion=7, apps=[], rules=[]), f)
            cfg = server.Config(path)
            self.assertEqual(cfg.snapshot()['schemaVersion'], 8)
            self.assertEqual(cfg.snapshot()['directorySnapshots'], {})


if __name__ == '__main__':
    unittest.main()
