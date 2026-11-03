import json
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import server
from log_center import LogCenter, TAIL, HEAD
from test_hardening import HttpHarness


class SummaryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.apps = [dict(id="ab000001", name="示例"), dict(id="ab000002", name="空日志")]
        self.now = 0
        self.center = LogCenter(lambda: self.now)
        self.path = self.dir / "ab000001.log"

    def summary(self):
        return self.center.summary(self.dir, self.apps)

    def test_bounded_samples_and_rotated_totals(self):
        middle = b"\nERROR outside sampled tail\n\0\n"
        tail = "a\nFaTaL exception\n错误：失败\nlast".encode()
        raw = b" " * HEAD + middle + b" " * TAIL + tail
        self.path.write_bytes(raw)
        backups = [b"\0warning\n", b"Traceback here\n", b"third"]
        for i, data in enumerate(backups, 1):
            Path(str(self.path) + "." + str(i)).write_bytes(data)
        (self.dir / "console.log").write_bytes(b"normal\n")
        (self.dir / "orphan.log").write_bytes(b"12345")
        (self.dir / "subdir").mkdir()
        (self.dir / "subdir" / "unrelated").write_bytes(b"123")
        result = self.summary()
        row, empty = result["apps"]
        self.assertEqual((row["bytes"], row["backupBytes"]), (len(raw), sum(map(len, backups))))
        self.assertEqual((row["errorCount"], row["lastLine"], row["nulDetected"]), (3, "last", True))
        self.assertEqual((empty["bytes"], empty["mtime"], empty["growthBytesPerHour"]), (0, None, None))
        self.assertEqual(result["console"]["lastLine"], "normal")
        self.assertEqual(result["totalBytes"], row["bytes"] + row["backupBytes"] + 12)
        self.assertGreaterEqual(row["mtime"], self.path.stat().st_mtime)

    def test_nul_at_head_or_tail_but_not_middle(self):
        for position, expected in [(0, True), (HEAD + 10, False), (HEAD + TAIL + 127, True)]:
            raw = bytearray(b"x" * (HEAD + TAIL + 128))
            raw[position] = 0
            self.path.write_bytes(raw)
            self.now += 16
            self.assertEqual(self.summary()["apps"][0]["nulDetected"], expected)

    def test_io_budget_does_not_scale_with_file_size(self):
        raw = b"x" * (5 * TAIL)
        self.path.write_bytes(raw)
        consumed = []

        class Meter(io.BytesIO):
            def read(self, n=-1):
                data = super().read(n)
                consumed.append(len(data))
                return data

        with patch("log_center.open", return_value=Meter(raw)):
            self.assertEqual(self.summary()["apps"][0]["bytes"], len(raw))
        self.assertLessEqual(sum(consumed), TAIL + HEAD)

    def test_cache_and_rate_survive_rotation_and_throttle_independently(self):
        self.path.write_bytes(b"x"*100)
        first = self.summary()
        self.now = 14
        os.rename(self.path, str(self.path) + ".1")
        self.path.write_bytes(b"x"*60)
        with patch("log_center.os.scandir", side_effect=AssertionError("cache should not touch disk")):
            self.assertIs(self.summary(), first)
        for now, rate in [(15, None), (45, None), (60, 3600), (90, 3600), (120, 0)]:
            self.now = now
            row = self.summary()["apps"][0]
            self.assertEqual((row["bytes"], row["backupBytes"], row["growthBytesPerHour"]), (60, 100, rate))

    def test_http_summary_and_glance_direct_control_session(self):
        harness = HttpHarness()
        self.addCleanup(harness.close)
        with patch.object(server, "LOGS_DIR", str(self.dir)):
            (self.dir / "console.log").write_bytes(b"ERROR demo")
            status, data, _ = harness.request("GET", "/api/logs/summary")
        self.assertEqual((status, data["console"]["errorCount"], data["totalBytes"]), (200, 1, 10))
        harness.cfg.update(lambda cfg: cfg.update(uiTheme="pack-papercut"))
        status, html, headers = harness.request("GET", "/glance")
        self.assertEqual(status, 200)
        self.assertIn(b'/themes/packs/papercut/theme.css', html)
        cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        request_headers = {"Content-Type": "application/json", "Sec-Fetch-Site": "same-origin",
                           "Cookie": cookie.split(";")[0]}
        self.assertEqual(harness.request("POST", "/api/ui/theme", json.dumps({"theme": "ops"}), request_headers)[0], 200)
        self.assertNotIn("Set-Cookie", harness.request("GET", "/glance", headers={"Host": "other.invalid"})[2])
