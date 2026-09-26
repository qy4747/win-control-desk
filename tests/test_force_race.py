"""Verified force-stop snapshots must not lose children born during startup."""
from types import SimpleNamespace
import unittest
from unittest import mock

import server
import win_metrics


class SuspensionContracts(unittest.TestCase):
    def native(self, suspend=lambda handle: 0, created=lambda handle: handle):
        kernel, native = mock.Mock(), mock.Mock()
        kernel.OpenProcess.side_effect = lambda rights, inherit, pid: pid
        def times(handle, birth, exited, *_):
            birth._obj.value = created(handle)
            exited._obj.value = 0
            return 1
        kernel.GetProcessTimes.side_effect = times
        native.NtSuspendProcess.side_effect = suspend
        native.NtResumeProcess.return_value = 0
        return kernel, native

    def test_reused_pid_is_not_suspended(self):
        kernel, native = self.native(created=lambda handle: 200)
        with mock.patch.object(win_metrics.C, 'WinDLL', side_effect=[kernel, native], create=True):
            with self.assertRaises(OSError):
                with win_metrics.SuspendedProcesses() as frozen:
                    frozen.add(42, '100')
        native.NtSuspendProcess.assert_not_called()
        native.NtResumeProcess.assert_not_called()
        kernel.CloseHandle.assert_called_once_with(42)

    def test_failed_child_pause_resumes_parent_and_closes_both_handles(self):
        kernel, native = self.native(suspend=lambda handle: -1 if handle == 20 else 0)
        with mock.patch.object(win_metrics.C, 'WinDLL', side_effect=[kernel, native], create=True):
            with self.assertRaises(OSError):
                with win_metrics.SuspendedProcesses() as frozen:
                    frozen.add(10, '10')
                    frozen.add(20, '20')
        native.NtResumeProcess.assert_called_once_with(10)
        self.assertEqual(kernel.CloseHandle.call_args_list, [mock.call(20), mock.call(10)])

    def test_body_failure_resumes_each_pause_once_and_handles_are_retained(self):
        kernel, native = self.native()
        with mock.patch.object(win_metrics.C, 'WinDLL', side_effect=[kernel, native], create=True):
            with self.assertRaisesRegex(ValueError, 'fixture failure'):
                with win_metrics.SuspendedProcesses() as frozen:
                    frozen.add(10, '10'); frozen.add(20, '20'); frozen.add(10, '10')
                    kernel.CloseHandle.assert_not_called()
                    raise ValueError('fixture failure')
        self.assertEqual(native.NtSuspendProcess.call_args_list, [mock.call(10), mock.call(20)])
        self.assertEqual(native.NtResumeProcess.call_args_list, [mock.call(20), mock.call(10)])
        self.assertEqual(kernel.CloseHandle.call_args_list, [mock.call(20), mock.call(10)])


class ForceBoundaryContracts(unittest.TestCase):
    def fixture(self, members):
        calls = []
        class Frozen:
            def __init__(self): self.identities = {}
            def __enter__(self): return self
            def add(self, pid, created):
                calls.append(('pause', pid)); self.identities[pid] = created
            def __exit__(self, *args): calls.append(('resume-survivors',)); return False
        table = {10: {'identity': '100'}, 20: {'identity': '200'}, 99: {'identity': '300'}}
        targets = [{'kind':'group', 'id':10, 'members':row, 'scoped':True} for row in members]
        patches = [
            mock.patch.object(server, '_win_process_table', return_value=table),
            mock.patch.object(server, 'resolve_app_stop_target', side_effect=[(t, None) for t in targets]),
            mock.patch.object(server, 'SELF_PID', 1),
            mock.patch.object(server, 'SELF_UID', 'fixture-owner'),
            mock.patch.object(server, 'process_uid', return_value='fixture-owner'),
            mock.patch.object(win_metrics, 'SuspendedProcesses', Frozen),
            mock.patch.object(win_metrics, 'terminate_verified', side_effect=lambda ids: calls.append(('terminate', dict(ids))) or []),
        ]
        for patch in patches: patch.start(); self.addCleanup(patch.stop)
        return calls, Frozen

    def test_children_born_after_first_snapshot_are_paused_before_final_termination(self):
        calls, _ = self.fixture([[10], [10,20], [10,20]])
        target, error = server.force_windows_target({'id':'fixture'})
        self.assertIsNone(error)
        self.assertEqual(target['members'], [10,20])
        self.assertEqual(calls, [('pause',10), ('pause',20),
                                ('terminate',{10:'100',20:'200'}), ('resume-survivors',)])
        self.assertFalse(any(99 in call[1:] for call in calls), 'independent child card must stay outside the stop boundary')

    def test_owner_change_fails_before_suspension_or_termination(self):
        calls, _ = self.fixture([[10]])
        with mock.patch.object(server, 'process_uid', return_value='other-owner'):
            target, error = server.force_windows_target({'id':'fixture'})
        self.assertIsNone(target)
        self.assertIn('所有者', error)
        self.assertEqual(calls, [('resume-survivors',)])

    def test_boundary_removed_on_refresh_is_not_terminated(self):
        calls, _ = self.fixture([[10,20], [10]])
        target, error = server.force_windows_target({'id':'fixture'})
        self.assertIsNone(error)
        self.assertEqual(target['members'], [10])
        self.assertIn(('terminate', {10:'100'}), calls)
        self.assertNotIn(('terminate', {10:'100',20:'200'}), calls)

    def test_native_failure_returns_failure_and_never_terminates(self):
        calls, Frozen = self.fixture([[10]])
        with mock.patch.object(Frozen, 'add', side_effect=OSError('fixture denial')), mock.patch.object(server.LOG, 'exception'):
            target, error = server.force_windows_target({'id':'fixture'})
        self.assertIsNone(target)
        self.assertIn('未确认', error)
        self.assertEqual(calls, [('resume-survivors',)])

    def test_termination_failure_cannot_be_reported_as_success(self):
        calls, _ = self.fixture([[10], [10]])
        with mock.patch.object(win_metrics, 'terminate_verified', return_value=[10]):
            target, error = server.force_windows_target({'id':'fixture'})
        self.assertIsNone(target)
        self.assertIn('无法强制结束', error)
        self.assertEqual(calls[-1], ('resume-survivors',))


if __name__ == '__main__':
    unittest.main()
