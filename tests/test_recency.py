"""Tests for luminos_lib/recency.py"""

import unittest
from unittest.mock import patch, MagicMock

from luminos_lib.recency import find_recent_files


class TestFindRecentFiles(unittest.TestCase):
    def _mock_find(self, lines):
        output = "\n".join(lines)
        return MagicMock(returncode=0, stdout=output)

    def test_returns_sorted_by_recency(self):
        lines = [
            "1000.0\t/tmp/old.py",
            "2000.0\t/tmp/new.py",
            "1500.0\t/tmp/mid.py",
        ]
        with patch("subprocess.run", return_value=self._mock_find(lines)):
            result = find_recent_files("/tmp")
        self.assertEqual(result[0]["name"], "new.py")
        self.assertEqual(result[1]["name"], "mid.py")
        self.assertEqual(result[2]["name"], "old.py")

    def test_limits_to_n(self):
        lines = [f"{i}.0\t/tmp/file{i}.py" for i in range(20)]
        with patch("subprocess.run", return_value=self._mock_find(lines)):
            result = find_recent_files("/tmp", n=5)
        self.assertEqual(len(result), 5)

    def test_entry_fields(self):
        lines = ["1700000000.0\t/tmp/subdir/script.py"]
        with patch("subprocess.run", return_value=self._mock_find(lines)):
            result = find_recent_files("/tmp")
        self.assertEqual(len(result), 1)
        entry = result[0]
        self.assertEqual(entry["name"], "script.py")
        self.assertEqual(entry["path"], "/tmp/subdir/script.py")
        self.assertIsInstance(entry["modified"], float)
        self.assertIsInstance(entry["modified_human"], str)

    def test_timeout_returns_empty(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("find", 30)):
            result = find_recent_files("/tmp")
        self.assertEqual(result, [])

    def test_file_not_found_returns_empty(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = find_recent_files("/tmp")
        self.assertEqual(result, [])

    def test_nonzero_returncode_returns_empty(self):
        mock = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=mock):
            result = find_recent_files("/tmp")
        self.assertEqual(result, [])

    def test_empty_output_returns_empty(self):
        mock = MagicMock(returncode=0, stdout="")
        with patch("subprocess.run", return_value=mock):
            result = find_recent_files("/tmp")
        self.assertEqual(result, [])

    def test_malformed_lines_skipped(self):
        lines = ["notvalid", "1000.0\t/tmp/good.py", "alsoinvalid"]
        with patch("subprocess.run", return_value=self._mock_find(lines)):
            result = find_recent_files("/tmp")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "good.py")


if __name__ == "__main__":
    unittest.main()
