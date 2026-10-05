"""Related locations and explicitly selected Windows windows. Standard library only."""
import ctypes as C
from ctypes import wintypes as W
import os
import ntpath
import hashlib
import json
import re
import time
import secrets
import subprocess
import sys
import threading


DESKTOP_LAUNCH_FLAGS = {
    'streamdeck.exe': ({'--runinbk'}, set()),
    'typeless.exe': ({'--system-startup-silent-launch'}, set()),
    'quark_cloud_drive.exe': (set(), {'--launch-from'}),
    'steam.exe': ({'-silent'}, set()),
    'todesk.exe': ({'--hide', '--show'}, {'--localPort'}),
    'baidunetdisk.exe': ({'NoUpdate'}, set()),
}


def desktop_rule_upgrade_needed(app):
    rule = app.get('instanceMatch') or {}
    exe = os.path.basename(rule.get('exe') or '').lower()
    window = (app.get('windowBinding') or {}).get('match') or {}
    if (app.get('kind') == 'desktop' and exe == 'bambu-studio.exe' and rule.get('argsHash')
            and window.get('scope') == 'application' and window.get('windowClass') == 'wxWindowNR'
            and same_window_executable(window.get('exe'), rule.get('exe'))):
        return True
    version = 4 if exe == 'quark_cloud_drive.exe' else 3
    return (app.get('kind') == 'desktop' and exe in DESKTOP_LAUNCH_FLAGS
            and bool(rule.get('argsHash')) and rule.get('argsHashVersion', 1) < version)


def same_window_executable(left, right):
    """Match window owners across WindowsApps updates, not arbitrary exe moves.

    Keep the install root, package name, architecture, resource, publisher and
    relative executable. Only the four-part package version may change.
    This is discovery identity; live PID/created/exe checks remain exact.
    """
    def key(path):
        path = ntpath.normcase(ntpath.normpath(path or ''))
        root = ntpath.normcase(ntpath.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'WindowsApps')) + '\\'
        if path.startswith(root):
            package, sep, relative = path[len(root):].partition('\\')
            match = re.fullmatch(r'([^_]+)_\d+\.\d+\.\d+\.\d+_([^_]+)_([^_]*)_([^_]+)', package)
            if match and sep and relative:
                return (root, *match.groups(), relative)
        return path
    return bool(left and right) and key(left) == key(right)


def browser_card_rule(api, app):
    """Only plain default-profile browser cards; service/PWA profiles stay exact."""
    tokens = api._simple_command_tokens(app.get('command') or '')
    if (app.get('kind') == 'desktop' and tokens and len(tokens) == 1
            and os.path.basename(tokens[0]).lower() in ('chrome.exe', 'msedge.exe')
            and os.path.isabs(tokens[0])):
        return dict(exe=tokens[0], windowClass='Chrome_WidgetWin_1', toolWindow=False, browserMain=True)
    return None


def ordinary_browser_window(window):
    from service_web import window_app_property
    expected = {'chrome.exe': 'Chrome', 'msedge.exe': 'MSEdge'}.get(os.path.basename(window['exe']).lower())
    return bool(expected and not window.get('toolWindow')
                and window.get('windowClass') == 'Chrome_WidgetWin_1'
                and window_app_property(window['hwnd'], 5) == expected)


def default_browser_process(api, row):
    tokens = api._simple_command_tokens(row.get('args') or '')
    return bool(tokens and not any(t.split('=', 1)[0].lower() in ('--type', '--user-data-dir') for t in tokens[1:]))


def instance_args_hash(exe, args, parse=None, launch_modes=False):
    if launch_modes and parse:
        tokens = parse(args)
        if tokens:
            flags, options = DESKTOP_LAUNCH_FLAGS.get(os.path.basename(exe).lower(), (set(), set()))
            if launch_modes == 4 and os.path.basename(exe).lower() == 'quark_cloud_drive.exe':
                flags = flags | {'--brand-clouddrive'}
            effective, index = [os.path.normcase(exe)], 1
            while index < len(tokens):
                token = tokens[index]
                key, equals, _ = token.partition('=')
                if token in flags:
                    index += 1
                    continue
                if key in options:
                    if equals:
                        index += 1
                        continue
                    if index + 1 < len(tokens) and not tokens[index + 1].startswith('-'):
                        index += 2
                        continue
                effective.append(token)
                index += 1
            return hashlib.sha256(json.dumps(effective, ensure_ascii=False).encode('utf8')).hexdigest()
    # ToDesk allocates a new local IPC port on each GUI launch.
    if os.path.basename(exe).lower() == 'todesk.exe':
        args = re.sub(r'(?i)(?<!\S)--localPort=\d+(?=\s|$)', '', args)
    if parse:
        tokens = parse(args)
        if tokens:
            args = json.dumps(tokens, ensure_ascii=False)
    return hashlib.sha256(args.strip().encode('utf8')).hexdigest()


