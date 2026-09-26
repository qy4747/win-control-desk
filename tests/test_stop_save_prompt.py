"""Offline check: python -m unittest discover -s tests -p test_stop_save_prompt.py."""
import unittest
from unittest.mock import patch

import server
import ops_entries


class SavePromptTests(unittest.TestCase):
    def test_save_dialog_returns_actionable_message_without_force(self):
        app = {'id': 'bambu', 'name': 'Bambu Studio'}
        target = {'id': 10, 'kind': 'external', 'members': [10]}
        with patch.object(server, 'IS_WIN', True), \
             patch.object(server, 'resolve_app_stop_target', return_value=(target, None)), \
             patch.object(server, 'signal_app_stop', return_value=(True, None)) as signal, \
             patch.object(server, 'stop_target_alive', return_value=True), \
             patch.object(server, 'managed_pids', return_value=[10]), \
             patch.object(ops_entries, 'list_windows') as windows:
            windows.return_value = [{'pid': 10, 'windowClass': '#32770', 'title': 'Bambu Studio - 保存'}]
            ok, error = server.stop_app_and_wait(app, timeout=0)
            self.assertFalse(ok)
            self.assertTrue(error.startswith('需要保存'))
            signal.assert_called_once_with(target)
            windows.return_value[0]['pid'] = 99
            self.assertNotIn('需要保存', server.stop_app_and_wait(app, timeout=0)[1])
            windows.return_value = [{'pid': 10, 'windowClass': 'wxWindowNR', 'title': '保存案例 - BambuStudio'}]
            self.assertNotIn('需要保存', server.stop_app_and_wait(app, timeout=0)[1])


if __name__ == '__main__':
    unittest.main()
