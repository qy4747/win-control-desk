import json
import unittest
from ops_monitor import Alerts
from ops_model import validate_app_extra
from tools.ui_demo import Demo
import server


class AcceptanceTests(unittest.TestCase):
    def test_temporary_threshold_realerts_and_expires_only_at_original_recovery(self):
        events = []
        a = Alerts(events.append)
        rule = dict(name='Memory', metric='memoryBytes', threshold=300, recoveryThreshold=280, durationSec=2)
        for t in (0, 2): a.check('memory', True, 400, rule, t)
        a.accept('memory', a.active()[0]['incident'], 'temporary', 450)
        self.assertEqual(a.active(), [])
        a.check('memory', True, 420, rule, 3)
        self.assertIn('memory', a.overrides)
        for t in (4, 6): a.check('memory', True, 460, rule, t)
        self.assertEqual(len(a.active()), 1)
        self.assertFalse(a.active()[0]['ignored'])
        a.check('memory', None, None, rule, 7)
        self.assertIn('memory', a.overrides)
        a.check('memory', False, 290, rule, 8, recover=2)
        self.assertIn('memory', a.overrides)
        a.check('memory', False, 270, rule, 9, recover=2)
        self.assertIn('memory', a.overrides)
        a.check('memory', False, 270, rule, 10, recover=2)
        self.assertNotIn('memory', a.overrides)
        for t in (11, 13): a.check('memory', True, 400, rule, t)
        self.assertEqual(len([e for e in events if e['phase'] == 'alert']), 3)

    def test_low_threshold_and_validation(self):
        a = Alerts(lambda e: None)
        rule = dict(name='Disk', metric='diskFreePercent', threshold=10, durationSec=0)
        a.check('disk', True, 3, rule, 0)
        incident = a.active()[0]['incident']
        for value in (None, True, float('nan'), 4, -1):
            with self.assertRaises(ValueError): a.accept('disk', incident, 'temporary', value)
        a.accept('disk', incident, 'temporary', 2)
        a.check('disk', True, 2.5, rule, 1)
        self.assertFalse(a.active())
        a.check('disk', True, 1, rule, 2)
        self.assertTrue(a.active())

    def test_permanent_survives_recovery_restart_and_can_be_revoked(self):
        events = []
        a = Alerts(events.append)
        rule = dict(name='HTTP', appId='app', durationSec=0)
        a.check('http', True, 'error', rule, 0)
        a.accept('http', a.active()[0]['incident'], 'permanent')
        a = Alerts(events.append, overrides=json.loads(json.dumps(a.overrides)))
        a.check('http', False, 'ok', rule, 1)
        a.check('http', True, 'error', rule, 2)
        self.assertTrue(a.active()[0]['ignored'])
        self.assertTrue(events[-1]['muted'])
        a.revoke('http')
        a.check('http', True, 'error', rule, 3)
        self.assertFalse(a.active()[0]['ignored'])
        self.assertFalse(events[-1]['muted'])

    def test_temporary_boolean_recovery_and_restart(self):
        a = Alerts(lambda e: None)
        rule = dict(name='HTTP', durationSec=0)
        a.check('http', True, 'error', rule, 0)
        a.accept('http', a.active()[0]['incident'], 'temporary')
        a = Alerts(lambda e: None, overrides=json.loads(json.dumps(a.overrides)))
        a.check('http', True, 'error', rule, 1)
        self.assertTrue(a.active()[0]['ignored'])
        a.check('http', False, 'ok', rule, 2, recover=2)
        a.check('http', None, None, rule, 3, recover=2)
        self.assertIn('http', a.overrides)
        a.check('http', False, 'ok', rule, 4, recover=2)
        self.assertIn('http', a.overrides)
        a.check('http', False, 'ok', rule, 5, recover=2)
        self.assertNotIn('http', a.overrides)

    def test_schema_and_demo_use_production_contracts(self):
        data, _ = server.migrate_config(dict(schemaVersion=3, apps=[]))
        self.assertEqual(data['schemaVersion'], server.CURRENT_SCHEMA_VERSION)
        self.assertEqual(data['alertOverrides'], {})
        demo = Demo(9611)
        for app in demo.snapshot()['apps']: validate_app_extra({'cardButtons': app['cardButtons']})
        alert = next(a for a in demo.snapshot()['alerts'] if a['target'] == 'comfy')
        demo.request('POST', '/api/ops/alerts/accept', dict(key=alert['key'], incident=alert['incident'], mode='temporary', threshold=5*1024**3))
        self.assertFalse(demo.snapshot()['apps'][0]['alerts'])
        demo.app('comfy')['resources']['memoryBytes'] = 6*1024**3
        self.assertTrue(demo.snapshot()['apps'][0]['alerts'])
        demo.request('DELETE', '/api/apps/comfy', {})
        self.assertNotIn('app:comfy:memory', demo.snapshot()['alertOverrides'])


if __name__ == '__main__': unittest.main()
