"""Run with: python -m unittest discover -s tests -p test_gpu_memory.py"""
import unittest
from unittest.mock import Mock

from win_metrics import Metrics


class GpuMemoryTests(unittest.TestCase):
    def test_native_totals_zero_failure_and_adapter_cleanup(self):
        metrics = object.__new__(Metrics)
        metrics.gdi, metrics.gpu_adapters = Mock(), []

        def open_adapter(pointer):
            pointer._obj.handle = pointer._obj.luid.low
            return 0

        def query(pointer):
            info = pointer._obj
            self.assertEqual(info.process, 123)
            self.assertEqual(info.segment, 0)
            info.usage = info.adapter * 1024
            return 0

        metrics.gdi.D3DKMTOpenAdapterFromLuid.side_effect = open_adapter
        metrics.gdi.D3DKMTQueryVideoMemoryInfo.side_effect = query
        closed = []
        metrics.gdi.D3DKMTCloseAdapter.side_effect = lambda p: closed.append(p._obj.value) or 0
        names = ['luid_0x00000000_0x00000001_phys_0', 'luid_0x00000000_0x00000002_phys_1']
        metrics.refresh_gpu_adapters(names + names)
        self.assertEqual(metrics.gpu_memory(123), 3072)
        self.assertEqual(len(metrics.gpu_adapters), 2)

        metrics.gdi.D3DKMTQueryVideoMemoryInfo.side_effect = lambda p: 0
        self.assertEqual(metrics.gpu_memory(123), 0)
        metrics.gdi.D3DKMTQueryVideoMemoryInfo.side_effect = [0, -1]
        self.assertIsNone(metrics.gpu_memory(123))
        metrics.refresh_gpu_adapters([])
        self.assertEqual(closed, [1, 2])
        self.assertIsNone(metrics.gpu_memory(123))

        metrics.gdi.D3DKMTOpenAdapterFromLuid.side_effect = lambda p: -1
        metrics.refresh_gpu_adapters(names)
        self.assertIsNone(metrics.gpu_memory(123))


if __name__ == '__main__':
    unittest.main()
