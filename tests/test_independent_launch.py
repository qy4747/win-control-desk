"""Manual check: python -m unittest discover -s tests -p test_independent_launch.py"""
import io
import unittest
from unittest.mock import patch
import server


class IndependentLaunchTest(unittest.TestCase):
    def test_breakaway_required_and_denied_host_never_retries_as_child(self):
        self.assertTrue(server.independent_windows_flags() & 0x01000000)
        denied = OSError('access denied')
        denied.winerror = 5
        with patch.object(server.os.path, 'isfile', return_value=True), \
                patch.object(server.subprocess, 'Popen', side_effect=denied) as popen:
            result = server._start_app_windows({'command': 'echo example', 'shell': 'cmd'},
                '.', io.BytesIO(), {}, 'marker', 'token')
        self.assertFalse(result[0])
        self.assertIn('独立启动', result[1])
        popen.assert_called_once()
        self.assertTrue(popen.call_args.kwargs['creationflags'] & 0x01000000)