def service_identity(api, command, cwd, exe=None, entry_hint=None):
    """Identify a script service by its entry and project, not its launcher/PID."""
    # Windows extended-length paths name the same entry as ordinary drive paths.
    if isinstance(command, str):
        command = command.replace('\\\\?\\UNC\\', '\\\\').replace('\\\\?\\', '')
    tokens = api._simple_command_tokens(command)
    if not tokens or not cwd:
        return None
    runtime = os.path.basename(exe or tokens[0]).lower().removesuffix('.exe')
    if runtime in ('npx', 'npx.cmd') and entry_hint:
        index = 1
        while index < len(tokens) and tokens[index] in ('-y', '--yes', '--no-install'):
            index += 1
        if index >= len(tokens):
            return None
        match = re.fullmatch(r'(@[\w.-]+/[\w.-]+|[\w.-]+)(?:@[^\s/]+)?', tokens[index])
        if not match:
            return None
        package = match[1]
        marker = '/node_modules/' + package + '/'
        prefix, found, _ = entry_hint.replace('\\', '/').rpartition(marker)
        if not found:
            return None
        directory = prefix + '/node_modules/' + package
        try:
            with open(os.path.join(directory, 'package.json'), encoding='utf8') as source:
                raw = source.read(65537)
            if len(raw) > 65536:
                return None
            metadata = json.loads(raw)
            bins = metadata.get('bin')
            entry = bins if isinstance(bins, str) else (bins or {}).get(package.rsplit('/', 1)[-1])
            if (metadata.get('name') != package or not isinstance(entry, str)
                    or os.path.normcase(os.path.realpath(os.path.join(directory, entry))) != os.path.normcase(os.path.realpath(entry_hint))):
                return None
        except (OSError, ValueError, AttributeError):
            return None
        # Resolve only the already-recorded local package entry. Never run npx,
        # download a package, or infer its arguments from an unowned process.
        tokens, runtime = ['node', entry_hint, *tokens[index + 1:]], 'node'
    if runtime == 'tunnel-client':
        if len(tokens) < 2 or tokens[1] != 'run':
            return None
        options = {}
        for flag in ('--profile-dir', '--profile'):
            values = [tokens[i + 1] if token == flag and i + 1 < len(tokens) else token[len(flag) + 1:]
                      for i, token in enumerate(tokens) if token == flag or token.startswith(flag + '=')]
            if len(values) != 1 or not values[0] or values[0].startswith('-'):
                return None
            options[flag] = values[0]
        directory = api._resolve_command_path(options['--profile-dir'], cwd)
        executable = api._resolve_command_path(exe or tokens[0], cwd)
        return dict(runtime=runtime, exe=os.path.normcase(os.path.realpath(executable)),
                    profileDir=os.path.normcase(os.path.realpath(directory)), profile=options['--profile'])
    if re.fullmatch(r'pythonw?(?:\d+(?:\.\d+)*)?', runtime):
        family, suffixes = 'python', ('.py', '.pyw')
    elif runtime == 'node':
        family, suffixes = 'node', ('.js', '.mjs', '.cjs')
    else:
        return None
    args = iter(tokens[1:])
    for arg in args:
        if family == 'python' and arg in ('-X', '-W'):
            next(args, None)
            continue
        if arg in ('--', '-B', '-u', '-s', '-S', '-E', '-I', '-O', '-OO', '--no-warnings', '--enable-source-maps'):
            continue
        # Do not guess entries hidden inside -c/-m, loaders or other switches.
        if arg.startswith('-') or not arg.lower().endswith(suffixes):
            return None
        entry = api._resolve_command_path(arg, cwd)
        effective = []
        for value in args:
            # --profile=x and --profile x are the same spelling; preserve all
            # script arguments, including unknown options and their order.
            effective.extend(value.split('=', 1) if value.startswith('--') and '=' in value else [value])
        return dict(runtime=family, entry=os.path.normcase(os.path.realpath(entry)),
                    project=os.path.normcase(os.path.realpath(cwd)),
                    argsHash=hashlib.sha256(json.dumps(effective, ensure_ascii=False).encode('utf8')).hexdigest())
    return None


