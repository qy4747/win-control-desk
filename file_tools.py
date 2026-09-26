"""Folder bookmarks and on-demand Everything CLI queries. Standard library only."""
import copy
import datetime as dt
from functools import lru_cache
import json
import math
import os
import re
import secrets
import subprocess
import tempfile
import threading

from ops_entries import open_location
from ops_model import text

DEFAULT_ES_PATH = r'H:\codex文件管理\tools\Everything-CLI\es.exe'
PAGE_SIZE = 100
MAX_PAGE = 1000
# ponytail: two concurrent ES processes; queue only if multi-user demand appears.
SEARCH_SLOTS = threading.BoundedSemaphore(2)


def absolute_path(value):
    value = text(value, '路径', 32767)
    if not os.path.isabs(value) or any(c in value for c in '\r\n'):
        raise ValueError('请输入绝对路径')
    return os.path.normpath(value)


def save_folder(cfg, data):
    path = absolute_path(data.get('path'))
    if not os.path.isdir(path):
        raise ValueError('目录不存在或不可访问，请检查路径')
    name = text(data.get('name'), '目录名称', 80)
    group = text(data.get('group', ''), '分组', 80, empty=True)
    ident = data.get('id')
    if ident is not None and not isinstance(ident, str):
        raise ValueError('目录 ID 无效')

    def save(c):
        folders = c['folders']
        current = next((f for f in folders if f['id'] == ident), None)
        if ident is not None and current is None:
            raise ValueError('收藏已被移除，请刷新后重试')
        if any(f['id'] != ident and os.path.normcase(f['path']) == os.path.normcase(path) for f in folders):
            raise ValueError('此目录已收藏')
        if current is None:
            current = {'id': secrets.token_hex(8)}
            folders.append(current)
        current.update(name=name, path=path, group=group)
        return copy.deepcopy(current)
    return cfg.update(save)


def remove_folder(cfg, ident):
    if not isinstance(ident, str):
        raise ValueError('目录 ID 无效')
    def save(c):
        if not any(f['id'] == ident for f in c['folders']):
            raise ValueError('收藏已被移除，请刷新后重试')
        c['folders'] = [f for f in c['folders'] if f['id'] != ident]
    cfg.update(save)


def reorder_folders(cfg, ids):
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ValueError('排序数据无效')
    def save(c):
        by_id = {f['id']: f for f in c['folders']}
        if len(ids) != len(by_id) or set(ids) != set(by_id):
            raise ValueError('收藏列表已变化，请刷新后重试')
        c['folders'] = [by_id[i] for i in ids]
    cfg.update(save)


def search_args(settings, folders, data):
    query = text(data.get('query', ''), '搜索内容', 2048, empty=True)
    if any(ord(c) < 32 for c in query):
        raise ValueError('搜索内容不能含控制字符')
    page = data.get('page', 1)
    if type(page) is not int or not 1 <= page <= MAX_PAGE:
        raise ValueError('页码超出范围')
    sort = data.get('sort', 'name')
    direction = data.get('direction', 'ascending')
    if sort not in ('name', 'path', 'extension', 'size', 'date-modified') or direction not in ('ascending', 'descending'):
        raise ValueError('排序方式无效')
    kind = data.get('kind', '')
    if kind not in ('', 'file', 'folder'):
        raise ValueError('文件类型无效')
    ext = text(data.get('extension', ''), '扩展名', 160, empty=True).lstrip('.')
    if ext and not re.fullmatch(r'[\w-]+(?:;[\w-]+)*', ext):
        raise ValueError('扩展名以分号分隔，例如 pdf;docx')
    filters = []
    if ext:
        filters.append('ext:' + ext)
    sizes = []
    for key, operator in (('minSize', '>='), ('maxSize', '<=')):
        value = data.get(key)
        if value is not None:
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1e16:
                raise ValueError('文件大小范围无效')
            filters.append('size:' + operator + str(int(value)))
        sizes.append(value)
    if all(v is not None for v in sizes) and sizes[0] > sizes[1]:
        raise ValueError('最小大小不能大于最大大小')
    dates = []
    for key, operator in (('dateFrom', '>='), ('dateTo', '<')):
        value = data.get(key, '')
        if not isinstance(value, str):
            raise ValueError('修改时间无效')
        try:
            date = dt.date.fromisoformat(value) if value else None
            bound = date + dt.timedelta(days=1) if date and key == 'dateTo' else date
        except (ValueError, OverflowError):
            raise ValueError('修改时间无效') from None
        if bound:
            filters.append('dm:' + operator + bound.isoformat())
        dates.append(date)
    if all(dates) and dates[0] > dates[1]:
        raise ValueError('开始日期不能晚于结束日期')
    offset = (page - 1) * PAGE_SIZE
    args = [absolute_path(settings.get('esPath')), '-timeout', '3000',
            '-n', str(offset + PAGE_SIZE + 1), '-viewport-offset', str(offset),
            '-viewport-count', str(PAGE_SIZE + 1), '-json', '-full-path-and-name',
            '-size', '-date-modified', '-attributes', '-date-format', '1',
            '-sort', sort + '-' + direction]
    folder_id = data.get('folderId', '')
    if folder_id:
        folder = next((f for f in folders if f['id'] == folder_id), None)
        if folder is None:
            raise ValueError('范围目录已移除，请重新选择')
        path = absolute_path(folder['path'])
        if not os.path.isdir(path):
            raise ValueError('范围目录不存在或不可访问')
        args.extend(['-path', path])
    if kind:
        args.append('/ad' if kind == 'folder' else '/a-d')
    # -search consumes one argument (including spaces and option-like text).
    # Bare positional text preserves CLI quoting and would turn filters into a phrase.
    args.extend(['-search', '<' + (query or '*') + '>' + (' ' + ' '.join(filters) if filters else '')])
    return args


