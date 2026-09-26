"""Configure real app cards through the running console; never launch/stop apps."""
import argparse
import copy
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ops_model import validate_app_extra
from server import validate_app_fields, validate_stop_action


class Client:
    def __init__(self, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise ValueError('仅使用 http://127.0.0.1:端口')
        self.url = url.rstrip('/')
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.state = self.request('GET', '/api/state')
        if self.state.get('version') == 'demo' or Path(self.state.get('consoleCwd', '')).resolve() != ROOT:
            raise ValueError('目标不是本项目的正式总控台；不能写入演示服务')
        if not self.state.get('sampledAt') or self.state.get('stale'):
            raise ValueError('采集尚未就绪，请稍后重试')

    def request(self, method, route, data=None):
        req = urllib.request.Request(self.url+route, method=method,
            data=json.dumps(data, ensure_ascii=False).encode('utf8') if data is not None else None,
            headers={'Content-Type': 'application/json', 'Origin': self.url, 'Sec-Fetch-Site': 'same-origin'})
        try:
            with self.opener.open(req, timeout=30) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            raise ValueError(f'{route}: {error.read().decode("utf8", errors="replace")}') from None
        if result.get('ok') is False:
            raise ValueError(result.get('error', '操作失败'))
        return result


def prepare(spec, current, processes, windows):
    """Pure plan preparation: preserve existing settings unless explicitly supplied."""
    if not isinstance(spec, dict) or not isinstance(spec.get('name'), str) or not spec['name'].strip():
        raise ValueError('每个应用需要 name')
    if 'followInstance' in spec and type(spec['followInstance']) is not bool:
        raise ValueError('followInstance 必须是布尔值')
    fields = {k: copy.deepcopy(spec[k]) for k in ('name', 'command', 'cwd', 'port', 'kind', 'shell', 'category', 'glyph', 'probe', 'alertPolicy', 'cardButtons', 'stopAction') if k in spec}
    process = None
    if 'pid' in spec:
        process = next((p for p in processes if p['pid'] == spec['pid'] and p['created'] == spec.get('created')), None)
        if process is None:
            raise ValueError(spec['name']+': PID/created 已变化，请重新发现')
        if current and current.get('running') and process['pid'] not in current.get('pids', []):
            raise ValueError(spec['name']+': 卡片已有另一运行实例，不能自动替换')
    if not current:
        fields.setdefault('kind', 'service' if fields.get('port') else 'desktop')
        fields.setdefault('shell', 'cmd')
        fields.setdefault('command', '')
        if process:
            exe = Path(process['exe'])
            fields.setdefault('cwd', str(exe.parent))
            # Interpreters need the actual entry script and working directory.
            if not fields['command'] and exe.name.lower() not in ('python.exe','pythonw.exe','node.exe','cmd.exe','powershell.exe','pwsh.exe','windowsterminal.exe','wt.exe','wsl.exe','bash.exe','conhost.exe','openconsole.exe'):
                fields['command'] = subprocess.list2cmdline([str(exe)])
    actions = copy.deepcopy((current or {}).get('actions', []))
    for item in spec.get('locations', []):
        path = item['path']
        if not isinstance(path, str) or not os.path.isabs(path) or not os.path.exists(path):
            raise ValueError(spec['name']+': 位置必须存在且为绝对路径：'+str(path))
        mode = item.get('mode', 'explorer')
        ident = item.get('id') or 'loc-' + hashlib.sha256((os.path.normcase(os.path.normpath(path))+'|'+mode).encode('utf8')).hexdigest()[:12]
        action = dict(item, id=ident, type='location', when=item.get('when', 'always'))
        actions = [a for a in actions if a['id'] != ident] + [action]
    if 'actions' in spec:
        for action in spec['actions']:
            actions = [a for a in actions if a['id'] != action['id']] + [action]
    fields['actions'] = validate_app_extra({'actions': actions})['actions']
    selected = spec.get('window', (current or {}).get('windowBinding'))
    if 'window' in spec and selected is not None:
        if not isinstance(selected, dict) or not any(all(w[k] == selected.get(k) for k in ('hwnd','pid','created','exe')) for w in windows):
            raise ValueError(spec['name']+': 窗口身份已变化，请重新选择')
    if 'cardButtons' not in fields and (not current or 'front' in spec):
        service = fields.get('kind', (current or {}).get('kind', 'service')) == 'service'
        front = spec.get('front')
        if front is None:
            front = ((['web'] if not service and fields.get('port', (current or {}).get('port')) else [])
                + ['custom:'+a['id'] for a in fields['actions'] if a['id'] != fields.get('stopAction', (current or {}).get('stopAction'))] + ['details', 'logs'])[:2]
        if not isinstance(front, list) or len(front) > 2 or len(set(front)) != len(front):
            raise ValueError('front 最多 2 个不重复的软件专用动作；打开/关闭与端口或前台由系统固定')
        choices = {'restart','web','logs','details'} | {'custom:'+a['id'] for a in actions}
        if any(action not in choices for action in front):
            raise ValueError('front 引用了不存在的动作或尚未关联的窗口')
        front = ['toggle', 'web' if service else 'window:focus'] + [a for a in front if not (service and a == 'web')]
        menu = ['custom:'+a['id'] for a in actions if a['id'] != fields.get('stopAction', (current or {}).get('stopAction'))]
        menu += ['details', 'logs', 'restart']
        fields['cardButtons'] = [dict(action=action, name='', placement='primary' if index==0 else 'card',
            when='always') for index,action in enumerate(front)]
        fields['cardButtons'] += [dict(action=action, name='', placement='menu',
            when='always') for action in menu if action not in front]
    validate_app_extra(fields)
    fields, error = validate_app_fields(fields, partial=bool(current))
    if error:
        raise ValueError(spec['name']+': '+error)
    validate_stop_action(dict(current or {}, **fields))
    if current and current.get('running'):
        for key in ('command','cwd','port','kind','shell'):
            if key in fields and fields[key] != current.get(key):
                raise ValueError(f'{spec["name"]}: 运行中不能改 {key}；本工具不会自动停止应用')
    return fields, process


def verification(state, windows=()):
    issues = []
    for app in state['apps']:
        for action in app.get('actions', []):
            if action.get('type') == 'location' and not os.path.exists(action['path']):
                issues.append(app['name']+'：位置不存在 '+action['path'])
        if app.get('health', {}).get('blocking'):
            issues.append(app['name']+'：启动配置不可用')
        binding = app.get('windowBinding')
        if binding and not binding.get('match') and not any(all(w[k] == binding.get(k) for k in ('hwnd','pid','created','exe')) for w in windows):
            issues.append(app['name']+'：关联窗口已失效，需要重新选择')
    return dict(apps=[dict(id=a['id'],name=a['name'],running=a.get('running'),
        locations=sum(x.get('type')=='location' for x in a.get('actions',[])),window=bool(a.get('windowBinding')),
        probe=a.get('probeState',{}).get('status')) for a in state['apps']], issues=issues)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:9600')
    sub = parser.add_subparsers(dest='operation', required=True)
    discover = sub.add_parser('discover'); discover.add_argument('query', nargs='?', default='')
    apply = sub.add_parser('apply'); apply.add_argument('plan', type=Path); apply.add_argument('--write', action='store_true')
    sub.add_parser('verify')
    args = parser.parse_args()
    client = Client(args.url)
    if args.operation == 'verify':
        print(json.dumps(verification(client.state, client.request('GET','/api/ops/windows')['items']), ensure_ascii=False, indent=2)); return
    processes = client.request('GET','/api/ops/discover?all=1')['items']
    windows = client.request('GET','/api/ops/windows')['items']
    if args.operation == 'discover':
        query = args.query.casefold()
        selected = [p for p in processes if query in (str(p['pid'])+' '+p['name']+' '+p['exe']).casefold()]
        pids = {p['pid'] for p in selected}
        result = dict(processes=[{k:p[k] for k in ('pid','created','name','exe','ports','kind')} for p in selected],
            windows=[w for w in windows if w['pid'] in pids or query in w['title'].casefold()],
            cards=[dict(id=a['id'],name=a['name'],running=a.get('running')) for a in client.state['apps']])
        print(json.dumps(result,ensure_ascii=False,indent=2)); return
    plan = json.loads(args.plan.read_text(encoding='utf-8-sig'))
    if not isinstance(plan, dict) or not isinstance(plan.get('apps'), list) or not plan['apps']:
        raise ValueError('计划格式应为 {"apps": [...]}')
    prepared, seen = [], set()
    for spec in plan['apps']:
        candidates = [a for a in client.state['apps'] if a['id']==spec.get('appId')] if spec.get('appId') else [a for a in client.state['apps'] if a['name']==spec.get('name')]
        if len(candidates)>1: raise ValueError('有同名卡片，请指定 appId')
        if spec.get('appId') and not candidates: raise ValueError('appId 不存在')
        current = candidates[0] if candidates else None
        key = current['id'] if current else spec['name']
        if key in seen: raise ValueError('同一张卡片在计划中重复')
        seen.add(key)
        fields, process = prepare(spec, current, processes, windows)
        prepared.append((spec,current,fields,process))
    if not args.write:
        print(json.dumps(dict(write=False,changes=[dict(name=s['name'],operation='update' if a else 'create',
            pid=p['pid'] if p else None,locations=sum(x['type']=='location' for x in f['actions']),buttons=f.get('cardButtons','保留原布局'),window='window' in s) for s,a,f,p in prepared]),ensure_ascii=False,indent=2)); return
    config = Path(client.state['dataDir'])/'config.json'
    backup = config.with_name('config.before-apps-'+time.strftime('%Y%m%d-%H%M%S')+'-'+str(time.time_ns()%1000000)+'.json')
    shutil.copy2(config,backup)
    completed = []
    try:
        for spec,current,fields,process in prepared:
            if current:
                saved = client.request('PUT','/api/apps/'+current['id'],fields)
                if process and not current.get('running'):
                    saved = client.request('POST','/api/ops/discover/import',dict(appId=current['id'],pid=process['pid'],created=process['created']))
            elif process:
                saved = client.request('POST','/api/ops/discover/import',dict(fields,pid=process['pid'],created=process['created']))
            else:
                saved = client.request('POST','/api/apps',fields)
            completed.append(dict(id=saved['id'],name=spec['name']))
            if 'window' in spec:
                client.request('POST','/api/ops/window/bind',dict(appId=saved['id'],window=spec['window']))
            if 'followInstance' in spec:
                client.request('POST','/api/ops/instance',dict(appId=saved['id'],enabled=spec['followInstance']))
    except Exception:
        print(json.dumps(dict(backup=str(backup),completed=completed,error='已停止后续写入；不回滚或启停应用，修正计划后继续'),ensure_ascii=False),file=sys.stderr)
        raise
    print(json.dumps(dict(ok=True,backup=str(backup),saved=completed,next='运行 verify 检查最新采集结果'),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    try: main()
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print(str(exc),file=sys.stderr); sys.exit(1)
