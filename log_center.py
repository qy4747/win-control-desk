"""On-demand log directory inventory. No writer, worker or process sampling."""
import os
import re
import stat
import threading
import time


TAIL = 64 * 1024
HEAD = 4 * 1024
ERROR = re.compile(r"error|exception|traceback|fatal|错误|失败", re.I)


def _inspect(path, size):
    """One bounded tail and, only if necessary, the non-overlapping head."""
    with open(path, "rb") as stream:
        start = max(0, size - TAIL)
        head = stream.read(min(start, HEAD))
        stream.seek(start)
        tail = stream.read(TAIL)
    lines = tail.decode("utf-8", errors="replace").splitlines()
    return (lines[-1] if lines else "",
            sum(bool(ERROR.search(line)) for line in lines),
            b"\0" in head or b"\0" in tail)


class LogCenter:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.key = self.result = None
        self.samples = {}

    def summary(self, directory, apps):
        entries = [(app["id"], app.get("name") or app["id"]) for app in apps]
        key = (os.fspath(directory), tuple(entries))
        with self.lock:
            now = self.clock()
            if self.key == key and now - self.stamp < 15:
                return self.result
            if self.key is None or self.key[0] != key[0]:
                self.samples.clear()
            files = {}
            try:
                with os.scandir(directory) as listing:
                    for entry in listing:
                        try:
                            info = entry.stat(follow_symlinks=False)
                        except FileNotFoundError:
                            continue  # rotated during enumeration
                        if stat.S_ISREG(info.st_mode):
                            files[entry.name] = (entry.path, info)
            except FileNotFoundError:
                pass

            def row(app_id, name):
                current = backups = errors = 0
                modified = None
                last = ""
                nul = False
                for suffix in ("", ".1", ".2", ".3"):
                    file = files.get(f"{app_id}.log{suffix}")
                    if file is None:
                        continue
                    path, info = file
                    if suffix:
                        backups += info.st_size
                    else:
                        current = info.st_size
                    modified = max(modified or 0, info.st_mtime)
                    try:
                        line, count, zeros = _inspect(path, info.st_size)
                    except FileNotFoundError:
                        continue
                    if not last and line:
                        last = line
                    errors += count
                    nul |= zeros
                size = current + backups
                old, at, rate = self.samples.setdefault(app_id, (size, now, None))
                if now - at >= 60:
                    rate = round(max(0, size - old) * 3600 / (now - at))
                    self.samples[app_id] = (size, now, rate)
                return dict(appId=app_id, name=name, bytes=current, backupBytes=backups,
                            mtime=modified, growthBytesPerHour=rate, lastLine=last,
                            errorCount=errors, nulDetected=nul)

            rows = [row(*entry) for entry in entries]
            console = row("console", "总控台")
            active = {item["appId"] for item in [*rows, console]}
            self.samples = {k: v for k, v in self.samples.items() if k in active}
            self.result = dict(apps=rows, console=console,
                               totalBytes=sum(info.st_size for _, info in files.values()))
            self.key, self.stamp = key, now
            return self.result


log_center = LogCenter()