def search(settings, folders, data):
    if os.name != 'nt':
        raise ValueError('Everything 搜索仅支持 Windows')
    args = search_args(settings, folders, data)
    if not os.path.isfile(args[0]):
        raise ValueError('未找到 ES，请在设置中心检查 Everything CLI 路径')
    if not SEARCH_SLOTS.acquire(blocking=False):
        raise ValueError('搜索繁忙，请稍后重试')
    try:
        # Redirected stdout uses the active Windows code page and can lose filenames.
        # ES JSON export is UTF-8; a per-request temporary file also isolates queries.
        with tempfile.TemporaryDirectory(prefix='cddeck-es-') as directory:
            export = os.path.join(directory, 'results.json')
            args[-2:-2] = ['-export-json', export, '-utf8-bom']
            try:
                result = subprocess.run(es_command_line(args), executable=args[0], capture_output=True, timeout=8, shell=False,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
            except subprocess.TimeoutExpired:
                raise ValueError('搜索超时，请缩小范围后重试，并确认 Everything 已运行') from None
            if result.returncode:
                raise ValueError('Everything 查询失败（代码 %d），请确认 Everything 正在运行且索引已就绪' % result.returncode)
            with open(export, 'rb') as stream:
                payload = stream.read(4 * 1024 * 1024 + 1)
            if len(payload) > 4 * 1024 * 1024:
                raise ValueError('搜索结果过大，请缩小范围')
        try:
            rows = json.loads(payload.decode('utf-8-sig').strip() or '[]')
            if not isinstance(rows, list) or len(rows) > PAGE_SIZE + 1:
                raise ValueError()
            items = []
            for row in rows[:PAGE_SIZE]:
                path = absolute_path(row['filename'])
                attributes = row.get('attributes')
                kind = 'unknown' if attributes is None else ('folder' if int(attributes) & 16 else 'file')
                size = row.get('size')
                items.append(dict(path=path, name=os.path.basename(path.rstrip('\\/')) or path,
                                  kind=kind,
                                  size=size if isinstance(size, (int, float)) and kind != 'folder' else None,
                                  modified=str(row.get('date_modified') or '')))
        except (ValueError, KeyError, TypeError, UnicodeError):
            raise ValueError('ES 返回格式无法识别，请检查 CLI 版本') from None
        return dict(ok=True, items=items, page=data.get('page', 1),
                    hasMore=len(rows) > PAGE_SIZE and data.get('page', 1) < MAX_PAGE,
                    limited=len(rows) > PAGE_SIZE and data.get('page', 1) == MAX_PAGE)
    finally:
        SEARCH_SLOTS.release()


def es_command_line(args):
    # ES parses -search with triple quotes, not the MS C-runtime backslash escaping.
    # Serialize the validated option array, then quote the single search value for ES.
    # This is passed directly to CreateProcess; never to cmd.exe or PowerShell.
    return subprocess.list2cmdline(args[:-1]) + ' "' + args[-1].replace('"', '"""') + '"'


@lru_cache(maxsize=1)
def quicklook_pipe():
    # The running Store and desktop editions expose the same per-user pipe.
    result = subprocess.run([os.path.join(os.environ['SystemRoot'], 'System32', 'whoami.exe'),
                             '/user', '/fo', 'csv', '/nh'], capture_output=True, timeout=3,
                            creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    sid = re.search(rb'S-1-\d+(?:-\d+)+', result.stdout)
    if not sid:
        raise ValueError('无法确定当前用户的 QuickLook 会话')
    return '\\\\.\\pipe\\QuickLook.App.Pipe.' + sid[0].decode('ascii')


def send_quicklook(action, path):
    import _winapi
    pipe = quicklook_pipe()
    _winapi.WaitNamedPipe(pipe, 500)
    handle = _winapi.CreateFile(pipe, _winapi.GENERIC_WRITE, 0, _winapi.NULL,
                               _winapi.OPEN_EXISTING, _winapi.FILE_FLAG_OVERLAPPED, _winapi.NULL)
    try:
        message = ('QuickLook.App.PipeMessages.' + action + '|' + path + '|\n').encode('utf-8')
        operation, error = _winapi.WriteFile(handle, message, overlapped=True)
        try:
            if error == _winapi.ERROR_IO_PENDING and _winapi.WaitForSingleObject(operation.event, 1000) != _winapi.WAIT_OBJECT_0:
                raise ValueError('QuickLook 响应超时，请稍后重试')
            written, error = operation.GetOverlappedResult(True)
            if error or written != len(message):
                raise ValueError('QuickLook 预览请求未发送完成')
        finally:
            operation.cancel()
            operation.GetOverlappedResult(True)
    finally:
        _winapi.CloseHandle(handle)


def preview(data):
    if os.name != 'nt':
        raise ValueError('QuickLook 预览仅支持 Windows')
    action = data.get('action', 'show')
    if action not in ('show', 'switch', 'close'):
        raise ValueError('预览操作无效')
    path = '' if action == 'close' else absolute_path(data.get('path'))
    if '|' in path or any(ord(c) < 32 for c in path):
        raise ValueError('预览路径含无效字符')
    if path and not os.path.exists(path):
        raise ValueError('文件不存在或不可访问，请重新搜索')
    try:
        send_quicklook({'show': 'Invoke', 'switch': 'Switch', 'close': 'Close'}[action], path)
    except (OSError, subprocess.SubprocessError):
        raise ValueError('无法连接 QuickLook，请先启动 QuickLook 后重试') from None
    return dict(ok=True)


def handle(handler, path, method):
    cfg = handler.server.cfg
    try:
        if method == 'GET' and path == '/api/files/config':
            snapshot = cfg.snapshot()
            handler.send_json(dict(ok=True, folders=snapshot['folders'], settings=snapshot['fileSearch']))
            return
        if method != 'POST':
            handler.send_err(404, '接口不存在')
            return
        data, error = handler.read_json_body()
        if error:
            raise ValueError(error)
        if not isinstance(data, dict):
            raise ValueError('请求必须是对象')
        if path == '/api/files/folders/save':
            result = dict(ok=True, folder=save_folder(cfg, data))
        elif path == '/api/files/folders/remove':
            remove_folder(cfg, data.get('id'))
            result = dict(ok=True)
        elif path == '/api/files/folders/reorder':
            reorder_folders(cfg, data.get('ids'))
            result = dict(ok=True)
        elif path == '/api/files/settings':
            es_path = absolute_path(data.get('esPath'))
            if not es_path.lower().endswith('.exe') or not os.path.isfile(es_path):
                raise ValueError('请选择存在的 ES 可执行文件（.exe）')
            cfg.update(lambda c: c['fileSearch'].update(esPath=es_path))
            result = dict(ok=True)
        elif path == '/api/files/search':
            snapshot = cfg.snapshot()
            result = search(snapshot['fileSearch'], snapshot['folders'], data)
        elif path == '/api/files/preview':
            result = preview(data)
        elif path == '/api/files/open':
            target = absolute_path(data.get('path'))
            mode = data.get('mode', 'explorer')
            if mode not in ('explorer', 'default'):
                raise ValueError('打开方式无效')
            if not os.path.exists(target):
                raise ValueError('位置不存在或不可访问，请重新搜索或修改路径')
            if mode == 'explorer' or os.path.isdir(target):
                result = open_location(dict(path=target, mode='explorer'))
            elif os.name == 'nt':
                os.startfile(target)
                result = dict(ok=True)
            else:
                raise ValueError('默认程序打开文件仅支持 Windows')
        else:
            handler.send_err(404, '接口不存在')
            return
        handler.send_json(result)
    except (ValueError, OSError) as exc:
        handler.send_err(400, str(exc))