def capture_instance_match(api, app, pid):
    row = api._win_process_table().get(pid, {})
    if not row.get('exe') or not row.get('args') or api.process_uid(pid) != api.SELF_UID:
        raise ValueError('无法读取应用身份，请先关联运行实例')
    parse = getattr(api, '_simple_command_tokens', None)
    browser = browser_card_rule(api, app) if parse else None
    if browser and same_window_executable(browser['exe'], row['exe']):
        if not default_browser_process(api, row):
            raise ValueError('所选实例使用独立浏览器数据目录，请在启动命令中保留该目录后再关联')
        return browser
    rule = dict(exe=row['exe'], argsHash=instance_args_hash(row['exe'], row['args'], parse))
    if parse:
        rule['argsHashVersion'] = 2
    hosts = {'python.exe', 'pythonw.exe', 'node.exe', 'cmd.exe', 'powershell.exe', 'pwsh.exe',
             'windowsterminal.exe', 'wt.exe', 'wsl.exe', 'bash.exe', 'conhost.exe', 'openconsole.exe'}
    window_match = (app.get('windowBinding') or {}).get('match') or {}
    executable = os.path.basename(row['exe']).lower()
    if app.get('kind') == 'desktop' and executable in DESKTOP_LAUNCH_FLAGS and parse:
        version = 4 if executable == 'quark_cloud_drive.exe' else 3
        rule.update(argsHash=instance_args_hash(row['exe'], row['args'], parse, launch_modes=version), argsHashVersion=version)
    if (app.get('kind') == 'desktop' and
            (executable in {'pixpin.exe', 'cloudmusic.exe'}
             or (executable == 'bambu-studio.exe' and window_match.get('windowClass') == 'wxWindowNR')
             or (executable == 'chatgpt.exe' and 'openai.codex_' in row['exe'].lower())) and
            window_match.get('scope') == 'application' and window_match.get('windowClass') and
            same_window_executable(window_match.get('exe'), row['exe'])):
        return dict(exe=row['exe'], windowClass=window_match['windowClass'],
                    toolWindow=window_match.get('toolWindow', False))
    if app.get('kind') != 'desktop' or os.path.basename(row['exe']).lower() in hosts:
        cwd = api._win_cwd(pid)
        if not row.get('args') or not cwd:
            raise ValueError('脚本或服务需要可读取的启动参数及工作目录才能自动关联')
        rule['cwd'] = cwd
        if app.get('kind') == 'service':
            service = service_identity(api, row['args'], cwd, row['exe'])
            if service:
                rule = dict(service=service, port=app.get('port'))
    return rule


