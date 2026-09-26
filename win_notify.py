"""User-level Windows notifications; PowerShell runs only for delivery/setup."""
import base64
import os
import queue
import subprocess
import threading
import sys
import uuid
from xml.sax.saxutils import escape


def register_shortcut(path):
    """Set System.AppUserModel.ID on our own shortcut (IPropertyStore)."""
    import ctypes as C
    from ctypes import wintypes as W
    class Guid(C.Structure):
        _fields_ = [('bytes', C.c_ubyte*16)]
    class Key(C.Structure):
        _fields_ = [('fmtid', Guid), ('pid', W.DWORD)]
    class Value(C.Structure):
        _fields_ = [('vt', W.USHORT), ('reserved', W.USHORT*3), ('text', W.LPWSTR), ('extra', C.c_ulonglong)]
    guid = lambda value: Guid.from_buffer_copy(uuid.UUID(value).bytes_le)
    ole, shell = C.OleDLL('ole32'), C.OleDLL('shell32')
    ole.CoInitializeEx(None, 2)
    store = C.c_void_p()
    shell.SHGetPropertyStoreFromParsingName.argtypes = [W.LPCWSTR, C.c_void_p, W.DWORD, C.POINTER(Guid), C.POINTER(C.c_void_p)]
    try:
        iid = guid('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99')
        shell.SHGetPropertyStoreFromParsingName(path, None, 2, C.byref(iid), C.byref(store))
        table = C.cast(store, C.POINTER(C.POINTER(C.c_void_p))).contents
        key = Key(guid('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3'), 5)
        value = Value(); value.vt = 31; value.text = 'Cddeck.LocalOps'
        set_value = C.WINFUNCTYPE(C.HRESULT, C.c_void_p, C.POINTER(Key), C.POINTER(Value))(table[6])
        commit = C.WINFUNCTYPE(C.HRESULT, C.c_void_p)(table[7])
        if set_value(store, C.byref(key), C.byref(value)) < 0 or commit(store) < 0:
            raise OSError('通知快捷方式身份写入失败')
    finally:
        if store:
            C.WINFUNCTYPE(W.ULONG, C.c_void_p)(C.cast(store, C.POINTER(C.POINTER(C.c_void_p))).contents[2])(store)
        ole.CoUninitialize()


class Notifier:
    def __init__(self, enabled=True):
        self.status = 'starting' if enabled and os.name == 'nt' else 'disabled'
        self.queue = queue.Queue(maxsize=64)
        self.thread = None
        if enabled and os.name == 'nt':
            self.thread = threading.Thread(target=self._run, daemon=True, name='windows-notifications')
            self.thread.start()

    def send(self, event):
        if self.thread:
            try:
                self.queue.put_nowait(event)
            except queue.Full:
                self.status = 'busy'

    def close(self):
        if self.thread:
            try:
                self.queue.put_nowait(None)
            except queue.Full:
                pass

    def _deliver(self, event=None):
        # Registration is per-user, with our own AUMID; never impersonate PowerShell.
        xml = ('<toast><visual><binding template="ToastGeneric"><text>总控台</text><text>' +
               escape(event['title'] + ' · ' + event.get('detail', '')) + '</text></binding></visual></toast>') if event else ''
        payload = base64.b64encode(xml.encode('utf-8')).decode('ascii')
        if event is None:
            path = os.path.join(os.environ['APPDATA'], 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Cddeck 总控台.lnk')
            if not os.path.exists(path):
                python = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
                if not os.path.isfile(python): python = sys.executable
                target = os.path.join(os.path.dirname(__file__), 'server.py')
                def quoted(text): return "'"+text.replace("'", "''")+"'"
                setup = "$ErrorActionPreference='Stop'; $s=(New-Object -ComObject WScript.Shell).CreateShortcut("+quoted(path)+"); $s.TargetPath="+quoted(python)+"; $s.Arguments="+quoted('"'+target+'" --launcher')+"; $s.Description='Cddeck.LocalOps'; $s.Save()"
                result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                    base64.b64encode(setup.encode('utf-16le')).decode('ascii')], capture_output=True, timeout=15, creationflags=0x08000000)
                if result.returncode: return 'unavailable'
            register_shortcut(path)
        script = r'''
$ErrorActionPreference='Stop'
$p='HKCU:\Software\Classes\AppUserModelId\Cddeck.LocalOps'
if (!(Test-Path $p)) { New-Item $p -Force | Out-Null }
New-ItemProperty $p -Name DisplayName -Value '总控台' -PropertyType String -Force | Out-Null
[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotifier,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotification,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
[Windows.UI.Notifications.NotificationSetting,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime] | Out-Null
$n=[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Cddeck.LocalOps')
$status='ready'
try {
  if ($n.get_Setting().ToString() -ne 'Enabled') { Write-Output 'disabled'; exit }
} catch {
  # A new identity has no notification database entry until its first Show.
  if ($_.Exception.InnerException.HResult -ne -2147023728) { throw }
  $status='pending'
}
'''
        if event:
            script += "$x=New-Object Windows.Data.Xml.Dom.XmlDocument\n$x.LoadXml([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + payload + "')))\n$n.Show([Windows.UI.Notifications.ToastNotification]::new($x))\n$status='ready'\n"
        script += "Write-Output $status"
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                                 base64.b64encode(script.encode('utf-16le')).decode('ascii')],
                                capture_output=True, timeout=15, creationflags=0x08000000)
        if result.returncode:
            return 'unavailable'
        return 'ready' if b'ready' in result.stdout else 'pending' if b'pending' in result.stdout else 'disabled'

    def _run(self):
        try:
            self.status = self._deliver()
        except Exception:
            self.status = 'unavailable'
        while True:
            event = self.queue.get()
            if event is None:
                return
            try:
                self.status = self._deliver(event)
            except Exception:
                self.status = 'unavailable'
