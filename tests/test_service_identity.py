"""Manual only: python -m unittest discover -s tests -p test_service_identity.py"""
import os
import unittest
from types import SimpleNamespace

import server
from ops_entries import service_identity, instance_candidates


@unittest.skipUnless(os.name == 'nt', 'Windows command/path semantics')
class ServiceIdentityTest(unittest.TestCase):
    def test_service_entry_survives_launcher_changes_but_preserves_instance_arguments(self):
        cwd = r'H:\GROK资源整合'
        identity = service_identity(server,
            'pythonw.exe H:/GROK资源整合/workbench/http_server.py --port 8765', cwd)
        self.assertEqual(identity, service_identity(server,
            'python.exe -u workbench/http_server.py --port=8765', cwd))
        self.assertEqual(identity, service_identity(server,
            r'"\\?\C:\Python\python.exe" \\?\H:\GROK资源整合\workbench\http_server.py --port 8765', cwd))
        self.assertNotEqual(identity, service_identity(server, 'python.exe other.py', cwd))
        self.assertNotEqual(identity, service_identity(server, 'python.exe workbench/http_server.py', r'H:\other'))
        self.assertIsNone(service_identity(server, 'python.exe -c "other.py"', cwd))
        rows = {22: dict(exe='python.exe', args='python.exe workbench/http_server.py --port 8765', identity='new', ppid=0)}
        api = SimpleNamespace(SELF_PID=1, SELF_UID=7, _win_process_table=lambda: rows,
            process_uid=lambda pid: 7, _win_cwd=lambda pid: cwd, scan_listeners=lambda: [(22, 8765)],
            _win_tree_of=lambda pid, table: [pid], _simple_command_tokens=server._simple_command_tokens,
            _resolve_command_path=server._resolve_command_path)
        rule = dict(service=identity, port=8765)
        self.assertEqual(instance_candidates(api, rule), [22])
        api.scan_listeners = lambda: [(22, 9999)]
        self.assertEqual(instance_candidates(api, rule), [])
        api.scan_listeners = lambda: []
        rows[22]['args'] += ' --profile personal'
        self.assertEqual(instance_candidates(api, rule), [])


if __name__ == '__main__':
    unittest.main()
