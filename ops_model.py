"""Small JSON contracts shared by configuration, actions and monitoring."""
import ipaddress
import math
import os
import re
import sys
import urllib.parse
import urllib.request

DEFAULT_RULES = [
    dict(id='system-cpu', name='整机 CPU', metric='cpu', threshold=90, durationSec=60, intervalSec=10, muted=False),
    dict(id='system-memory', name='整机内存', metric='memoryPercent', threshold=90, durationSec=60, intervalSec=10, muted=False),
    dict(id='disk-free', name='磁盘剩余空间', metric='diskFreePercent', threshold=10, durationSec=60, intervalSec=60, muted=False),
]
APP_FIELDS = dict(category='', actions=[], probe=None, alertPolicy={},
                  externalIdentity=None, expectedRunning=False, startedAt=None,
                  stopAction=None, cardButtons=None, windowBinding=None, instanceMatch=None)
METRICS = {'cpu', 'memoryPercent', 'memoryBytes', 'diskFreePercent',
           'diskWriteBytesPerSec', 'diskWriteBytes', 'directoryBytes',
           'directoryGrowthBytes', 'directorySnapshotGrowthBytes', 'gpuPercent'}


def number(value, label, low=0, high=1e18):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(label + ' 数值超出范围')
    return value


def text(value, label, maximum=4096, empty=False):
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value or (not empty and not value.strip()):
        raise ValueError(label + ' 无效')
    return value.strip()


def local_url(value):
    value = text(value, '本机 URL')
    try:
        p = urllib.parse.urlsplit(value)
        if p.scheme not in ('http', 'https') or p.username or p.password or p.fragment:
            raise ValueError()
        if p.hostname != 'localhost' and not ipaddress.ip_address(p.hostname or '').is_loopback:
            raise ValueError()
        if p.port is not None and not 1 <= p.port <= 65535:
            raise ValueError()
        # Pin localhost to a numeric loopback; environment proxies are disabled below.
        if p.hostname == 'localhost':
            value = urllib.parse.urlunsplit((p.scheme, '127.0.0.1' + (':' + str(p.port) if p.port else ''), p.path, p.query, ''))
    except (ValueError, TypeError):
        raise ValueError('HTTP 地址必须是本机回环地址') from None
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('本机动作不允许重定向')


def http_action(spec):
    req = urllib.request.Request(local_url(spec['url']),
        data=spec.get('body', '').encode('utf-8') if spec.get('body') else None,
        headers=spec.get('headers', {}), method=spec.get('method', 'GET'))
    with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(
            req, timeout=spec.get('timeoutSec', 5)) as response:
        return {'ok': 200 <= response.status < 300, 'status': response.status}


def validate_http(spec, probe=False):
    if not isinstance(spec, dict):
        raise ValueError('HTTP 配置必须是对象')
    out = dict(url=local_url(spec.get('url')), method=spec.get('method', 'GET'),
               timeoutSec=number(spec.get('timeoutSec', 5), '超时', 1, 60))
    if out['method'] not in ('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE') or (probe and out['method'] not in ('GET', 'HEAD')):
        raise ValueError('HTTP 方法不适用')
    headers = spec.get('headers', {})
    if not isinstance(headers, dict) or len(headers) > 32:
        raise ValueError('HTTP 请求头无效')
    for key, value in headers.items():
        if not re.fullmatch(r'[A-Za-z0-9-]+', key) or not isinstance(value, str) or '\r' in value or '\n' in value or len(value) > 8192:
            raise ValueError('HTTP 请求头无效')
        if key.lower() in ('host', 'content-length', 'transfer-encoding'):
            raise ValueError('此请求头由客户端管理')
    out['headers'] = dict(headers)
    out['body'] = text(spec.get('body', ''), '请求体', 65536, empty=True)
    return out


def script_command(action):
    path = action['path']
    if path.lower().endswith('.ps1'):
        return "& '" + path.replace("'", "''") + "'", 'powershell'
    argv = [action.get('python') or sys.executable, path]
    if os.name == 'nt':
        return '& ' + ' '.join("'" + arg.replace("'", "''") + "'" for arg in argv), 'powershell'
    import shlex
    return shlex.join(argv), 'bash'


