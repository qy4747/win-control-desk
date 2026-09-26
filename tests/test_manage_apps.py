import tempfile
from pathlib import Path
import unittest

from tools.manage_apps import prepare


class AppSetupTests(unittest.TestCase):
    def test_merge_identity_and_running_guards(self):
        with tempfile.TemporaryDirectory() as td:
            current = dict(id='aaaaaaaa',name='sample',running=True,command='keep',
                actions=[dict(id='old',name='old',type='url',url='http://127.0.0.1',when='always')],cardButtons=[])
            spec = dict(name='sample',locations=[dict(id='repo',name='打开项目',path=td)],front=['custom:repo'])
            fields, _ = prepare(spec,current,[],[])
            self.assertEqual([a['id'] for a in fields['actions']],['old','repo'])
            self.assertEqual(fields['actions'][1]['when'],'always')
            self.assertNotIn('command',fields)
            self.assertEqual([b['action'] for b in fields['cardButtons'][:3]], ['toggle','web','custom:repo'])
            desktop, _ = prepare(spec, dict(current, kind='desktop'), [], [])
            self.assertEqual([b['action'] for b in desktop['cardButtons'][:3]], ['toggle','window:focus','custom:repo'])
            again, _ = prepare(spec,dict(current,**fields),[],[])
            self.assertEqual(fields,again)
            for changes in (dict(command='different'),dict(pid=1,created='stale'),dict(window={'hwnd':1}),
                            dict(followInstance='yes'), dict(front=['custom:missing']),dict(locations=[dict(name='bad',path=str(Path(td,'missing')))])):
                with self.assertRaises(ValueError): prepare(dict(spec,**changes),current,[],[])

    def test_new_interpreter_does_not_invent_entry_command(self):
        with tempfile.TemporaryDirectory() as td:
            process = dict(pid=123,created='now',exe=str(Path(td,'python.exe')))
            fields, selected = prepare(dict(name='TUI',pid=123,created='now'),None,[process],[])
            self.assertEqual(fields['command'],'')
            self.assertEqual(selected,process)
            self.assertEqual([b['action'] for b in fields['cardButtons'][:4]], ['toggle','window:focus','details','logs'])


if __name__ == '__main__':
    unittest.main()
