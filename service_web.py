"""Service UI activation; browser windows never become service stop targets."""
import ctypes as C
from ctypes import wintypes as W
import os
import subprocess
import threading
import time
from urllib.parse import urlsplit
import uuid

from ops_entries import bind_window, list_windows, operate_window, resolve_window

_launch_lock = threading.Lock()


# ctypes caches pointer/function types globally. Reuse these definitions across
# reads; defining them inside window_app_property leaks types on every poll.
_GUID = C.c_ubyte * 16


class _PropertyKey(C.Structure):
    _fields_ = [('fmtid', _GUID), ('pid', W.DWORD)]


class _PropertyValue(C.Union):
    _fields_ = [('text', C.c_wchar_p), ('storage', C.c_ulonglong * 2)]


class _PropVariant(C.Structure):
    _fields_ = [('vt', W.WORD), ('reserved', W.WORD * 3), ('value', _PropertyValue)]


def is_browser_window(row):
    return os.path.basename(row.get('exe') or '').lower() in ('chrome.exe', 'msedge.exe')


def new_app_window(rows, before, chrome):
    candidates = [row for row in rows
                  if (row['hwnd'], row['pid'], row['created']) not in before
                  and os.path.normcase(row['exe']) == os.path.normcase(chrome)
                  and row['windowClass'] == 'Chrome_WidgetWin_1' and not row['toolWindow']
                  and window_app_property(row['hwnd'], 5).startswith('Chrome.')]
    if len(candidates) > 1:
        raise ValueError('同时出现多个网页应用窗口，请在卡片详情选择窗口关联')
    return candidates[0] if candidates else None


def window_app_property(hwnd, property_id):
    # Read only: https://learn.microsoft.com/windows/win32/api/shellapi/nf-shellapi-shgetpropertystoreforwindow
    iid = _GUID.from_buffer_copy(uuid.UUID('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99').bytes_le)
    key = _PropertyKey(_GUID.from_buffer_copy(uuid.UUID('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3').bytes_le), property_id)
    ole, shell = C.WinDLL('ole32'), C.WinDLL('shell32')
    shell.SHGetPropertyStoreForWindow.argtypes = [W.HWND, C.POINTER(_GUID), C.POINTER(C.c_void_p)]
    initialized = ole.CoInitialize(None) >= 0
    store, value = C.c_void_p(), _PropVariant()
    try:
        if shell.SHGetPropertyStoreForWindow(hwnd, C.byref(iid), C.byref(store)) < 0:
            return ''
        methods = C.cast(store, C.POINTER(C.POINTER(C.c_void_p))).contents
        get_value = C.WINFUNCTYPE(C.c_long, C.c_void_p, C.POINTER(_PropertyKey), C.POINTER(_PropVariant))(methods[5])
        if get_value(store, C.byref(key), C.byref(value)) >= 0 and value.vt == 31:
            return value.value.text or ''
        return ''
    finally:
        ole.PropVariantClear(C.byref(value))
        if store:
            methods = C.cast(store, C.POINTER(C.POINTER(C.c_void_p))).contents
            C.WINFUNCTYPE(W.ULONG, C.c_void_p)(methods[2])(store)
        if initialized:
            ole.CoUninitialize()


def same_service_url(left, right):
    def identity(value):
        parsed = urlsplit(value)
        host = parsed.hostname
        if host in ('localhost', '127.0.0.1', '::1'):
            host = 'loopback'
        return parsed.scheme, host, parsed.port, parsed.path.rstrip('/'), parsed.query
    try:
        return identity(left) == identity(right)
    except ValueError:
        return False


def browser_window(api, url):
    for row in list_windows(api):
        if not is_browser_window(row) or row['toolWindow']:
            continue
        tokens = api._simple_command_tokens(window_app_property(row['hwnd'], 2))
        if tokens and any(token.startswith('--app=') and same_service_url(token[6:], url) for token in tokens):
            return row
    return None


def focus_service(api, cfg, app):
    if not api.app_running(app):
        raise ValueError('服务未运行，请先打开服务')
    listeners = api.scan_listeners()
    members = set(api.managed_pids(app))
    if not members:
        legacy = api.legacy_managed_pid(app, listeners)
        if legacy:
            members.add(legacy)
    ports = sorted({port for pid, port in listeners if pid in members})
    port = app.get('port') if app.get('port') in ports else next(iter(ports), None)
    saved = app.get('windowBinding')
    if api.IS_WIN and saved and (is_browser_window(saved) or not (app.get('port') or port)):
        try:
            binding = resolve_window(api, app)
        except ValueError as exc:
            if '不唯一' in str(exc):
                raise
            pass  # Closed UI: find/open its web window without restarting the service.
        else:
            # An activation denial must not spawn a duplicate window.
            if binding != app.get('windowBinding'):
                cfg.update(lambda c: api.find_app(c, app['id']).update(windowBinding=binding))
            return operate_window(api, dict(app, windowBinding=binding), 'focus', cfg)
    if not port:
        raise ValueError('服务尚未监听端口，也没有关联窗口')
    host = api.listener_open_host(listeners, port, members)
    url = 'http://%s:%d/' % (host, port)
    if not api.IS_WIN:
        if not api.webbrowser.open(url, new=0, autoraise=True):
            raise ValueError('浏览器未接受打开请求')
        return {'ok': True, 'opened': True}
    # ponytail: serialize browser launches so two service buttons cannot claim
    # each other's newly created windows; use browser integration if tabs matter.
    with _launch_lock:
        row = browser_window(api, url)
        if row is None:
            chrome = api.find_chrome_executable()
            if not chrome:
                raise ValueError('未找到 Chrome，请先在卡片详情关联已有网页窗口')
            before = {(w['hwnd'], w['pid'], w['created']) for w in list_windows(api, include_hidden=True)}
            try:
                subprocess.Popen([chrome, '--app=' + url], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=api.independent_windows_flags())
            except OSError as exc:
                raise ValueError('无法打开网页窗口：' + str(exc)) from exc
            # Chrome --app windows may expose no RelaunchCommand at all. Capture
            # the new window, then retain its verified HWND/property binding.
            for _ in range(20):
                time.sleep(0.25)
                row = new_app_window(list_windows(api), before, chrome)
                if row:
                    break
            if row is None:
                raise ValueError('网页打开请求已发出，但未找到新窗口，请在卡片详情关联窗口')
        binding = bind_window(api, app['id'], row, app)
        cfg.update(lambda c: api.find_app(c, app['id']).update(windowBinding=binding))
    return operate_window(api, dict(app, windowBinding=binding), 'focus', cfg)
