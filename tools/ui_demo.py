"""Isolated UI acceptance server. Shared pure rules; no process control or config writes.

Run: py -3 tools/ui_demo.py --port 9610
All mutations live in memory; POST /api/demo/reset restores the fixtures.
"""
import argparse
import copy
import json
import mimetypes
import threading
import time
import uuid
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

STATIC = Path(__file__).resolve().parents[1] / 'static'
sys.path.insert(0, str(STATIC.parent))
from ops_model import validate_app_extra
from ops_monitor import Alerts
GIB = 1024 ** 3


def make_app(ident, name, category, **extra):
    app = dict(id=ident, name=name, category=category, kind='service', command='echo demo',
               shell='cmd', cwd='C:\\Demo\\' + ident, glyph='box', port=None, ports=[],
               running=False, listening=False, statusKnown=True, canStart=True,
               health=dict(status='ok', blocking=False, issues=[]), alerts=[],
               resources=dict(cpu=1.5, memoryBytes=256*1024**2), actions=[], cardButtons=None,
               probe=None, probeState=dict(status='not-configured'), alertPolicy={},
               associationState='managed', pids=[], lastExit=None, uptimeSec=3600)
    app.update(extra)
    return app


class Demo:
    def __init__(self, port):
        self.port = port
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.run_start = None
        self.logs = {}
        self.scenario = 'mixed'
        apps = [
            make_app('comfy', 'ComfyUI', 'AI 工具', running=True, listening=True, port=8188, ports=[8188], glyph='image',
                     probe=dict(url='http://127.0.0.1:8188/'), probeState=dict(status='ok'), resources=dict(cpu=18.4, memoryBytes=4*GIB),
                     actions=[dict(id='free', name='释放显存', type='http', url='http://127.0.0.1:8188/free', method='POST', when='running'),
                              dict(id='output', name='打开 Output', type='url', url='http://127.0.0.1:8188/output', when='always')],
                     cardButtons=[dict(action='stop', name='关闭', placement='card', when='running'),
                                  dict(action='web', name='打开 Web', placement='primary', when='running'),
                                  dict(action='start', name='启动', placement='card', when='stopped'),
                                  dict(action='custom:free', name='释放显存', placement='card', when='running'),
                                  dict(action='custom:output', name='打开 Output', placement='card', when='running')]),
            make_app('astrbot', 'AstrBot', 'AI 工具', running=True, listening=True, port=6185, ports=[6185], glyph='bot',
                     probe=dict(url='http://127.0.0.1:6185/health'), probeState=dict(status='error')),
            make_app('code', 'VS Code', '开发', kind='desktop', running=True, glyph='code', resources=dict(cpu=2.6, memoryBytes=1.2*GIB)),
            make_app('ollama', 'Ollama', 'AI 工具', port=11434, glyph='brain'),
            make_app('steam', 'Steam', '娱乐', kind='desktop', glyph='gamepad-2'),
            make_app('conflict', '端口冲突样例', '异常验收', port=8000, portConflict=True, portConflictApps=['另一个服务']),
            make_app('broken', '配置失效样例', '异常验收',
                     health=dict(status='error', blocking=True, issues=[dict(title='启动脚本不存在', detail='C:\\Demo\\missing.bat', fix='重新选择脚本')])),
            make_app('observe', '观察卡片（无启动命令）', '观察', kind='desktop', running=True, command='', canStart=False, glyph='eye', associationState='attached'),
            make_app('pending', '多实例待确认', '观察', statusKnown=False, associationState='pending'),
            make_app('backup', '每日备份 · 成功', '任务', kind='task', glyph='database', lastExit=dict(code=0, status='succeeded', at=(time.time()-600)*1000, durationSec=48)),
            make_app('failed', '转码任务 · 失败', '任务', kind='task', glyph='terminal', lastExit=dict(code=1, status='failed', at=(time.time()-180)*1000, durationSec=12)),
            make_app('export', '素材导出 · 执行中', '任务', kind='task', running=True, glyph='download'),
        ]
        for index, app in enumerate(apps):
            app['lastPid'] = 12000 + index
            app['pids'] = [app['lastPid']] if app['running'] else []
        rules = [dict(id='system-cpu', name='整机 CPU', metric='cpu', threshold=90, durationSec=60, intervalSec=10, muted=False),
                 dict(id='disk-free', name='磁盘剩余空间', metric='diskFreePercent', threshold=10, durationSec=60, intervalSec=60, muted=False)]
        themes = []
        theme_root = STATIC / 'themes'
        manifests = [(p, None) for p in sorted(theme_root.glob('*.json'))]
        manifests += [(p, p.parent.name) for p in sorted((theme_root / 'packs').glob('*/theme.json'))]
        for manifest, pack in manifests:
            meta = json.loads(manifest.read_text(encoding='utf-8'))
            ident = 'pack-' + pack if pack else meta['id']
            css = 'packs/' + pack + '/theme.css' if pack else ident + '.css'
            meta.update(id=ident, css='/themes/' + css)
            if pack:
                meta['kind'] = 'elements'
                preview = next((manifest.parent / ('preview.' + ext) for ext in ('webp', 'png', 'svg') if (manifest.parent / ('preview.' + ext)).is_file()), None)
                if preview:
                    meta['preview'] = '/themes/' + preview.relative_to(theme_root).as_posix()
            themes.append(meta)
        self.data = dict(apps=apps, services=[], watched=[], watchedKeywords=['ffmpeg'], consolePort=self.port,
            consolePid=99999, consoleCwd='演示：不读取真实工作目录', dataDir='仅内存，不写入正式配置', logsDir='演示日志',
            platform='win32', version='demo', schemaVersion=8, uiTheme='ops', themes=themes, degraded=False,
            degradedReasons=[], configHealth=dict(writable=True, issues=[]), stale=False, notificationStatus='disabled',
            system=dict(cpu=24.6, memoryPercent=58.2, diskWriteBytesPerSec=12*1024**2,
                        gpus=[dict(id='演示 GPU', dedicatedBytes=6*GIB, sharedBytes=512*1024**2)],
                        disks=[dict(path='C:\\', freeBytes=8*GIB, totalBytes=256*GIB), dict(path='D:\\', freeBytes=600*GIB, totalBytes=1024*GIB)]),
            directories={'C:\\Demo\\outputs': dict(status='ok', bytes=24*GIB)}, rules=rules,
            presets=[dict(id='daily', name='日常', steps=[dict(appId='code', action='start'), dict(appId='steam', action='stop')]),
                     dict(id='work', name='工作', steps=[dict(appId='steam', action='stop'), dict(appId='code', action='start'), dict(appId='ollama', action='start')]),
                     dict(id='game', name='游戏', steps=[dict(appId='comfy', action='stop'), dict(appId='ollama', action='stop'), dict(appId='steam', action='start')]),
                     dict(id='partial', name='部分失败验收', steps=[dict(appId='code', action='keep'), dict(appId='broken', action='start'), dict(appId='ollama', action='start')])],
            activePreset='daily', presetRun=None, alerts=[], events=[])
        self.alert_engine = Alerts(lambda event: self.event(event['target'], event['title'], event['detail'], event['phase'], event['key']))
        self.alert_rules = {}
        for target, key, title, value in [
            ('system', 'rule:disk-free:C', 'C 盘剩余空间不足', 3.1),
            ('comfy', 'app:comfy:memory', 'ComfyUI · 内存持续超限', 4*GIB),
            ('astrbot', 'app:astrbot:http', 'AstrBot · 接口持续不可用', '连续 3 次请求超时'),
            ('broken', 'app:broken:config', '配置失效样例 · 启动脚本不存在', '请重新选择启动脚本'),
            ('failed', 'app:failed:exit', '转码任务 · 执行失败', '退出码 1')]:
            rule = dict(name=title, appId=target, durationSec=0)
            if key.endswith(':memory'): rule.update(metric='memoryBytes', threshold=3*GIB)
            if target == 'system': rule.update(metric='diskFreePercent', threshold=10)
            self.alert_rules[key] = rule
            self.alert_engine.check(key, True, value, rule, time.monotonic())
            alert = dict(key=key, **self.alert_engine.states[key])
            self.data['alerts'].append(alert)
            if target != 'system':
                self.app(target)['alerts'].append(alert)
            self.event(target, title, str(value), phase='alert', key=key)
        self.extra_services = [dict(key='external-demo', pid=22001, port=8000, name='python.exe', project='未加入卡片的服务', group='mine', cpu=3.2, mem=1.8, uptimeSec=3200, cwd='C:\\Demo\\external', cmd='python app.py'),
                               dict(key='background-demo', pid=22002, port=9222, name='browser-helper.exe', group='background', cpu=.2, mem=.8, uptimeSec=400, cwd='C:\\Demo', cmd='browser-helper --port 9222'),
                               dict(key='hidden-demo', pid=22003, port=9333, name='hidden-worker.exe', group='mine', hidden=True, cpu=0, mem=.1, uptimeSec=500, cwd='C:\\Demo', cmd='hidden-worker')]

    def app(self, ident):
        return next(a for a in self.data['apps'] if a['id'] == ident)

    def event(self, target, title, detail, phase='action', key=None):
        self.data['events'].insert(0, dict(id=uuid.uuid4().hex, at=time.time(), target=target, title=title, detail=detail, phase=phase, key=key or 'demo:'+target))
        del self.data['events'][100:]
        self.logs.setdefault(target, []).append(time.strftime('%H:%M:%S') + '  ' + title + ' — ' + detail)
        self.logs[target] = self.logs[target][-100:]

    def operate(self, app, action):
        if action in ('start', 'restart') and (not app.get('canStart') or app.get('portConflict') or app['health']['blocking']):
            return dict(ok=False, error='演示失败：请先修复配置或端口冲突')
        app.update(running=action != 'stop', listening=action != 'stop' and bool(app.get('port')), lastExit=None)
        app['pids'] = [app['lastPid']] if app['running'] else []
        app['ports'] = [app['port']] if app['listening'] else []
        self.event(app['id'], app['name'], '模拟' + action)
        return dict(ok=True)

    def advance(self):
        run = self.data['presetRun']
        if not run or run['status'] != 'running':
            return
        elapsed = time.monotonic()-self.run_start
        for index, step in enumerate(run['steps']):
            if step['status'] not in ('waiting', 'running'):
                continue
            if elapsed >= (index+1)*3:
                app = self.app(step['appId'])
                if step['action'] == 'keep' or app['running'] == (step['action'] == 'start'):
                    step.update(status='skipped', detail='已满足目标状态')
                else:
                    result = self.operate(app, step['action'])
                    step.update(status='succeeded' if result['ok'] else 'failed', detail=result.get('error', '模拟操作完成'))
            elif elapsed >= index*3:
                step['status'] = 'running'
        if all(s['status'] not in ('waiting', 'running') for s in run['steps']):
            run['status'] = 'completed'

    def snapshot(self):
        self.advance()
        ids = {app['id'] for app in self.data['apps']}
        for key, rule in list(self.alert_rules.items()):
            if rule['appId'] != 'system' and rule['appId'] not in ids:
                self.alert_rules.pop(key)
                self.alert_engine.states.pop(key, None)
                self.alert_engine.overrides.pop(key, None)
                continue
            old = self.alert_engine.states[key]
            target, value = rule['appId'], old['value']
            app = self.app(target) if target != 'system' else None
            if key.endswith(':memory'): value = app['resources'].get('memoryBytes')
            bad = True
            if rule.get('threshold') is not None:
                bad = None if value is None else value < rule['threshold'] if rule.get('metric') == 'diskFreePercent' else value > rule['threshold']
            if app and not app['running'] and key.rsplit(':', 1)[-1] in ('memory', 'cpu', 'http', 'port'): bad = False
            if key.endswith(':config'): bad = app['health']['blocking']
            if key.endswith(':exit'): bad = (app.get('lastExit') or {}).get('status') == 'failed'
            self.alert_engine.check(key, None if self.scenario == 'unknown' else bad, value, rule, time.monotonic())
        result = copy.deepcopy(self.data)
        result['alerts'] = self.alert_engine.active()
        result['alertOverrides'] = copy.deepcopy(self.alert_engine.overrides)
        for app in result['apps']: app['alerts'] = self.alert_engine.active(app['id'])
        result['sampledAt'] = time.time()
        result['services'] = copy.deepcopy(self.extra_services)
        for a in result['apps']:
            if a['running'] and a.get('port'):
                result['services'].append(dict(key=a['id'], appId=a['id'], appName=a['name'], name='demo.exe', pid=a['lastPid'], port=a['port'],
                    group='mine', cpu=a['resources']['cpu'], mem=3.2, uptimeSec=3600, cwd=a['cwd'], cmd=a['command']))
        result['watched'] = [dict(pid=23000, name='ffmpeg.exe', cpu=12.2, mem=2.1, uptimeSec=100, keywords=['ffmpeg'], cmd='ffmpeg -i demo.mp4 output.mp4')]
        if self.scenario == 'unknown':
            result.update(stale=True, degraded=True, notificationStatus='unavailable')
            for a in result['apps']:
                a.update(statusKnown=False, resources={}, probeState=dict(status='pending'))
        elif self.scenario == 'empty':
            result.update(apps=[], services=[], watched=[], alerts=[], presets=[], activePreset=None, events=[])
        return result

    def request(self, method, path, body):
        if path == '/api/state':
            return self.snapshot()
        if path == '/api/demo/reset':
            self.reset()
        elif path == '/api/demo/scenario':
            self.scenario = body['scenario']
        elif path == '/api/ops/config':
            return {k: self.data[k] for k in ('rules', 'presets', 'activePreset')}
        elif path == '/api/ops/alerts/ignore':
            self.alert_engine.ignore(body['key'], body['incident'])
        elif path == '/api/ops/alerts/accept':
            if body.get('mode') == 'revoke': self.alert_engine.revoke(body['key'])
            else: self.alert_engine.accept(body['key'], body.get('incident'), body.get('mode'), body.get('threshold'))
        elif path in ('/api/ops/rules', '/api/ops/presets'):
            key = path.rsplit('/', 1)[1]
            self.data[key] = body[key]
            if key == 'presets' and not any(p['id'] == self.data['activePreset'] for p in body[key]):
                self.data['activePreset'] = None
        elif path == '/api/ops/presets/run':
            if self.data['presetRun'] and self.data['presetRun']['status'] == 'running':
                return dict(ok=False, error='已有场景正在执行')
            preset = next(p for p in self.data['presets'] if p['id'] == body['id'])
            self.data['activePreset'] = preset['id']
            self.data['presetRun'] = dict(id=uuid.uuid4().hex, name=preset['name'], status='running',
                steps=[dict(s, status='waiting', detail='') for s in sorted(preset['steps'], key=lambda s: s['action'] != 'stop')])
            self.run_start = time.monotonic()
        elif path == '/api/ops/presets/cancel':
            run = self.data['presetRun']
            if run and run['status'] == 'running':
                run['status'] = 'canceled'
                for s in run['steps']:
                    if s['status'] in ('waiting', 'running'):
                        s.update(status='skipped', detail='已取消后续操作')
        elif path == '/api/ops/action':
            app = self.app(body['appId'])
            action = next(a for a in app['actions'] if a['id'] == body['actionId'])
            self.event(app['id'], app['name']+' · '+action['name'], '模拟成功，没有请求外部接口')
        elif path == '/api/ops/force':
            return self.operate(self.app(body['appId']), 'stop')
        elif path == '/api/ops/discover':
            return dict(items=[dict(pid=24001, created=12345, name='演示画图工具', exe='C:\\Demo\\paint.exe', command='paint.exe', ports=[], kind='desktop'),
                               dict(pid=24002, created=12346, name='演示 Web 服务', exe='C:\\Demo\\python.exe', command='python demo.py', ports=[8899], kind='service')])
        elif path in ('/api/apps', '/api/ops/discover/import'):
            validate_app_extra(body)
            values = {k: v for k, v in body.items() if k not in ('name', 'id', 'category', 'appId')}
            if body.get('appId'):
                app = self.app(body['appId']); app.update(values, associationState='attached', statusKnown=True)
            else:
                app = make_app(uuid.uuid4().hex[:8], body.get('name', '新应用'), body.get('category', '验收新增'), **values)
                app.update(lastPid=25000, canStart=bool(app['command']))
                self.data['apps'].append(app)
            return dict(ok=True, id=app['id'])
        elif path == '/api/apps/reorder':
            ids = body['ids']
            self.data['apps'].sort(key=lambda a: ids.index(a['id']) if a['id'] in ids else len(ids))
        elif path.startswith('/api/apps/'):
            parts = path.split('/')
            app = self.app(parts[3])
            action = parts[4] if len(parts) > 4 else ''
            if action == 'logs':
                return dict(text='[演示日志] '+app['name']+'\n'+ '\n'.join(self.logs.get(app['id'], ['服务初始化完成', '等待用户操作；不重复打印心跳'])))
            if action in ('start', 'stop', 'restart'):
                return self.operate(app, action)
            if action == 'diagnose':
                return dict(ok=True, summary='演示诊断：未检查真实文件或进程', issues=app['health']['issues'] or [dict(title='演示检查完成', detail='配置结构正常', fix='无需处理')])
            if action == 'attach':
                app.update(associationState='attached', statusKnown=True, running=True)
            elif action in ('favicon', 'icon'):
                return dict(ok=False, error='演示使用内置图标，不读取或保存图片')
            elif method == 'PUT' and not action:
                extra = validate_app_extra(body)
                app.update(body); app.update(extra); app['canStart'] = bool(app['command'])
                if body.get('command'):
                    app['health'] = dict(status='ok', blocking=False, issues=[])
                    app['alerts'] = [a for a in app['alerts'] if not a['key'].endswith(':config')]
                    self.data['alerts'] = [a for a in self.data['alerts'] if not (a['target'] == app['id'] and a['key'].endswith(':config'))]
                if 'port' in body:
                    app['portConflict'] = body['port'] == 8000
            elif method == 'DELETE' and not action:
                self.data['apps'].remove(app)
            else:
                return dict(ok=False, error='此操作未模拟')
        elif path == '/api/console/log':
            return dict(text='[演示总控台] 仅内存模拟，不连接生产后台\n'+'\n'.join(e['title']+' — '+e['detail'] for e in reversed(self.data['events'][:30])))
        elif path.startswith('/api/console/'):
            return dict(ok=False, error='验收入口保持运行；可用底部“重置演示”恢复数据')
        elif path == '/api/pick':
            return dict(ok=True, path='C:\\Demo\\start.bat' if body.get('what') == 'script' else 'C:\\Demo', command='call start.bat')
        elif path == '/api/project/detect':
            return dict(ok=True, name='演示项目', summary='模拟项目识别，未访问磁盘', files=['start.bat'],
                        candidates=[dict(label='运行演示服务', command='call start.bat', shell='cmd', cwd='C:\\Demo', port=8800, kind='service')])
        elif path == '/api/services/flag':
            service = next(s for s in self.extra_services if s['key'] == body['key'])
            service[body['flag']] = body['value']
            if body['flag'] == 'promoted':
                service['group'] = 'mine' if body['value'] else 'background'
        elif path == '/api/kill':
            self.extra_services = [s for s in self.extra_services if s['pid'] != body['pid']]
        elif path == '/api/watch':
            words = self.data['watchedKeywords']
            if body['action'] == 'remove' and body['keyword'] in words:
                words.remove(body['keyword'])
            elif body['keyword'] not in words:
                words.append(body['keyword'])
        elif path == '/api/ui/theme':
            self.data['uiTheme'] = body['theme']
        else:
            return dict(ok=False, error='验收入口未模拟此接口：'+path)
        return dict(ok=True)