def validate_app_extra(data):
    fields = {}
    if 'cardButtons' in data:
        buttons = data['cardButtons']
        if buttons is not None and (not isinstance(buttons, list) or len(buttons) > 30):
            raise ValueError('卡片按钮最多 30 个')
        fields['cardButtons'] = None if buttons is None else []
        for b in buttons or []:
            if not isinstance(b, dict):
                raise ValueError('卡片按钮无效')
            action = text(b.get('action'), '按钮动作', 80)
            if action not in ('toggle', 'start', 'stop', 'restart', 'web', 'logs', 'details', 'window:focus', 'window:pin', 'window:unpin') and not re.fullmatch(r'custom:[\w-]{1,40}', action):
                raise ValueError('按钮动作无效')
            placement, when = b.get('placement', 'card'), b.get('when', 'always')
            if placement not in ('primary', 'card', 'menu') or when not in ('always', 'running', 'stopped'):
                raise ValueError('按钮位置或可用状态无效')
            fields['cardButtons'].append(dict(action=action, name=text(b.get('name', ''), '按钮名称', 80, empty=True), placement=placement, when=when))
        if sum(b['placement'] == 'primary' for b in fields['cardButtons'] or []) > 1:
            raise ValueError('只能设置一个主按钮')
    if 'category' in data:
        fields['category'] = text(data['category'], '分类', 80, empty=True)
    if 'probe' in data:
        fields['probe'] = validate_http(data['probe'], True) if data['probe'] else None
    if 'actions' in data:
        if not isinstance(data['actions'], list) or len(data['actions']) > 30:
            raise ValueError('最多保存 30 个操作')
        actions, ids = [], set()
        for action in data['actions']:
            if not isinstance(action, dict):
                raise ValueError('操作必须是对象')
            ident = text(action.get('id'), '操作 ID', 40)
            if not re.fullmatch(r'[\w-]+', ident) or ident in ids:
                raise ValueError('操作 ID 无效或重复')
            ids.add(ident)
            a = dict(id=ident, name=text(action.get('name'), '操作名称', 80),
                     type=action.get('type'), when=action.get('when', 'always'))
            if a['when'] not in ('always', 'running', 'stopped'):
                raise ValueError('操作可用状态无效')
            if a['type'] == 'http':
                a.update(validate_http(action))
            elif a['type'] == 'command':
                a.update(command=text(action.get('command'), '操作命令', 16384),
                         shell=action.get('shell', 'cmd'),
                         timeoutSec=number(action.get('timeoutSec', 30), '超时', 1, 300))
                if a['shell'] not in ('cmd', 'powershell', 'bash'):
                    raise ValueError('操作解释器无效')
            elif a['type'] == 'script':
                a.update(path=text(action.get('path'), '脚本路径'),
                         python=text(action.get('python', ''), 'Python 解释器', empty=True),
                         timeoutSec=number(action.get('timeoutSec', 30), '超时', 1, 300))
                if not os.path.isabs(a['path']) or not a['path'].lower().endswith(('.ps1', '.py')):
                    raise ValueError('脚本需要 .ps1 或 .py 文件的绝对路径')
                if a['path'].lower().endswith('.ps1') and os.name != 'nt':
                    raise ValueError('PowerShell 脚本仅支持 Windows')
                if a['python'] and not os.path.isabs(a['python']):
                    raise ValueError('Python 解释器需要绝对路径')
            elif a['type'] == 'url':
                url = text(action.get('url'), 'URL')
                if urllib.parse.urlsplit(url).scheme not in ('http', 'https'):
                    raise ValueError('打开地址仅支持 HTTP/HTTPS')
                a['url'] = url
            elif a['type'] == 'location':
                a.update(path=text(action.get('path'), '位置路径'),
                         mode=action.get('mode', 'explorer'),
                         editor=text(action.get('editor', ''), '编辑器路径', empty=True))
                if not os.path.isabs(a['path']) or a['mode'] not in ('explorer', 'terminal', 'editor'):
                    raise ValueError('位置需要绝对路径，打开方式为 explorer/terminal/editor')
                if a['editor'] and (not os.path.isabs(a['editor']) or (os.name == 'nt' and not a['editor'].lower().endswith('.exe'))):
                    raise ValueError('编辑器需要可执行文件的绝对路径（Windows 为 .exe）')
            else:
                raise ValueError('操作类型必须是 command/script/http/url/location')
            actions.append(a)
        fields['actions'] = actions
    if 'stopAction' in data:
        fields['stopAction'] = text(data['stopAction'], '退出操作', 40) if data['stopAction'] else None
    if 'alertPolicy' in data:
        policy = data['alertPolicy']
        if not isinstance(policy, dict):
            raise ValueError('告警配置必须是对象')
        p = dict(exitPolicy=policy.get('exitPolicy', 'default'),
                 graceSec=number(policy.get('graceSec', 30), '启动宽限', 0, 3600),
                 durationSec=number(policy.get('durationSec', 60), '持续时间', 0, 86400))
        if p['exitPolicy'] not in ('default', 'always', 'never'):
            raise ValueError('退出报警规则无效')
        for key, maximum in [('cpuPercent', 100), ('memoryBytes', 1e15)]:
            p[key] = number(policy[key], key, 0, maximum) if policy.get(key) is not None else None
        p['muted'] = policy.get('muted', [])
        if not isinstance(p['muted'], list) or any(k not in ('exit', 'config', 'port', 'http', 'cpu', 'memory') for k in p['muted']):
            raise ValueError('静音规则无效')
        fields['alertPolicy'] = p
    return fields


