import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import file_tools as files
import server


def export_result(payload, code=0):
    def run(command, **kwargs):
        path = re.search(r'-export-json ("[^"]+"|\S+)', command)[1].strip('"')
        Path(path).write_bytes(payload)
        return subprocess.CompletedProcess([], code, b'', b'')
    return run


class FileToolsTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows QuickLook')
    def test_preview_commands_validate_paths_and_do_not_execute_files(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(files, 'send_quicklook') as send:
            path = Path(tmp, '中文 空格.txt'); path.write_text('preview')
            for action, command in [('show', 'Invoke'), ('switch', 'Switch')]:
                self.assertTrue(files.preview(dict(action=action, path=str(path)))['ok'])
                send.assert_called_with(command, str(path))
            files.preview(dict(action='close')); send.assert_called_with('Close', '')
            send.reset_mock()
            for data in [dict(action='Quit'), dict(path='relative'), dict(path=str(path)+'|Close'), dict(path=str(path)+'missing')]:
                with self.assertRaises(ValueError): files.preview(data)
            send.assert_not_called()
            send.side_effect = FileNotFoundError()
            with self.assertRaisesRegex(ValueError, '先启动 QuickLook'):
                files.preview(dict(path=str(path)))

    def test_migration_and_folder_lifecycle_preserve_disk_and_apps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / '中文 空格 & 目录'; path.mkdir()
            second = root / 'second'; second.mkdir()
            marker = path / 'keep.txt'; marker.write_text('keep')
            config_path = root / 'config.json'
            config_path.write_text(json.dumps({'schemaVersion': 6, 'apps': [{'id': 'app', 'name': 'retain'}]}), encoding='utf-8')
            cfg = server.Config(str(config_path))
            self.assertEqual(cfg.snapshot()['folders'], [])
            self.assertEqual(cfg.snapshot()['fileSearch']['esPath'], files.DEFAULT_ES_PATH)
            a = files.save_folder(cfg, dict(name='目录', path=str(path), group='开发'))
            b = files.save_folder(cfg, dict(name='第二个', path=str(second)))
            with self.assertRaisesRegex(ValueError, '已收藏'):
                files.save_folder(cfg, dict(name='重复', path=str(path)))
            files.save_folder(cfg, dict(a, name='改名', group='文档'))
            files.reorder_folders(cfg, [b['id'], a['id']])
            with self.assertRaises(ValueError):
                files.reorder_folders(cfg, [a['id'], a['id']])
            reloaded = server.Config(str(config_path))
            self.assertEqual([x['name'] for x in reloaded.snapshot()['folders']], ['第二个', '改名'])
            files.remove_folder(reloaded, a['id'])
            self.assertEqual(marker.read_text(), 'keep')
            self.assertEqual(reloaded.snapshot()['apps'][0]['name'], 'retain')
            self.assertEqual(reloaded.snapshot()['schemaVersion'], server.CURRENT_SCHEMA_VERSION)

    def test_validation_rejects_bad_input_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = server.Config(str(Path(tmp, 'config.json')))
            before = cfg.snapshot()
            for fields in (dict(name='missing', path=str(Path(tmp, 'missing'))),
                           dict(name='relative', path='relative'),
                           dict(name='x', path=tmp, group=[]),
                           dict(id='gone', name='x', path=tmp)):
                with self.subTest(fields=fields), self.assertRaises(ValueError):
                    files.save_folder(cfg, fields)
            self.assertEqual(before, cfg.snapshot())

    def test_query_filters_pagination_and_es_quoting(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = dict(esPath=str(Path(tmp, 'es.exe')))
            args = files.search_args(settings, [dict(id='a', path=tmp)], dict(
                query='"two words" | 中文', folderId='a', kind='file', extension='pdf;docx',
                minSize=1024, maxSize=2048, dateFrom='2026-09-01', dateTo='2026-09-21',
                sort='size', direction='descending', page=2))
            self.assertEqual(args[args.index('-n') + 1], '201')
            self.assertEqual(args[args.index('-viewport-offset') + 1], '100')
            self.assertEqual(args[args.index('-viewport-count') + 1], '101')
            self.assertEqual(args[-2], '-search')
            self.assertEqual(args[-1], '<"two words" | 中文> ext:pdf;docx size:>=1024 size:<=2048 dm:>=2026-09-01 dm:<2026-09-22')
            self.assertIn('"""two words"""', files.es_command_line(args))
            for bad in (dict(page=True), dict(page=1001), dict(minSize=float('nan')),
                        dict(minSize=2, maxSize=1), dict(dateFrom='bad'),
                        dict(dateFrom='2026-09-22', dateTo='2026-09-21'),
                        dict(extension='py -exit'), dict(sort='-exit'), dict(folderId='gone'), dict(query='x\n-exit')):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    files.search_args(settings, [], bad)

    @unittest.skipUnless(os.name == 'nt', 'Windows ES process')
    def test_results_empty_errors_and_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp, 'es.exe'); executable.touch()
            settings = dict(esPath=str(executable))
            rows = [dict(filename=str(Path(tmp, '中文 %d.txt' % i)), size=i, attributes=32, date_modified='2026-09-21T12:00:00') for i in range(101)]
            rows[0]['attributes'] = 16
            with mock.patch.object(files.subprocess, 'run', side_effect=export_result(json.dumps(rows, ensure_ascii=False).encode('utf-8-sig'))) as run:
                result = files.search(settings, [], {})
                self.assertEqual(len(result['items']), 100)
                self.assertTrue(result['hasMore'])
                self.assertIsNone(result['items'][0]['size'])
                self.assertEqual(result['items'][0]['kind'], 'folder')
                self.assertFalse(run.call_args.kwargs['shell'])
                self.assertEqual(run.call_args.kwargs['timeout'], 8)
            mixed = [rows[1], dict(rows[2], attributes=None, date_modified=None),
                     {key: value for key, value in rows[3].items() if key not in ('attributes', 'date_modified')}]
            with mock.patch.object(files.subprocess, 'run', side_effect=export_result(json.dumps(mixed).encode())):
                items = files.search(settings, [], {})['items']
                self.assertEqual([item['kind'] for item in items], ['file', 'unknown', 'unknown'])
                self.assertEqual([item['modified'] for item in items[1:]], ['', ''])
            for output in (b'', b'\r\n', b'[]'):
                with mock.patch.object(files.subprocess, 'run', side_effect=export_result(output)):
                    self.assertEqual(files.search(settings, [], {})['items'], [])
            for output, code in ((b'bad', 0), (b'[]', 8), (b'{}', 0)):
                with mock.patch.object(files.subprocess, 'run', side_effect=export_result(output, code)), self.assertRaises(ValueError):
                    files.search(settings, [], {})
            with mock.patch.object(files.subprocess, 'run', side_effect=subprocess.TimeoutExpired('es', 8)), self.assertRaisesRegex(ValueError, '超时'):
                files.search(settings, [], {})
            self.assertTrue(files.SEARCH_SLOTS.acquire(False)); files.SEARCH_SLOTS.release()


if __name__ == '__main__':
    unittest.main()
