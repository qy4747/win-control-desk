"""Repeatable Windows idle acceptance, isolated from the user's configuration.

py -3 tools/measure_idle.py --seconds 1800 --output tmp/idle-acceptance.json
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import sys
import statistics
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from win_metrics import Metrics, ProcessMemory
from tools.win_anchor import _snapshot_ppids


def worker(output):
    import server
    from ops_monitor import Monitor
    collect = Monitor.collect
    count = 0
    def measured(self):
        nonlocal count
        collect(self)
        count += 1
        if count == 7:
            self.emit(dict(key='acceptance', target='system', title='总控台验收通知',
                           detail='后台通知测试，无需操作', phase='test', muted=False))
        with open(output, 'a', encoding='utf8') as f:
            f.write(json.dumps(dict(at=time.time(), durationMs=self.state['collectorDurationMs'],
                                    notifications=self.notifier.status))+'\n')
    Monitor.collect = measured
    server.main(preferred_port=9608, open_browser=False)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--seconds', type=int, default=1800)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.seconds < 20:
        p.error('--seconds must be at least 20')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cddeck-perf-') as td:
        env = dict(os.environ, CONSOLE_DATA_DIR=os.path.join(td, 'data'),
                   CONSOLE_LOG_DIR=os.path.join(td, 'logs'), CONSOLE_NOTIFICATIONS='1')
        from ops_model import DEFAULT_RULES
        os.makedirs(env['CONSOLE_DATA_DIR'])
        Path(env['CONSOLE_DATA_DIR'], 'config.json').write_text(json.dumps({
            'schemaVersion': 2, 'apps': [], 'rules': [dict(r, muted=True) for r in DEFAULT_RULES]}), encoding='utf8')
        collector_path = os.path.join(td, 'collections.jsonl')
        with open(os.path.join(td, 'console.log'), 'wb') as log:
            proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', collector_path],
                                    cwd=ROOT, env=env, stdout=log, stderr=log, creationflags=0x08000000)
            metrics = Metrics()
            previous = {}
            samples = []
            start = last = time.monotonic()
            try:
                while time.monotonic()-start < args.seconds:
                    if proc.poll() is not None:
                        raise RuntimeError('验收后台意外退出')
                    time.sleep(min(1, max(.1, args.seconds-(time.monotonic()-start))))
                    now = time.monotonic()
                    table = _snapshot_ppids()
                    pids = {proc.pid}
                    while True:
                        more = {pid for pid, ppid in table.items() if ppid in pids}
                        if more <= pids:
                            break
                        pids.update(more)
                    rss, delta = 0, 0
                    current = {}
                    for pid in pids:
                        handle = metrics.k.OpenProcess(0x1000, False, pid)
                        if not handle:
                            continue
                        try:
                            times = [C.c_ulonglong() for _ in range(4)]
                            if not metrics.k.GetProcessTimes(handle, *[C.byref(t) for t in times]):
                                continue
                            key = (pid, times[0].value)
                            ticks = times[2].value+times[3].value
                            if key in previous:
                                delta += max(0, ticks-previous[key])
                            current[key] = ticks
                            mem = ProcessMemory(); mem.cb = C.sizeof(mem)
                            if metrics.k.K32GetProcessMemoryInfo(handle, C.byref(mem), mem.cb):
                                rss += mem.working
                        finally:
                            metrics.k.CloseHandle(handle)
                    if previous:
                        samples.append(dict(elapsedSec=now-start, cpu=delta/1e7/(now-last)*100/(os.cpu_count() or 1),
                                            memoryBytes=rss, processes=len(pids)))
                    previous, last = current, now
                collections = [json.loads(line) for line in Path(collector_path).read_text(encoding='utf8').splitlines()]
                early = [s['memoryBytes'] for s in samples if 60 <= s['elapsedSec'] < 360]
                late = [s['memoryBytes'] for s in samples if s['elapsedSec'] > args.seconds-300]
                result = dict(durationSec=time.monotonic()-start, samples=samples,
                              averageCpu=sum(s['cpu'] for s in samples)/max(1, len(samples)),
                              maxMemoryBytes=max((s['memoryBytes'] for s in samples), default=0),
                              memoryChangeBytes=statistics.mean(late)-statistics.mean(early) if early and late else None,
                              collections=collections, notificationDeliveryExcluded=False,
                              averageCollectionMs=statistics.mean(c['durationMs'] for c in collections),
                              maxCollectionMs=max(c['durationMs'] for c in collections),
                              notificationStatus=collections[-1]['notifications'])
                result['passed'] = result['averageCpu'] <= 1 and result['maxMemoryBytes'] <= 150*1024*1024
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
                print(json.dumps({k: v for k, v in result.items() if k not in ('samples', 'collections')}))
            finally:
                # This isolated acceptance process has no managed applications.
                proc.terminate()
                proc.wait(timeout=10)
                metrics.close()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        worker(sys.argv[2])
    else:
        main()
