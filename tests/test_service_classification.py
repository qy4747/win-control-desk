import unittest
from unittest.mock import patch
import server


class ServiceClassificationTest(unittest.TestCase):
    def test_user_services_are_explicit_or_known_runtimes_and_other_apps_stay_background(self):
        with patch.object(server, 'IS_WIN', True):
            for name in ('wpscloudsvr.exe', 'Steam.exe', 'chrome.exe', 'node-helper.exe', 'custom-server.exe'):
                key = name + ':4709'
                args = (key, name, 'D:\\Apps\\' + name, '', r'C:\Windows')
                self.assertEqual(server.classify_group(*args, []), 'background')
                self.assertEqual(server.classify_group(*args, [key]), 'mine')
                self.assertEqual(server.classify_group(*args, [], {'kind': 'service'}), 'mine')
            for name in ('python.exe', 'python3.13.exe', 'node.exe', 'javaw.exe', 'redis-server.exe'):
                args = (name + ':8000', name, 'D:\\Tools\\' + name, '', 'D:\\Project')
                self.assertEqual(server.classify_group(*args, []), 'mine')
                self.assertEqual(server.classify_group(*args, [], {'kind': 'desktop'}), 'background')
            self.assertEqual(server.classify_group('python.exe:8000', 'python.exe',
                server.WIN_SYSTEM_DIR + 'python.exe', '', '', []), 'background')