def instance_candidates(api, rule, within=None):
    table = api._win_process_table()
    service = rule.get('service')
    window_pids = {w['pid'] for w in list_windows(api, include_hidden=True)
                   if same_window_executable(w['exe'], rule['exe'])
                   and w.get('windowClass') == rule['windowClass']
                   and w.get('toolWindow') == rule.get('toolWindow', False)
                   and (not rule.get('browserMain') or ordinary_browser_window(w))} if rule.get('windowClass') else None
    listeners = api.scan_listeners() if service and rule.get('port') else []
    matches = []
    for pid, row in table.items():
        if within is not None and pid not in within:
            continue
        if pid == api.SELF_PID or not row.get('exe'):
            continue
        if not row.get('identity') or api.process_uid(pid) != api.SELF_UID:
            continue
        if service:
            runtime = os.path.basename(row['exe']).lower()
            if not (runtime.startswith('python') if service['runtime'] == 'python' else runtime == service['runtime'] + '.exe'):
                continue
            actual = service_identity(api, row.get('args') or '', api._win_cwd(pid), row['exe'])
            # cwd resolves relative script entries; the launcher directory is not
            # identity once the same absolute entry and effective args are known.
            if not actual or {k: v for k, v in actual.items() if k != 'project'} != {k: v for k, v in service.items() if k != 'project'}:
                continue
            members = set(api._win_tree_of(pid, table))
            ports = {port for owner, port in listeners if owner in members}
            if ports and rule.get('port') not in ports:
                continue
        else:
            if rule.get('browserMain') and not default_browser_process(api, row):
                continue
            if not (same_window_executable(row['exe'], rule['exe']) if window_pids is not None
                    else os.path.normcase(row['exe']) == os.path.normcase(rule['exe'])):
                continue
            if window_pids is not None:
                if pid not in window_pids:
                    continue
            elif instance_args_hash(row['exe'], row.get('args') or '',
                                    getattr(api, '_simple_command_tokens', None) if rule.get('argsHashVersion') in (2, 3, 4) else None,
                                    launch_modes=rule.get('argsHashVersion') if rule.get('argsHashVersion') in (3, 4) else False) != rule.get('argsHash'):
                continue
            if rule.get('cwd') and os.path.normcase(api._win_cwd(pid) or '') != os.path.normcase(rule['cwd']):
                continue
        matches.append(pid)
    # Electron/browser helpers share the executable: keep independent roots only.
    roots = []
    for pid in matches:
        parent, seen = table[pid].get('ppid'), {pid}
        while parent in table and parent not in seen and parent not in matches:
            seen.add(parent)
            parent = table[parent].get('ppid')
        if parent not in matches:
            roots.append(pid)
    return roots


def verify_instance_ownership(api, cfg, identity, app_id=None):
    candidate = dict(id=app_id, externalIdentity=identity)
    members = set(api.external_pids(candidate))
    if not members:
        raise ValueError('选定实例已退出或身份变化')
    # Include the proposed root while checking both sides, so importing a child
    # carves that branch out of its launcher's card before overlap is evaluated.
    apps = [a for a in cfg['apps'] if a['id'] != app_id] + [candidate]
    members = set(api.card_process_members(candidate, members, apps))
    for other in cfg['apps']:
        other_members = api.managed_pids(other)
        other_members = api.card_process_members(other, other_members, apps)
        if other['id'] != app_id and members.intersection(other_members):
            raise ValueError('进程树已包含其他卡片：' + other.get('name', other['id']))
    return members


