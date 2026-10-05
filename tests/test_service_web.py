"""Offline check: python -m unittest discover -s tests -p test_service_web.py."""
import ctypes as C
from ctypes import wintypes as W
import gc
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import service_web
import ops_entries


class ServiceWebTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'Windows property store required')
    def test_repeated_window_property_reads_do_not_grow_type_caches(self):
        user = C.WinDLL('user32', use_last_error=True)
        user.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
                                        C.c_int, C.c_int, C.c_int, C.c_int,
                                        W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p]
        user.CreateWindowExW.restype = W.HWND
        user.DestroyWindow.argtypes = [W.HWND]
        # Own a hidden window so this test needs neither a browser nor user data.
        hwnd = user.CreateWindowExW(0, 'STATIC', '', 0, 0, 0, 0, 0,
                                    None, None, None, None)
        self.assertTrue(hwnd, C.get_last_error())
        try:
            self.assertEqual(service_web.window_app_property(hwnd, 5), '')
            def cache_sizes():
                return len(C._pointer_type_cache), len(C._win_functype_cache)
            before = cache_sizes()
            for _ in range(256):
                self.assertEqual(service_web.window_app_property(hwnd, 5), '')
            gc.collect()
            self.assertEqual(cache_sizes(), before)
        finally:
            user.DestroyWindow(hwnd)

    def test_installed_web_app_survives_browser_suffix_and_title_changes(self):
        exe = 'chrome.exe'
        rule = dict(exe=exe, windowClass='Chrome_WidgetWin_1', toolWindow=False,
                    scope='title', title='SillyTavern - Google Chrome')
        app = dict(id='st', windowBinding={'match': rule})
        row = dict(exe=exe, windowClass=rule['windowClass'], toolWindow=False,
                   hwnd=20, pid=30, title='SillyTavern')
        with patch.object(ops_entries, 'verify_window', side_effect=ValueError('old window closed')), \
             patch.object(ops_entries, 'list_windows', return_value=[row]), \
             patch.object(ops_entries, 'bind_window', side_effect=lambda api, ident, window, app: window), \
             patch.object(service_web, 'window_app_property', return_value='Chrome._crx_st'):
            self.assertEqual(ops_entries.resolve_window(None, app)['hwnd'], 20)
            rule['browserAppId'] = 'Chrome._crx_st'
            row['title'] = 'A different chat title'
            self.assertEqual(ops_entries.resolve_window(None, app)['hwnd'], 20)
            rule['browserAppId'] = 'Chrome._crx_other'
            with self.assertRaises(ValueError):
                ops_entries.resolve_window(None, app)

    def test_focus_reuses_window_and_does_not_start_stopped_service(self):
        app = dict(id='st', port=8000, windowBinding={'hwnd': 10, 'exe': 'chrome.exe'})
        cfg = Mock()
        api = SimpleNamespace(IS_WIN=True, app_running=lambda _: False,
            managed_pids=lambda _: [12], scan_listeners=lambda: [(12, 8000)])
        with patch.object(service_web, 'resolve_window') as resolve:
            with self.assertRaisesRegex(ValueError, '未运行'):
                service_web.focus_service(api, cfg, app)
            resolve.assert_not_called()
        api.app_running = lambda _: True
        with patch.object(service_web, 'resolve_window', return_value=app['windowBinding']), \
             patch.object(service_web, 'operate_window', side_effect=ValueError('activation denied')), \
             patch.object(service_web.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(ValueError, 'activation denied'):
                service_web.focus_service(api, cfg, app)
            launch.assert_not_called()

    def test_only_owned_listener_is_opened_and_window_is_reused(self):
        app = dict(id='st', port=8000)
        api = SimpleNamespace(IS_WIN=True, app_running=lambda _: True,
            managed_pids=lambda _: [12], scan_listeners=lambda: [(99, 8000), (12, 8001)],
            listener_open_host=lambda *args: '127.0.0.1', find_app=lambda c, ident: c)
        cfg = SimpleNamespace(update=lambda fn: fn(app))
        binding = {'hwnd': 20}
        with patch.object(service_web, 'browser_window', return_value=binding) as lookup, \
             patch.object(service_web, 'bind_window', return_value=binding), \
             patch.object(service_web, 'operate_window', return_value={'ok': True}), \
             patch.object(service_web.subprocess, 'Popen') as launch:
            self.assertTrue(service_web.focus_service(api, cfg, app)['ok'])
            lookup.assert_called_once_with(api, 'http://127.0.0.1:8001/')
            launch.assert_not_called()
        self.assertEqual(app['windowBinding'], binding)
        self.assertTrue(service_web.same_service_url('http://localhost:8000/', 'http://127.0.0.1:8000'))
        self.assertFalse(service_web.same_service_url('http://localhost:8000/', 'http://localhost:8001/'))

    def test_service_ignores_terminal_and_remembers_new_app_without_relaunch_command(self):
        app = dict(id='observer', port=4173, windowBinding={'exe': 'WindowsTerminal.exe'})
        row = dict(hwnd=20, pid=30, created='current', exe='chrome.exe',
                   windowClass='Chrome_WidgetWin_1', toolWindow=False, title='Observer')
        api = SimpleNamespace(IS_WIN=True, app_running=lambda _: True,
            managed_pids=lambda _: [12], scan_listeners=lambda: [(12, 4173)],
            listener_open_host=lambda *args: '127.0.0.1', find_app=lambda c, ident: c,
            find_chrome_executable=lambda: 'chrome.exe', independent_windows_flags=lambda: 0)
        cfg = SimpleNamespace(update=lambda fn: fn(app))
        with patch.object(service_web, 'resolve_window') as resolve, \
             patch.object(service_web, 'browser_window', return_value=None), \
             patch.object(service_web, 'list_windows', side_effect=[[], [row]]), \
             patch.object(service_web, 'window_app_property', return_value='Chrome.127.0.0.1_/'), \
             patch.object(service_web, 'bind_window', return_value=row), \
             patch.object(service_web, 'operate_window', return_value={'ok': True}), \
             patch.object(service_web.time, 'sleep'), \
             patch.object(service_web.subprocess, 'Popen') as launch:
            self.assertTrue(service_web.focus_service(api, cfg, app)['ok'])
            resolve.assert_not_called()
            launch.assert_called_once()
        self.assertEqual(app['windowBinding'], row)


if __name__ == '__main__':
    unittest.main()
