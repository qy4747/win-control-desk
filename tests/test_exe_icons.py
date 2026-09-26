import base64
import unittest
from unittest.mock import patch
import server


class ExeIconTests(unittest.TestCase):
    def test_extracts_configured_exe_as_data_and_skips_interpreters(self):
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jp1sAAAAASUVORK5CYII=')
        app = {'kind':'desktop', 'externalIdentity':{'exe':"C:\\Apps\\O'Brien\\app.exe"}}
        with patch.object(server, 'IS_WIN', True), patch.object(server.os.path, 'isfile', return_value=True), \
             patch.object(server, '_win_powershell', return_value=base64.b64encode(png).decode()) as native:
            self.assertEqual(server.extract_app_exe_icon(app), png)
            self.assertIn("O''Brien", native.call_args.args[0])
            native.reset_mock()
            self.assertIsNone(server.extract_app_exe_icon({'kind':'service'}))
            self.assertIsNone(server.extract_app_exe_icon({'kind':'desktop', 'externalIdentity':{'exe':'python.exe'}}))
            native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