def refresh_instance(api, cfg, app):
    """Caller holds the app operation lock; never adopts an ambiguous match."""
    rule = app.get('instanceMatch')
    if not api.IS_WIN or not rule:
        return app, None
    running = api.app_running(app)
    if not running and api.app_identity_uncertain(app):
        return app, '原实例身份暂时不可读，等待下一次采集'
    saved_rule = rule
    if running and desktop_rule_upgrade_needed(app):
        # Learn only from the already verified application root. Old saved
        # hashes keep their meaning until a live instance can be recaptured.
        pid = (app.get('externalIdentity') or {}).get('pid')
        if pid and pid in api.managed_pids(app):
            row = api._win_process_table().get(pid, {})
            if row.get('args') and same_window_executable(row.get('exe'), rule.get('exe')):
                rule = capture_instance_match(api, app, pid)
    browser = browser_card_rule(api, app) if hasattr(api, '_simple_command_tokens') else None
    if browser and same_window_executable(rule.get('exe'), browser['exe']):
        rule = browser
    service = rule.get('service')
    if service and service.get('runtime') in ('python', 'node') and 'argsHash' not in service:
        # Upgrade only from the still-verified instance, or its explicit saved
        # command. Never learn identity from an unowned candidate.
        signatures = []
        table = api._win_process_table()
        for member in api.managed_pids(app) if running else []:
            row = table.get(member, {})
            current = service_identity(api, row.get('args'), api._win_cwd(member), row.get('exe'))
            if current and {k: v for k, v in current.items() if k != 'argsHash'} == service and current not in signatures:
                signatures.append(current)
        if not signatures:
            current = service_identity(api, app.get('command'), app.get('cwd'), entry_hint=service.get('entry'))
            if current and {k: v for k, v in current.items() if k != 'argsHash'} == service:
                signatures.append(current)
        if len(signatures) != 1:
            if not running:
                for pid, row in table.items():
                    runtime = os.path.basename(row.get('exe') or '').lower()
                    if not (runtime.startswith('python') if service['runtime'] == 'python' else runtime == 'node.exe'):
                        continue
                    if api.process_uid(pid) != api.SELF_UID:
                        continue
                    current = service_identity(api, row.get('args'), api._win_cwd(pid), row.get('exe'))
                    if current and {k: v for k, v in current.items() if k != 'argsHash'} == service:
                        return app, '发现旧规则对应的运行实例，但缺少参数身份，请重新关联运行实例'
            # No candidate is a stopped app, not an ambiguous app. A managed
            # launch can capture its verified child identity on the next sample.
            return app, None
        rule = dict(service=signatures[0], port=app.get('port'))
    if rule != saved_rule:
        def upgrade(c):
            target = api.find_app(c, app['id'])
            if not target or target.get('instanceMatch') != saved_rule:
                raise ValueError('应用关联设置已变化，请重试')
            target['instanceMatch'] = rule
        try:
            cfg.update(upgrade)
        except ValueError as exc:
            return app, str(exc)
        app = api.find_app(cfg.snapshot(), app['id'])
        saved_rule = rule
    # A surviving shortcut/terminal is not the desktop it launched. Rebind
    # window-based cards when the actual client has moved to a new process.
    if running and not (app.get('kind') == 'desktop' and rule.get('windowClass')
                        and api.desktop_background_only(app)):
        return app, None
    pids = instance_candidates(api, rule)
    if len(pids) > 1:
        return app, '发现多个匹配实例，请在详情中选择运行实例'
    if not pids:
        return app, None
    pid = pids[0]
    row = api._win_process_table().get(pid, {})
    identity = dict(pid=pid, created=row.get('identity'), exe=row.get('exe'))
    def save(c):
        target = api.find_app(c, app['id'])
        if not target or target.get('instanceMatch') != saved_rule:
            raise ValueError('应用关联设置已变化，请重试')
        verify_instance_ownership(api, c, identity, app['id'])
        target.update(externalIdentity=identity, lastPid=pid, lastPgid=None, runToken=None,
                      attached=True, expectedRunning=True, startedAt=row.get('created') or time.time(),
                      instanceMatch=rule)
    try:
        cfg.update(save)
    except ValueError as exc:
        return app, str(exc)
    return api.find_app(cfg.snapshot(), app['id']), None


def open_location(action):
    path = os.path.normpath(action['path'])
    if not os.path.exists(path):
        raise ValueError('位置不存在，请检查路径')
    directory = path if os.path.isdir(path) else os.path.dirname(path)
    mode, editor = action['mode'], action.get('editor')
    if mode == 'editor' and editor and not os.path.isfile(editor):
        raise ValueError('编辑器不存在，请检查可执行文件路径')
    if mode == 'editor' and os.path.isdir(path) and not editor:
        raise ValueError('打开目录需要指定支持目录的编辑器，例如 Code.exe')
    if os.name == 'nt':
        system = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32')
        if mode == 'explorer':
            args = [os.path.join(os.path.dirname(system), 'explorer.exe')]
            args += [path] if os.path.isdir(path) else ['/select,', path]
        elif mode == 'terminal':
            args = [os.path.join(system, 'WindowsPowerShell', 'v1.0', 'powershell.exe'), '-NoLogo', '-NoExit']
        else:
            args = [editor or os.path.join(system, 'notepad.exe'), path]
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | (subprocess.CREATE_NEW_CONSOLE if mode == 'terminal' else subprocess.DETACHED_PROCESS)
        proc = subprocess.Popen(args, cwd=directory, creationflags=flags,
                                stdin=None if mode == 'terminal' else subprocess.DEVNULL,
                                stdout=None if mode == 'terminal' else subprocess.DEVNULL,
                                stderr=None if mode == 'terminal' else subprocess.DEVNULL, close_fds=True)
    elif sys.platform == 'darwin':
        args = (['/usr/bin/open', '-R', path] if mode == 'explorer' else
                ['/usr/bin/open', '-a', 'Terminal', directory] if mode == 'terminal' else
                [editor, path] if editor else ['/usr/bin/open', '-a', 'TextEdit', path])
        proc = subprocess.Popen(args, start_new_session=True, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        raise ValueError('打开位置仅支持 Windows/macOS')
    # Reap eventually, but never time out or terminate the launched application.
    threading.Thread(target=proc.wait, daemon=True, name='location-launch').start()
    return {'ok': True}


def window_api():
    user = C.WinDLL('user32', use_last_error=True)
    user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    user.SetPropW.argtypes = [W.HWND, W.LPCWSTR, W.HANDLE]
    user.GetPropW.argtypes = [W.HWND, W.LPCWSTR]
    user.GetPropW.restype = W.HANDLE
    user.IsIconic.argtypes = [W.HWND]
    user.IsWindowVisible.argtypes = [W.HWND]
    user.BringWindowToTop.argtypes = [W.HWND]
    user.SetActiveWindow.argtypes = [W.HWND]
    user.SetActiveWindow.restype = W.HWND
    user.ShowWindowAsync.argtypes = [W.HWND, C.c_int]
    user.SetForegroundWindow.argtypes = [W.HWND]
    user.GetForegroundWindow.restype = W.HWND
    user.AttachThreadInput.argtypes = [W.DWORD, W.DWORD, W.BOOL]
    user.PeekMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT]
    user.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    user.GetWindowLongW.argtypes = [W.HWND, C.c_int]
    return user


