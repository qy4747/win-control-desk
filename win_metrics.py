"""Read-only Windows telemetry. No PowerShell, third-party packages or service."""
import ctypes as C
from ctypes import wintypes as W
import os
import re
import shutil
import socket
import time


class Memory(C.Structure):
    _fields_ = [('length', W.DWORD), ('load', W.DWORD)] + [
        (n, C.c_ulonglong) for n in ('total', 'available', 'page', 'pageAvailable',
                                    'virtual', 'virtualAvailable', 'extended')]


class ProcessMemory(C.Structure):
    _fields_ = [('cb', W.DWORD), ('faults', W.DWORD)] + [
        (n, C.c_size_t) for n in ('peak', 'working', 'peakPaged', 'paged',
                                'peakNonpaged', 'nonpaged', 'page', 'peakPage')]


class IO(C.Structure):
    _fields_ = [(n, C.c_ulonglong) for n in
                ('reads', 'writes', 'others', 'readBytes', 'writeBytes', 'otherBytes')]


class Unicode(C.Structure):
    _fields_ = [('length', W.USHORT), ('maximum', W.USHORT), ('buffer', C.c_void_p)]


class CounterValue(C.Structure):
    _fields_ = [('status', W.DWORD), ('value', C.c_double)]


class CounterItem(C.Structure):
    _fields_ = [('name', W.LPWSTR), ('value', CounterValue)]


class AdapterLuid(C.Structure):
    _fields_ = [('low', C.c_uint32), ('high', C.c_int32)]


class OpenAdapter(C.Structure):
    _fields_ = [('luid', AdapterLuid), ('handle', C.c_uint32)]


class VideoMemoryInfo(C.Structure):
    # D3DKMT_QUERYVIDEOMEMORYINFO, d3dkmthk.h. LOCAL (0) excludes shared memory.
    _fields_ = [('process', W.HANDLE), ('adapter', C.c_uint32), ('segment', C.c_uint32),
                ('budget', C.c_uint64), ('usage', C.c_uint64),
                ('reservation', C.c_uint64), ('available', C.c_uint64),
                ('physical_index', C.c_uint32)]


