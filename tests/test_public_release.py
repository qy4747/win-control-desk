"""Regression tests for release checks; all fixtures stay in temporary directories."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools import audit_public_tree as audit
from tools import build_release as release
from tools import check_project as checks


class ThemeAndAssetChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.static = self.root / 'static'
        for name, value in [('ROOT', self.root), ('STATIC', self.static)]:
            patcher = mock.patch.object(checks, name, value)
            patcher.start(); self.addCleanup(patcher.stop)
        metadata = dict(id='ops', name='Base', author='Fixture', desc='Fixture', colors=['#ffffff'])
        self.write('static/themes/ops.json', json.dumps(metadata))
        self.write('static/themes/ops.css', ':root { --x: 1; }')
        for filename in checks.SHARED_THEME_STYLES:
            self.write('static/themes/'+filename, '/* shared */')
        self.write('static/themes/packs/sample/theme.json', json.dumps(metadata))
        self.write('static/themes/packs/sample/theme.css', '/* sample */')
        self.write('static/themes/packs/sample/preview.svg', '<svg/>')
        self.write('static/index.html', '<!doctype html><title>Fixture</title>')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_shared_styles_and_folder_identified_packs_are_registered(self):
        self.assertIn('pack-sample', checks.check_themes())

    def test_orphan_style_missing_pack_css_and_missing_preview_fail(self):
        extra = self.write('static/themes/unregistered.css', '/* orphan */')
        with self.assertRaisesRegex(checks.CheckError, '未注册'):
            checks.check_themes()
        extra.unlink()
        css = self.static/'themes/packs/sample/theme.css'
        css.unlink()
        with self.assertRaisesRegex(checks.CheckError, 'CSS'):
            checks.check_themes()
        self.write('static/themes/packs/sample/theme.css', '/* restored fixture */')
        (css.parent/'preview.svg').unlink()
        with self.assertRaisesRegex(checks.CheckError, '预览'):
            checks.check_themes()

    def test_nested_relative_css_reference_is_checked_and_cannot_escape(self):
        source = self.static/'themes/packs/sample/theme.css'
        source.write_text('a { background: url("assets/missing.png"); }', encoding='utf-8')
        with self.assertRaisesRegex(checks.CheckError, '不存在'):
            checks.check_static_references()
        self.write('static/themes/packs/sample/assets/missing.png', 'fixture')
        self.assertIn('静态资源', checks.check_static_references())
        with self.assertRaisesRegex(checks.CheckError, '越界'):
            checks.check_static_path(source, '/%2e%2e/outside.txt')

    def test_pack_assets_require_their_own_current_fingerprint(self):
        self.write('总控台.app/Contents/Resources/AppIcon.icns', 'icon fixture')
        image = self.write('static/themes/packs/sample/assets/card.png', 'card fixture')
        def ledger():
            return '`CLEARED` `REVIEW_REQUIRED` `BLOCKED` `TO_REPLACE`\n'+ '\n'.join(
                f'- `{p.relative_to(self.root).as_posix()}` — `{hashlib.sha256(p.read_bytes()).hexdigest()}`'
                for p in checks.provenance_files())
        self.write('ASSET_PROVENANCE.md', ledger())
        checks.check_asset_provenance()
        image.write_text('changed card', encoding='utf-8')
        with self.assertRaisesRegex(checks.CheckError, 'SHA-256'):
            checks.check_asset_provenance()
        self.write('ASSET_PROVENANCE.md', ledger())
        self.write('static/themes/packs/sample/assets/new.png', 'new fixture')
        with self.assertRaisesRegex(checks.CheckError, '缺少文件'):
            checks.check_asset_provenance()

    def test_a_hash_registered_for_another_file_is_not_sufficient(self):
        first = self.write('static/assets/one.png', 'one')
        second = self.write('static/assets/two.png', 'two')
        self.write('总控台.app/Contents/Resources/AppIcon.icns', 'icon')
        files = checks.provenance_files()
        hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        hashes[first], hashes[second] = hashes[second], hashes[first]
        self.write('ASSET_PROVENANCE.md', '`CLEARED` `REVIEW_REQUIRED` `BLOCKED` `TO_REPLACE`\n'+'\n'.join(
            f'- `{p.relative_to(self.root).as_posix()}` — `{hashes[p]}`' for p in files))
        with self.assertRaisesRegex(checks.CheckError, 'SHA-256'):
            checks.check_asset_provenance()


class ReleaseDiagnostics(unittest.TestCase):
    def test_failure_output_preserves_first_traceback_and_unicode(self):
        code = "print('FIRST_TRACE 中文'); print('\\n'.join('line '+str(i) for i in range(45))); raise SystemExit(1)"
        with self.assertRaises(checks.CheckError) as caught:
            checks.command_output([sys.executable, '-c', code])
        self.assertIn('FIRST_TRACE 中文', str(caught.exception))
        self.assertIn('line 44', str(caught.exception))

    def test_python_312_minimum_is_explicit(self):
        with mock.patch.object(checks.sys, 'version_info', (3, 11)):
            with self.assertRaisesRegex(checks.CheckError, '3.12'):
                checks.check_python_version()

    def test_top_level_runtime_modules_cannot_be_omitted_from_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ('server.py', 'service_web.py'):
                (root/name).write_text('# fixture', encoding='utf-8')
            with mock.patch.object(release, 'ROOT', root), mock.patch.object(release, 'INCLUDE', ('server.py',)):
                with self.assertRaisesRegex(SystemExit, 'service_web.py'):
                    release.iter_release_files()
            with mock.patch.object(release, 'ROOT', root), mock.patch.object(release, 'INCLUDE', ('server.py', 'service_web.py')):
                self.assertEqual(len(release.iter_release_files()), 2)

    def test_celadon_keeps_floating_panel_positioning_in_behavior_layer(self):
        import re
        css = (checks.STATIC / 'themes/packs/celadon/theme.css').read_text(encoding='utf-8')
        matched = 0
        for selector, declarations in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
            if any(name in selector for name in ('.drawer', '.palette', '.port-discovery')) and '::' not in selector:
                matched += 1
                self.assertNotRegex(declarations, r'position\s*:\s*relative', selector)
        self.assertGreater(matched, 0)

    def test_demo_registers_all_current_theme_ids_without_user_data(self):
        from tools.ui_demo import Demo
        demo = Demo(9610)
        expected = {ident for _, ident, _, _ in checks.theme_records()}
        self.assertEqual({theme['id'] for theme in demo.data['themes']}, expected)
        self.assertTrue(all('css' in theme for theme in demo.data['themes']))

    def test_privacy_classification_does_not_emit_secret_or_personal_value(self):
        value = b'C:' + b'/' + b'Users' + b'/private-person/project'
        token = b'gh' + b'p_' + b'A'*36
        result = audit.classify(value+b' '+token)
        self.assertIn('personal-path', result)
        self.assertIn('secret-pattern', result)
        self.assertNotIn('private-person', json.dumps(result))
        self.assertNotIn(token.decode(), json.dumps(result))

    @unittest.skipUnless(shutil.which('git'), 'Git required for history fixture')
    def test_clean_current_tree_does_not_hide_reachable_historical_leak(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            audit.git(root, 'init', '-q')
            path = root/'fixture.txt'
            path.write_bytes(b'C:' + b'/' + b'Users' + b'/private-person/project')
            audit.git(root, 'add', 'fixture.txt')
            opts = ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath='+str(root/'no-hooks')]
            audit.git(root, *opts, 'commit', '-qm', 'fixture source')
            path.write_text('sanitized fixture', encoding='utf-8')
            audit.git(root, 'add', 'fixture.txt')
            audit.git(root, *opts, 'commit', '-qm', 'fixture cleanup')
            self.assertEqual(audit.audit_working_tree(root)['findings'], [])
            history = audit.audit_history(root)
            self.assertTrue(any(f['kind'] == 'personal-path' for f in history['findings']))
            self.assertNotIn('private-person', json.dumps(history))


if __name__ == '__main__':
    unittest.main()