def list_windows(api, include_hidden=False):
    if not api.IS_WIN:
        return []
    from win_metrics import windows
    table = api._win_process_table(refresh=True)
    result = []
    for pid, items in windows(include_hidden=include_hidden).items():
        row = table.get(pid)
        if pid == api.SELF_PID or not row or not row.get('exe') or api.process_uid(pid) != api.SELF_UID:
            continue
        for hwnd, title in items:
            user = window_api()
            name = C.create_unicode_buffer(256)
            user.GetClassNameW(hwnd, name, len(name))
            result.append(dict(hwnd=hwnd, pid=pid, created=row['identity'], exe=row['exe'], title=title,
                               windowClass=name.value, toolWindow=bool(user.GetWindowLongW(hwnd, -20) & 0x80)))
    return result


def verify_window(api, binding):
    if not api.IS_WIN:
        raise ValueError('窗口操作仅支持 Windows')
    if not isinstance(binding, dict) or any(type(binding.get(k)) is not int or binding[k] <= 0 for k in ('hwnd', 'pid')):
        raise ValueError('请选择要关联的窗口')
    row = next((w for w in list_windows(api, include_hidden=True) if all(w[k] == binding.get(k) for k in ('hwnd', 'pid', 'created', 'exe'))), None)
    if row is None:
        raise ValueError('窗口已关闭、身份变化或不可访问，请重新选择窗口')
    return row


def bind_window(api, app_id, selection, app=None):
    row = verify_window(api, selection)
    token = secrets.randbelow(0x7ffffffe) + 1
    if not window_api().SetPropW(row['hwnd'], 'Cddeck.Window.' + app_id, token):
        raise ValueError('无法关联此窗口，请检查应用权限')
    binding = dict(row, token=token)
    if app and row.get('windowClass'):
        binding['match'] = dict(exe=row['exe'], windowClass=row['windowClass'], toolWindow=row['toolWindow'],
                               scope='application' if row['pid'] in api.managed_pids(app) else 'title', title=row['title'])
        if os.path.basename(row['exe']).lower() in ('chrome.exe', 'msedge.exe'):
            from service_web import window_app_property
            browser_id = window_app_property(row['hwnd'], 5)
            # Installed web apps have a distinct ID even when Chrome shares a PID.
            # Plain --app URL windows can share an ID across different ports.
            if '._crx_' in browser_id:
                binding['match']['browserAppId'] = browser_id
    return binding


