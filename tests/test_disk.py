"""Tests for luminos_lib/disk.py"""

import unittest
from unittest.mock import patch, MagicMock

from luminos_lib.disk import _human_size, top_directories, get_disk_usage


class TestHumanSize(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(_human_size(512), "512 B")

    def test_kilobytes(self):
        self.assertEqual(_human_size(1024), "1.0 KB")

    def test_megabytes(self):
        self.assertEqual(_human_size(1024 * 1024), "1.0 MB")

    def test_gigabytes(self):
        self.assertEqual(_human_size(1024 ** 3), "1.0 GB")

    def test_terabytes(self):
        self.assertEqual(_human_size(1024 ** 4), "1.0 TB")

    def test_zero_bytes(self):
        self.assertEqual(_human_size(0), "0 B")

    def test_fractional_kb(self):
        result = _human_size(1536)  # 1.5 KB
        self.assertEqual(result, "1.5 KB")


class TestTopDirectories(unittest.TestCase):
    def _entries(self, sizes):
        return [{"path": f"/dir{i}", "size_bytes": s, "size_human": _human_size(s)}
                for i, s in enumerate(sizes)]

    def test_returns_top_n(self):
        entries = self._entries([100, 500, 200, 800, 300, 50])
        top = top_directories(entries, n=3)
        self.assertEqual(len(top), 3)
        self.assertEqual(top[0]["size_bytes"], 800)
        self.assertEqual(top[1]["size_bytes"], 500)
        self.assertEqual(top[2]["size_bytes"], 300)

    def test_fewer_than_n_entries(self):
        entries = self._entries([100, 200])
        top = top_directories(entries, n=5)
        self.assertEqual(len(top), 2)

    def test_empty(self):
        self.assertEqual(top_directories([], n=5), [])

    def test_default_n_is_five(self):
        entries = self._entries([i * 100 for i in range(10)])
        top = top_directories(entries)
        self.assertEqual(len(top), 5)


class TestGetDiskUsage(unittest.TestCase):
    def _mock_du(self, output, returncode=0):
        return MagicMock(returncode=returncode, stdout=output)

    def test_parses_du_output(self):
        du_output = "4096\t/tmp/mydir\n1024\t/tmp/mydir/sub\n"
        with patch("subprocess.run", return_value=self._mock_du(du_output)):
            result = get_disk_usage("/tmp/mydir")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["size_bytes"], 4096)
        self.assertEqual(result[0]["path"], "/tmp/mydir")

    def test_skips_hidden_dirs_by_default(self):
        du_output = "1024\t/tmp/mydir/.git\n2048\t/tmp/mydir\n"
        with patch("subprocess.run", return_value=self._mock_du(du_output)):
            result = get_disk_usage("/tmp/mydir")
        paths = [r["path"] for r in result]
        self.assertNotIn("/tmp/mydir/.git", paths)

    def test_includes_hidden_dirs_when_requested(self):
        du_output = "1024\t/tmp/mydir/.git\n2048\t/tmp/mydir\n"
        with patch("subprocess.run", return_value=self._mock_du(du_output)):
            result = get_disk_usage("/tmp/mydir", show_hidden=True)
        paths = [r["path"] for r in result]
        self.assertIn("/tmp/mydir/.git", paths)

    def test_timeout_returns_empty(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("du", 30)):
            result = get_disk_usage("/tmp/mydir")
        self.assertEqual(result, [])

    def test_file_not_found_returns_empty(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = get_disk_usage("/tmp/mydir")
        self.assertEqual(result, [])

    def test_size_human_is_populated(self):
        du_output = "1048576\t/tmp/mydir\n"
        with patch("subprocess.run", return_value=self._mock_du(du_output)):
            result = get_disk_usage("/tmp/mydir")
        self.assertEqual(result[0]["size_human"], "1.0 MB")


if __name__ == "__main__":
    unittest.main()
