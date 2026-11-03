"""Run: python -m unittest discover -s tests -p test_discovery_cards.py"""
import os
import unittest

from ops_monitor import card_executables, discovery_card


class DiscoveryCardTests(unittest.TestCase):
    def test_card_executables_skip_shared_hosts(self):
        app = dict(externalIdentity=dict(exe=r'C:\Apps\Music\music.exe'),
                   instanceMatch=dict(exe=r'C:\Py\python.exe'),
                   windowBinding=dict(exe=r'C:\Apps\Music\music.exe', match=dict(exe=r'C:\Apps\Music\music.exe')),
                   command=r'"C:\Apps\Tool\tool.exe" --tray')
        parse = lambda c: [r'C:\Apps\Tool\tool.exe', '--tray']
        self.assertEqual(card_executables(app, parse), {r'C:\Apps\Music\music.exe', r'C:\Apps\Tool\tool.exe'})
        self.assertEqual(card_executables(dict(command='python app.py'), lambda c: ['python', 'app.py']), set())
        self.assertEqual(card_executables(dict(command='a | b'), lambda c: None), set())

    def test_managed_wins_then_same_exe_hint(self):
        owners = {10: dict(id='a1', name='已管理')}
        cards = [(dict(id='m1', name='音乐'), {r'C:\Apps\Music\music.exe'})]
        self.assertEqual(discovery_card(10, r'C:\Apps\Music\music.exe', owners, cards), dict(id='a1', name='已管理', state='managed'))
        exe = r'c:\apps\music\MUSIC.exe' if os.name == 'nt' else r'C:\Apps\Music\music.exe'
        self.assertEqual(discovery_card(11, exe, owners, cards), dict(id='m1', name='音乐', state='similar'))
        self.assertIsNone(discovery_card(12, r'C:\Apps\Other\other.exe', owners, cards))
        self.assertIsNone(discovery_card(13, r'C:\Py\python.exe', owners, [(dict(id='p', name='p'), {r'C:\Py\python.exe'})]))
        edge = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
        self.assertEqual(card_executables(dict(windowBinding=dict(exe=edge))), set())
        self.assertIsNone(discovery_card(14, edge, owners, [(dict(id='w', name='网页服务'), {edge})]))


if __name__ == '__main__':
    unittest.main()