def resolve_window(api, app):
    binding = app.get('windowBinding')
    browser = browser_card_rule(api, app) if hasattr(api, '_simple_command_tokens') else None
    try:
        row = verify_window(api, binding)
        if (not browser or ordinary_browser_window(row)) and binding.get('token') and window_api().GetPropW(row['hwnd'], 'Cddeck.Window.' + app['id']) == binding['token']:
            return binding
    except ValueError:
        if not isinstance(binding, dict) or not binding.get('match'):
            raise
    rule = binding.get('match')
    if not rule:
        raise ValueError('原窗口已失效，请重新选择窗口')
    members = api.managed_pids(app) if rule['scope'] == 'application' else []
    def title_matches(window):
        if rule.get('browserAppId'):
            from service_web import window_app_property
            return window_app_property(window['hwnd'], 5) == rule['browserAppId']
        title, expected = window['title'], rule['title']
        if os.path.basename(rule['exe']).lower() in ('chrome.exe', 'msedge.exe'):
            # A saved browser window can later be installed as a web app.
            for suffix in (' - Google Chrome', ' - Microsoft Edge'):
                title, expected = title.removesuffix(suffix), expected.removesuffix(suffix)
        return title == expected
    candidates = [w for w in list_windows(api, include_hidden=True) if same_window_executable(w['exe'], rule['exe'])
                  and w.get('windowClass') == rule['windowClass'] and w.get('toolWindow') == rule['toolWindow']
                  and (not browser or ordinary_browser_window(w))
                  and (w['pid'] in members if rule['scope'] == 'application' else title_matches(w))]
    if len(candidates) > 1:
        exact = [w for w in candidates if w['title'] == rule['title']]
        if len(exact) == 1:
            candidates = exact
    if len(candidates) != 1:
        raise ValueError('匹配窗口不唯一，请重新选择窗口' if candidates else '尚未找到匹配窗口，请等待应用打开或重新选择')
    return bind_window(api, app['id'], candidates[0], app)


def retry_foreground(user, hwnd):
    # HTTP workers receive no mouse input. Temporarily share the foreground
    # thread's input queue for this explicit activation, then always detach.
    foreground = user.GetForegroundWindow()
    if foreground == hwnd:
        return True
    current = threading.get_native_id()
    message = W.MSG()
    user.PeekMessageW(C.byref(message), None, 0, 0, 0)  # Create this worker's message queue.
    attached = []
    try:
        for window in (foreground, hwnd):
            target = user.GetWindowThreadProcessId(window, None) if window else 0
            if target and target != current and target not in attached:
                if not user.AttachThreadInput(current, target, True):
                    return False
                attached.append(target)
        user.BringWindowToTop(hwnd)
        user.SetActiveWindow(hwnd)
        return bool(user.SetForegroundWindow(hwnd)) or user.GetForegroundWindow() == hwnd
    finally:
        for target in reversed(attached):
            user.AttachThreadInput(current, target, False)


def operate_window(api, app, operation, cfg=None):
    if operation != 'focus':
        raise ValueError('窗口操作无效')
    binding = resolve_window(api, app)
    if cfg is not None and binding != app.get('windowBinding'):
        cfg.update(lambda c: api.find_app(c, app['id']).update(windowBinding=binding))
    row = verify_window(api, binding)
    user, hwnd = window_api(), row['hwnd']
    # A per-window property disappears on destruction, rejecting even HWND reuse
    # within the same still-running process. Titles may freely change (TUI tabs).
    if not binding.get('token') or user.GetPropW(hwnd, 'Cddeck.Window.' + app['id']) != binding['token']:
        raise ValueError('原窗口已失效，请重新选择窗口')
    pid = W.DWORD()
    user.GetWindowThreadProcessId(hwnd, C.byref(pid))
    if pid.value != row['pid']:
        raise ValueError('窗口身份变化，请重新选择窗口')
    if user.IsIconic(hwnd):
        user.ShowWindowAsync(hwnd, 9)  # SW_RESTORE only for minimized windows.
    elif not user.IsWindowVisible(hwnd):
        user.ShowWindowAsync(hwnd, 5)  # SW_SHOW restores a tray-hidden bound window.
    # ShowWindowAsync only queues a request. Wait briefly before activation.
    for _ in range(10):
        if user.GetPropW(hwnd, 'Cddeck.Window.' + app['id']) != binding['token']:
            raise ValueError('原窗口已失效，请重新选择窗口')
        if user.IsWindowVisible(hwnd) and not user.IsIconic(hwnd):
            break
        time.sleep(0.03)
    else:
        raise ValueError('应用未显示关联窗口，请从托盘打开主界面后重新关联')
    if user.GetForegroundWindow() == hwnd:
        return {'ok': True}
    user.SetForegroundWindow(hwnd)
    retry_foreground(user, hwnd)
    for _ in range(10):
        if user.GetForegroundWindow() == hwnd:
            return {'ok': True}
        time.sleep(0.03)
    raise ValueError('Windows 未允许切换前台，请从任务栏或托盘激活该窗口')
