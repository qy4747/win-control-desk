"""Explicit script stop: terminate only instances supplied by the console.

Never look up targets by executable name or port. Configure as a script action
with when=running, then select it as the card's stopAction.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from win_metrics import terminate_verified


def stop(context, terminate=terminate_verified):
    rows = context.get('processes')
    if not context.get('appId') or not isinstance(rows, list) or not rows:
        raise ValueError('没有可确认的应用进程，未执行关闭')
    identities = {}
    for row in rows:
        pid, created = row.get('pid'), row.get('created')
        if type(pid) is not int or pid <= 0 or not isinstance(created, str) or not created.isdigit():
            raise ValueError('应用进程身份无效，未执行关闭')
        if pid in identities or pid == os.getpid():
            raise ValueError('应用进程列表无效，未执行关闭')
        identities[pid] = created
    errors = terminate(identities)
    if errors:
        raise RuntimeError('身份变化或关闭被拒绝，PID: ' + ', '.join(map(str, errors)))
    print('已结束已核实的应用实例：' + ', '.join(map(str, identities)))


if __name__ == '__main__':
    try:
        stop(json.loads(os.environ.get('CDDECK_APP_CONTEXT', '{}')))
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