class Metrics:
    def __init__(self):
        from tools.win_anchor import _snapshot_ppids
        self.ppids = _snapshot_ppids
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.nt = C.WinDLL('ntdll')
        self.k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.k.OpenProcess.restype = W.HANDLE
        self.k.CloseHandle.argtypes = [W.HANDLE]
        self.k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
        self.k.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(C.c_ulonglong)] * 4
        self.k.K32GetProcessMemoryInfo.argtypes = [W.HANDLE, C.POINTER(ProcessMemory), W.DWORD]
        self.k.GetProcessIoCounters.argtypes = [W.HANDLE, C.POINTER(IO)]
        self.nt.NtQueryInformationProcess.argtypes = [W.HANDLE, W.ULONG, C.c_void_p, W.ULONG, C.POINTER(W.ULONG)]
        self.previous = {}
        self.previous_system = None
        self.table = {}
        self.seen_pids = set()
        self.system = {}
        self.disks = []
        self.disk_at = 0
        self.gdi, self.gpu_adapters = None, []
        try:
            gdi = C.WinDLL('gdi32')
            for name, structure in [('D3DKMTOpenAdapterFromLuid', OpenAdapter),
                                    ('D3DKMTCloseAdapter', C.c_uint32),
                                    ('D3DKMTQueryVideoMemoryInfo', VideoMemoryInfo)]:
                function = getattr(gdi, name)
                function.argtypes = [C.POINTER(structure)]
                function.restype = C.c_int32  # NTSTATUS
            self.gdi = gdi
        except (OSError, AttributeError):
            pass  # Unsupported Windows: process GPU readings remain unavailable.
        self.pdh = C.WinDLL('pdh')
        self.pdh.PdhOpenQueryW.argtypes = [W.LPCWSTR, C.c_size_t, C.POINTER(W.HANDLE)]
        self.pdh.PdhAddEnglishCounterW.argtypes = [W.HANDLE, W.LPCWSTR, C.c_size_t, C.POINTER(W.HANDLE)]
        self.pdh.PdhCollectQueryData.argtypes = [W.HANDLE]
        self.pdh.PdhGetFormattedCounterArrayW.argtypes = [W.HANDLE, W.DWORD, C.POINTER(W.DWORD), C.POINTER(W.DWORD), C.c_void_p]
        self.pdh.PdhCloseQuery.argtypes = [W.HANDLE]
        self.query = W.HANDLE()
        self.counters = {}
        if self.pdh.PdhOpenQueryW(None, 0, C.byref(self.query)) == 0:
            for key, path in {
                'diskWriteBytesPerSec': r'\PhysicalDisk(_Total)\Disk Write Bytes/sec',
                'dedicated': r'\GPU Adapter Memory(*)\Dedicated Usage',
                'shared': r'\GPU Adapter Memory(*)\Shared Usage',
            }.items():
                handle = W.HANDLE()
                if self.pdh.PdhAddEnglishCounterW(self.query, path, 0, C.byref(handle)) == 0:
                    self.counters[key] = handle

    def counter(self, key):
        handle = self.counters.get(key)
        if not handle:
            return {}
        size, count = W.DWORD(), W.DWORD()
        self.pdh.PdhGetFormattedCounterArrayW(handle, 0x200, C.byref(size), C.byref(count), None)
        if not size.value or size.value > 1024 * 1024:
            return {}
        buf = C.create_string_buffer(size.value)
        if self.pdh.PdhGetFormattedCounterArrayW(handle, 0x200, C.byref(size), C.byref(count), buf) != 0:
            return {}
        items = C.cast(buf, C.POINTER(CounterItem))
        return {items[i].name: items[i].value.value for i in range(count.value)
                if items[i].value.status in (0, 1)}

    def close(self):
        self.refresh_gpu_adapters([])
        if self.query:
            self.pdh.PdhCloseQuery(self.query)
            self.query = None

    def refresh_gpu_adapters(self, names):
        for handle, _ in self.gpu_adapters:
            if handle is not None:
                self.gdi.D3DKMTCloseAdapter(C.byref(C.c_uint32(handle)))
        self.gpu_adapters = []
        if not self.gdi:
            return
        # Reuse adapter identities from the whole-GPU counters, never their
        # process-memory values. Reopen each sample to handle driver changes.
        for name in sorted(set(names)):
            match = re.fullmatch(r'luid_0x([0-9a-fA-F]+)_0x([0-9a-fA-F]+)_phys_(\d+)', name)
            if not match:
                self.gpu_adapters.append((None, 0))
                continue
            high, low, physical = match.groups()
            adapter = OpenAdapter(AdapterLuid(int(low, 16), C.c_int32(int(high, 16)).value))
            status = self.gdi.D3DKMTOpenAdapterFromLuid(C.byref(adapter))
            self.gpu_adapters.append((adapter.handle if status == 0 and adapter.handle else None, int(physical)))

    def gpu_memory(self, process):
        if not self.gpu_adapters or any(handle is None for handle, _ in self.gpu_adapters):
            return None
        total = 0
        for handle, physical in self.gpu_adapters:
            info = VideoMemoryInfo(process=process, adapter=handle, segment=0, physical_index=physical)
            if self.gdi.D3DKMTQueryVideoMemoryInfo(C.byref(info)) != 0:
                return None  # Do not publish a partial total or fall back to PDH.
            total += info.usage
        return total

    def memory(self):
        m = Memory()
        m.length = C.sizeof(m)
        if not self.k.GlobalMemoryStatusEx(C.byref(m)):
            raise OSError('无法读取物理内存')
        return m

    def command(self, handle):
        size = W.ULONG()
        self.nt.NtQueryInformationProcess(handle, 60, None, 0, C.byref(size))
        if not size.value or size.value > 1024 * 1024:
            return ''
        buf = C.create_string_buffer(size.value)
        if self.nt.NtQueryInformationProcess(handle, 60, buf, size, None) != 0:
            return ''
        value = Unicode.from_buffer(buf)
        start, end = C.addressof(buf), C.addressof(buf) + len(buf)
        if not value.buffer or not start <= value.buffer <= end - value.length:
            return ''
        return C.wstring_at(value.buffer, value.length // 2)

    def sample(self):
        now = time.monotonic()
        if self.query:
            self.pdh.PdhCollectQueryData(self.query)
        dedicated, shared = self.counter('dedicated'), self.counter('shared')
        self.refresh_gpu_adapters(set(dedicated) | set(shared))
        table, previous = {}, {}
        ppids = self.ppids()
        self.seen_pids = set(ppids)
        for pid, ppid in ppids.items():
            # D3DKMT queries need QUERY_INFORMATION; preserve other metrics if
            # only QUERY_LIMITED_INFORMATION is allowed for this process.
            handle = self.k.OpenProcess(0x400, False, pid) or self.k.OpenProcess(0x1000, False, pid)
            if not handle:
                continue
            try:
                created, exited, kernel, user = [C.c_ulonglong() for _ in range(4)]
                if not self.k.GetProcessTimes(handle, *[C.byref(v) for v in (created, exited, kernel, user)]):
                    continue
                identity = (pid, created.value)
                old = self.previous.get(identity)
                ticks = kernel.value + user.value
                cpu = (max(0, ticks - old[1]) / 1e7 / max(.001, now - old[0]) * 100 / (os.cpu_count() or 1)
                       if old else None)
                previous[identity] = (now, ticks)
                cached = self.table.get(pid, {})
                if cached.get('identity') == str(created.value):
                    exe, args = cached['exe'], cached['args']
                else:
                    path, length = C.create_unicode_buffer(32768), W.DWORD(32768)
                    exe = path.value if self.k.QueryFullProcessImageNameW(handle, 0, path, C.byref(length)) else ''
                    args = self.command(handle)
                mem, io = ProcessMemory(), IO()
                mem.cb = C.sizeof(mem)
                ws = mem.working if self.k.K32GetProcessMemoryInfo(handle, C.byref(mem), mem.cb) else None
                write_bytes = io.writeBytes if self.k.GetProcessIoCounters(handle, C.byref(io)) else None
                table[pid] = dict(ppid=ppid, name=os.path.basename(exe), exe=exe, args=args,
                                  created=(created.value - 116444736000000000) / 1e7,
                                  identity=str(created.value), ws=ws, cpu=cpu, ioWriteBytes=write_bytes,
                                  gpuMemoryBytes=self.gpu_memory(handle))
            finally:
                self.k.CloseHandle(handle)
        self.previous, self.table = previous, table
        idle, kernel, user = [C.c_ulonglong() for _ in range(3)]
        cpu = None
        if self.k.GetSystemTimes(C.byref(idle), C.byref(kernel), C.byref(user)):
            current = (idle.value, kernel.value + user.value)
            if self.previous_system:
                di, dt = [a-b for a, b in zip(current, self.previous_system)]
                if dt > 0:
                    cpu = max(0, min(100, (1-di/dt)*100))
            self.previous_system = current
        mem = self.memory()
        if now - self.disk_at >= 60:
            disks = []
            for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
                root = letter + ':\\'
                if self.k.GetDriveTypeW(C.c_wchar_p(root)) == 3:
                    try:
                        d = shutil.disk_usage(root)
                        disks.append(dict(path=root, totalBytes=d.total, freeBytes=d.free,
                                          freePercent=d.free/d.total*100))
                    except OSError:
                        pass
            self.disks, self.disk_at = disks, now
        self.system = dict(cpu=cpu, memoryBytes=mem.total-mem.available,
                           memoryTotalBytes=mem.total, memoryPercent=mem.load,
                           disks=self.disks,
                           diskWriteBytesPerSec=self.counter('diskWriteBytesPerSec').get('_Total'),
                           gpus=[dict(id=k, dedicatedBytes=dedicated.get(k), sharedBytes=shared.get(k),
                                      capacityBytes=None) for k in sorted(set(dedicated) | set(shared))])
        return table


def windows(include_hidden=False):
    """Top-level windows grouped by PID; hidden windows are opt-in for bindings."""
    user = C.WinDLL('user32')
    result = {}
    callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    user.IsWindowVisible.argtypes = [W.HWND]
    user.GetWindowTextLengthW.argtypes = [W.HWND]
    user.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    user.EnumWindows.argtypes = [callback_type, W.LPARAM]

    @callback_type
    def visit(hwnd, _):
        length = user.GetWindowTextLengthW(hwnd)
        if include_hidden or (user.IsWindowVisible(hwnd) and length):
            text = C.create_unicode_buffer(length+1)
            user.GetWindowTextW(hwnd, text, length+1)
            pid = W.DWORD()
            user.GetWindowThreadProcessId(hwnd, C.byref(pid))
            result.setdefault(pid.value, []).append((int(hwnd), text.value))
        return True
    user.EnumWindows(visit, 0)
    return result


def close_windows(pids):
    user = C.WinDLL('user32')
    user.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    sent = False
    for pid, items in windows().items():
        if pid in pids:
            for hwnd, _ in items:
                sent = bool(user.PostMessageW(hwnd, 0x10, 0, 0)) or sent  # WM_CLOSE
    return sent



class SuspendedProcesses:
    """Briefly pause exact verified instances while collecting a stop boundary.

    Keep the original handles open until the transaction ends. A failed collection
    resumes every process paused here; nothing is suspended by name or raw PPID.
    NtSuspendProcess/NtResumeProcess are native Windows exports, not cross-platform
    APIs. Missing exports or denied access fail closed before termination.
    """
    def __init__(self):
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.nt = C.WinDLL('ntdll', use_last_error=True)
        self.k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.k.OpenProcess.restype = W.HANDLE
        self.k.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(C.c_ulonglong)] * 4
        self.k.CloseHandle.argtypes = [W.HANDLE]
        self.nt.NtSuspendProcess.argtypes = [W.HANDLE]
        self.nt.NtSuspendProcess.restype = C.c_long
        self.nt.NtResumeProcess.argtypes = [W.HANDLE]
        self.nt.NtResumeProcess.restype = C.c_long
        self.identities = {}
        self.handles = []

    def __enter__(self):
        return self

    def add(self, pid, expected):
        if self.identities.get(pid) == expected:
            return
        if pid in self.identities:
            raise OSError('process identity changed during stop preparation')
        # QUERY_LIMITED_INFORMATION | SUSPEND_RESUME, no privilege escalation.
        handle = self.k.OpenProcess(0x1800, False, pid)
        if not handle:
            raise OSError('cannot open verified process for stop preparation')
        retained = False
        try:
            times = [C.c_ulonglong() for _ in range(4)]
            if not self.k.GetProcessTimes(handle, *[C.byref(t) for t in times]) or str(times[0].value) != expected:
                raise OSError('process identity changed before stop preparation')
            if self.nt.NtSuspendProcess(handle) < 0:
                raise OSError('cannot pause verified process for stop preparation')
            self.handles.append(handle)
            self.identities[pid] = expected
            retained = True
        finally:
            if not retained:
                self.k.CloseHandle(handle)

    def __exit__(self, exc_type, exc, traceback):
        errors = []
        for handle in reversed(self.handles):
            try:
                status = self.nt.NtResumeProcess(handle)
                # Terminated instances no longer need resuming. GetProcessTimes
                # exposes a nonzero exit time on the exact retained handle.
                if status < 0:
                    times = [C.c_ulonglong() for _ in range(4)]
                    exited = self.k.GetProcessTimes(handle, *[C.byref(t) for t in times]) and times[1].value
                    if not exited:
                        errors.append(status)
            finally:
                self.k.CloseHandle(handle)
        self.handles.clear()
        if errors:
            raise OSError('could not resume a process after stop preparation')
        return False