def validate_rules(items):
    if not isinstance(items, list) or len(items) > 100:
        raise ValueError('基线规则必须是列表，最多 100 条')
    result, ids = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('规则必须是对象')
        r = dict(id=text(item.get('id'), '规则 ID', 80), name=text(item.get('name'), '规则名称', 80),
                 metric=item.get('metric'), threshold=number(item.get('threshold'), '阈值'),
                 durationSec=number(item.get('durationSec', 60), '持续时间', 0, 86400),
                 intervalSec=number(item.get('intervalSec', 10), '采样间隔', 2, 86400),
                 recoveryThreshold=number(item.get('recoveryThreshold', item.get('threshold')), '恢复阈值'),
                 windowSec=number(item.get('windowSec', 60), '增量窗口', 10,
                                  604800 if item.get('metric') == 'directorySnapshotGrowthBytes' else 86400),
                 muted=item.get('muted', False), path=item.get('path', ''))
        if r['metric'] not in METRICS or not re.fullmatch(r'[\w-]+', r['id']) or r['id'] in ids or type(r['muted']) is not bool:
            raise ValueError('规则指标、ID 或静音设置无效')
        if (r['metric'] == 'diskFreePercent' and r['recoveryThreshold'] < r['threshold']) or (r['metric'] != 'diskFreePercent' and r['recoveryThreshold'] > r['threshold']):
            raise ValueError('恢复阈值应位于正常一侧')
        if r['metric'].startswith('directory'):
            import os
            r['path'] = text(r['path'], '目录')
            if not os.path.isabs(r['path']) or r['path'].startswith(('\\\\', '//')) or os.path.dirname(os.path.abspath(r['path'])) == os.path.abspath(r['path']):
                raise ValueError('请选择本地专用子目录，不能使用磁盘根目录')
            if os.name == 'nt':
                import ctypes
                drive = os.path.splitdrive(os.path.abspath(r['path']))[0]+'\\'
                if ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive)) not in (2, 3, 6):
                    raise ValueError('目录必须位于可用的本地磁盘，不能使用网络映射盘')
            r['intervalSec'] = max(900, r['intervalSec'])
        if r['metric'] == 'directorySnapshotGrowthBytes':
            times = item.get('dailyTimes', ['03:00', '08:00', '12:30', '21:00'])
            if (not isinstance(times, list) or not 1 <= len(times) <= 4 or
                    any(not isinstance(t, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', t) for t in times)):
                raise ValueError('每天设置 1 至 4 个采样时刻，格式为 HH:MM')
            if r['windowSec'] not in (86400, 604800):
                raise ValueError('定时快照比较窗口为 24 小时或 7 天')
            r.update(dailyTimes=sorted(set(times)), durationSec=0)
        if r['metric'] == 'diskFreePercent':
            r['intervalSec'] = max(60, r['intervalSec'])
        ids.add(r['id'])
        result.append(r)
    return result


def validate_stop_action(app):
    if app.get('stopAction') and not any(a['id'] == app['stopAction'] and a['type'] in ('command', 'script', 'http')
            and a.get('when') != 'stopped' for a in app.get('actions', [])):
        raise ValueError('退出操作必须引用一个运行时可用的命令或 HTTP 操作')


def validate_presets(items, apps, rules):
    if not isinstance(items, list) or len(items) > 30:
        raise ValueError('最多保存 30 个预设')
    app_ids = {a['id'] for a in apps}
    rule_ids = {r['id'] for r in rules}
    result, ids = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('预设必须是对象')
        p = dict(id=text(item.get('id'), '预设 ID', 80), name=text(item.get('name'), '预设名称', 80), steps=[])
        p['type'] = item.get('type', 'scene')
        if p['type'] not in ('scene', 'package'):
            raise ValueError('请选择场景或预设包')
        if not re.fullmatch(r'[\w-]+', p['id']) or p['id'] in ids or not isinstance(item.get('steps'), list) or len(item['steps']) > 200:
            raise ValueError('预设重复或步骤无效')
        seen = set()
        for step in item['steps']:
            if not isinstance(step, dict) or step.get('appId') not in app_ids or step.get('appId') in seen or step.get('action') not in ('start', 'stop', 'keep'):
                raise ValueError('预设对象或操作无效，同一对象只能出现一次')
            seen.add(step['appId'])
            if p['type'] == 'package' and (step['action'] != 'start' or next(a for a in apps if a['id'] == step['appId']).get('kind') == 'task'):
                raise ValueError('预设包仅包含常驻应用，不能包含一次性任务或场景操作')
            p['steps'].append(dict(appId=step['appId'], action=step['action']))
        # Empty packages retain their name and scene references; UI disables them.
        p['packageSteps'] = item.get('packageSteps', [])
        if not isinstance(p['packageSteps'], list) or len(p['packageSteps']) > 30:
            raise ValueError('场景的预设包操作无效')
        packages_seen = set()
        for step in p['packageSteps']:
            if (not isinstance(step, dict) or not isinstance(step.get('packageId'), str) or
                    step['packageId'] in packages_seen or step.get('action') not in ('start', 'stop')):
                raise ValueError('场景的预设包重复或操作无效')
            packages_seen.add(step['packageId'])
        p['packageSteps'] = [dict(packageId=s['packageId'], action=s['action']) for s in p['packageSteps']]
        p['timeoutSec'] = number(item.get('timeoutSec', 30), '就绪超时', 1, 300)
        p['ruleOverrides'] = item.get('ruleOverrides', {})
        if not isinstance(p['ruleOverrides'], dict) or any(k not in rule_ids for k in p['ruleOverrides']):
            raise ValueError('预设基线覆盖不存在')
        for v in p['ruleOverrides'].values():
            number(v, '预设阈值')
        p['appOverrides'] = item.get('appOverrides', {})
        if not isinstance(p['appOverrides'], dict) or any(k not in app_ids for k in p['appOverrides']):
            raise ValueError('预设应用覆盖不存在')
        p['appOverrides'] = {k: validate_app_extra({'alertPolicy': v})['alertPolicy'] for k, v in p['appOverrides'].items()}
        if p['type'] == 'package' and (p['packageSteps'] or p['ruleOverrides'] or p['appOverrides']):
            raise ValueError('预设包只管理应用开关，不能包含其他包或场景基线')
        ids.add(p['id'])
        result.append(p)
    for p in result:
        if p['type'] == 'scene':
            preset_steps(p, result)
    return result


def reconcile_app_presets(config, app_id):
    app = next((a for a in config['apps'] if a['id'] == app_id), None)
    for preset in config.get('presets', []):
        if app is None or (app.get('kind') == 'task' and preset.get('type') == 'package'):
            preset['steps'] = [s for s in preset['steps'] if s['appId'] != app_id]
        if app is None:
            preset.get('appOverrides', {}).pop(app_id, None)
    config['presets'] = validate_presets(config.get('presets', []), config['apps'], config.get('rules', []))


def preset_steps(preset, presets, action=None):
    """Expand packages once; explicit app steps are scene exceptions."""
    if preset.get('type') == 'package':
        if action not in ('start', 'stop'):
            raise ValueError('预设包需要明确打开或关闭')
        return [dict(appId=s['appId'], action=action) for s in preset['steps']]
    if action is not None:
        raise ValueError('场景不接受预设包开关操作')
    explicit = {s['appId']: dict(s) for s in preset['steps']}
    expanded = {}
    for group in preset.get('packageSteps', []):
        package = next((p for p in presets if p['id'] == group['packageId'] and p.get('type') == 'package'), None)
        if package is None:
            raise ValueError('场景引用的预设包不存在，请先移除引用')
        for member in package['steps']:
            ident = member['appId']
            if ident in explicit:
                continue
            if ident in expanded and expanded[ident]['action'] != group['action']:
                raise ValueError('多个预设包对同一应用的操作冲突，请为该应用明确指定操作')
            expanded[ident] = dict(appId=ident, action=group['action'])
    expanded.update(explicit)
    return sorted(expanded.values(), key=lambda s: 0 if s['action'] == 'stop' else 1)
