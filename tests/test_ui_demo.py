import time
import unittest
from tools.ui_demo import Demo


class DemoTests(unittest.TestCase):
    def test_interactive_acceptance_flow_stays_in_memory_and_resets(self):
        demo = Demo(9610)
        self.assertEqual(len(demo.snapshot()['apps']), 12)
        alert = demo.app('comfy')['alerts'][0]
        demo.request('POST', '/api/ops/alerts/ignore', dict(key=alert['key'], incident=alert['incident']))
        self.assertTrue(demo.snapshot()['apps'][0]['alerts'][0]['ignored'])
        demo.request('PUT', '/api/apps/comfy', dict(cardButtons=[]))
        self.assertEqual(demo.app('comfy')['cardButtons'], [])
        demo.request('POST', '/api/ops/presets/run', dict(id='partial'))
        demo.run_start = time.monotonic()-10
        result = demo.snapshot()['presetRun']
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([s['status'] for s in result['steps']], ['skipped', 'failed', 'succeeded'])
        demo.request('POST', '/api/ops/presets/run', dict(id='game'))
        demo.request('POST', '/api/ops/presets/cancel', {})
        self.assertEqual(demo.snapshot()['presetRun']['status'], 'canceled')
        demo.request('POST', '/api/demo/scenario', dict(scenario='empty'))
        self.assertEqual(demo.snapshot()['apps'], [])
        self.assertFalse(demo.request('POST', '/api/not-implemented', {})['ok'])
        demo.request('POST', '/api/demo/reset', {})
        self.assertFalse(demo.app('comfy')['alerts'][0]['ignored'])
        self.assertTrue(demo.app('comfy')['cardButtons'])
        self.assertEqual(len(demo.snapshot()['apps']), 12)