def terminate_verified(identities):
    """Force only explicitly verified instances; never traverse raw PPIDs."""
    k = C.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k.OpenProcess.restype = W.HANDLE
    k.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(C.c_ulonglong)] * 4
    k.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
    k.CloseHandle.argtypes = [W.HANDLE]
    errors = []
    for pid, expected in sorted(identities.items(), key=lambda item: int(item[1]), reverse=True):
        handle = k.OpenProcess(0x1001, False, pid)
        if not handle:
            if C.get_last_error() != 87:  # Already exited.
                errors.append(pid)
            continue
        try:
            times = [C.c_ulonglong() for _ in range(4)]
            if not k.GetProcessTimes(handle, *[C.byref(t) for t in times]) or str(times[0].value) != expected:
                errors.append(pid)
                continue
            if not k.TerminateProcess(handle, 1):
                errors.append(pid)
        finally:
            k.CloseHandle(handle)
    return errors


def listeners():
    """TCP owner-PID tables; an API failure is unknown, never an empty scan."""
    ip = C.WinDLL('iphlpapi')
    fn = ip.GetExtendedTcpTable
    fn.argtypes = [C.c_void_p, C.POINTER(W.DWORD), W.BOOL, W.ULONG, C.c_int, W.ULONG]
    fn.restype = W.DWORD
    found = {}
    for family, row_size in [(2, 24), (23, 56)]:
        size = W.DWORD()
        code = fn(None, C.byref(size), False, family, 3, 0)
        if code not in (0, 122):
            raise OSError(code, '无法读取 TCP 监听表')
        for _ in range(3):
            buf = C.create_string_buffer(max(4, size.value))
            code = fn(buf, C.byref(size), False, family, 3, 0)
            if code != 122:
                break
        if code:
            raise OSError(code, 'TCP 监听表采集失败')
        count = W.DWORD.from_buffer(buf).value
        if 4+count*row_size > len(buf):
            raise OSError('TCP 表长度无效')
        for i in range(count):
            offset = 4+i*row_size
            if family == 2:
                host = socket.inet_ntop(socket.AF_INET, bytes(buf[offset+4:offset+8]))
                port = socket.ntohs(W.DWORD.from_buffer(buf, offset+8).value & 0xffff)
                pid = W.DWORD.from_buffer(buf, offset+20).value
            else:
                host = socket.inet_ntop(socket.AF_INET6, bytes(buf[offset:offset+16]))
                port = socket.ntohs(W.DWORD.from_buffer(buf, offset+20).value & 0xffff)
                pid = W.DWORD.from_buffer(buf, offset+52).value
            found.setdefault((pid, port), set()).add(host)
    return found
