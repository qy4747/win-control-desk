"""Run manually: python -m unittest discover -s tests -p test_script_stop.py"""
import unittest
from unittest.mock import Mock

from tools.stop_app_processes import stop


class ScriptStopTest(unittest.TestCase):
    def test_only_passes_complete_identities_and_reports_rejected_instances(self):
        terminate = Mock(return_value=[])
        stop({'appId': 'comfy', 'processes': [{'pid': 123, 'created': '456'}]}, terminate)
        terminate.assert_called_once_with({123: '456'})
        terminate.reset_mock()
        with self.assertRaises(ValueError):
            stop({'appId': 'comfy', 'processes': [{'pid': 123, 'created': ''}]}, terminate)
        terminate.assert_not_called()
        terminate.return_value = [123]
        with self.assertRaises(RuntimeError):
            stop({'appId': 'comfy', 'processes': [{'pid': 123, 'created': '456'}]}, terminate)