DEMO_SCRIPT = '''<style>body{padding-bottom:48px}#demoBar{position:fixed;bottom:0;left:184px;right:0;z-index:90;display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:10px 18px;background:#17243b;color:white;font:12px system-ui}#demoBar button,#demoBar select{color:#17243b;background:white;border-radius:5px;padding:4px 8px}#demoBar span{flex:1}@media(max-width:1100px){#demoBar{left:78px}}@media(max-width:600px){#demoBar{left:58px;gap:6px;padding:8px}#demoBar span{display:none}}</style>
<script>window.open=()=>{alert('演示操作：已模拟打开入口，不访问真实应用或外部页面。');return null;};
addEventListener('DOMContentLoaded',()=>{
 document.title='UI 验收 · 假数据';
 const bar=document.createElement('div');bar.id='demoBar';
 bar.innerHTML='<strong>假数据验收</strong><span>操作仅影响演示数据</span><select aria-label="验收数据状态"><option value="mixed">完整样例</option><option value="unknown">采集不可用</option><option value="empty">空数据</option></select><button type="button">重置演示</button>';
 document.body.append(bar);
 bar.querySelector('select').onchange=async e=>{await fetch('/api/demo/scenario',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario:e.target.value})});window.__poll?.();};
 bar.querySelector('button').onclick=async()=>{await fetch('/api/demo/reset',{method:'POST'});location.reload();};
 document.addEventListener('click',e=>{const a=e.target.closest('a[href]');if(a&&/^(https?:|file:)/.test(a.href)){e.preventDefault();e.stopImmediatePropagation();window.open();}},true);
});</script>'''


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *_):
        pass

    def send_bytes(self, data, kind, status=200):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith('/api/'):
            return self.api()
        if path in ('/', '/index.html'):
            html = (STATIC/'index.html').read_text(encoding='utf8').replace('</head>', DEMO_SCRIPT+'</head>')
            return self.send_bytes(html.encode(), 'text/html; charset=utf-8')
        super().do_GET()

    def api(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 <= size <= 1024*1024:
                raise ValueError('演示请求过大')
            body = json.loads(self.rfile.read(size)) if size else {}
            with self.server.demo.lock:
                result = copy.deepcopy(self.server.demo.request(self.command, urlsplit(self.path).path, body))
            self.send_bytes(json.dumps(result, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
        except (ValueError, KeyError, StopIteration, TypeError) as exc:
            self.send_bytes(json.dumps(dict(ok=False, error='演示数据不适用此操作：'+str(exc)), ensure_ascii=False).encode(), 'application/json; charset=utf-8', 400)

    do_POST = do_PUT = do_DELETE = api


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=9610)
    args = parser.parse_args()
    mimetypes.add_type('text/javascript', '.js')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.demo = Demo(args.port)
    print(f'UI acceptance demo: http://127.0.0.1:{args.port}/', flush=True)
    server.serve_forever()
