"""Tests for luminos_lib/code.py"""

import unittest
from unittest.mock import patch, MagicMock

from luminos_lib.code import (
    LANG_EXTENSIONS,
    LARGE_LINE_THRESHOLD,
    LARGE_SIZE_THRESHOLD,
    _count_lines,
    detect_languages,
    find_large_files,
)


def _make_file_record(name, category="source", size=100):
    return {"name": name, "path": f"/tmp/{name}", "category": category, "size": size}


class TestCountLines(unittest.TestCase):
    def test_returns_line_count(self):
        mock_result = MagicMock(returncode=0, stdout="42 /tmp/foo.py\n")
        with patch("subprocess.run", return_value=mock_result):
            self.assertEqual(_count_lines("/tmp/foo.py"), 42)

    def test_returns_zero_on_failure(self):
        mock_result = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=mock_result):
            self.assertEqual(_count_lines("/tmp/foo.py"), 0)

    def test_returns_zero_on_timeout(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("wc", 10)):
            self.assertEqual(_count_lines("/tmp/foo.py"), 0)

    def test_returns_zero_on_file_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(_count_lines("/tmp/foo.py"), 0)


class TestDetectLanguages(unittest.TestCase):
    def _mock_lines(self, n):
        return MagicMock(returncode=0, stdout=f"{n} /tmp/file\n")

    def test_detects_python(self):
        files = [_make_file_record("main.py")]
        with patch("subprocess.run", return_value=self._mock_lines(50)):
            langs, loc = detect_languages(files)
        self.assertIn("Python", langs)
        self.assertEqual(loc["Python"], 50)

    def test_ignores_non_source_files(self):
        files = [
            _make_file_record("main.py", category="source"),
            _make_file_record("config.json", category="config"),
        ]
        with patch("subprocess.run", return_value=self._mock_lines(10)):
            langs, loc = detect_languages(files)
        self.assertNotIn("config.json", str(langs))
        self.assertEqual(len(langs), 1)

    def test_multiple_languages(self):
        files = [
            _make_file_record("main.py"),
            _make_file_record("app.js"),
        ]
        with patch("subprocess.run", return_value=self._mock_lines(20)):
            langs, loc = detect_languages(files)
        self.assertIn("Python", langs)
        self.assertIn("JavaScript", langs)

    def test_unknown_extension_maps_to_other(self):
        files = [_make_file_record("script.xyz")]
        with patch("subprocess.run", return_value=self._mock_lines(5)):
            langs, loc = detect_languages(files)
        self.assertIn("Other", langs)

    def test_empty_input(self):
        langs, loc = detect_languages([])
        self.assertEqual(langs, [])
        self.assertEqual(loc, {})

    def test_on_file_callback(self):
        files = [_make_file_record("a.py"), _make_file_record("b.py")]
        seen = []
        with patch("subprocess.run", return_value=self._mock_lines(10)):
            detect_languages(files, on_file=seen.append)
        self.assertEqual(len(seen), 2)

    def test_loc_accumulates_across_files(self):
        files = [_make_file_record("a.py"), _make_file_record("b.py")]
        with patch("subprocess.run", return_value=self._mock_lines(100)):
            langs, loc = detect_languages(files)
        self.assertEqual(loc["Python"], 200)


class TestFindLargeFiles(unittest.TestCase):
    def test_large_by_lines(self):
        files = [_make_file_record("big.py", size=100)]
        mock_result = MagicMock(returncode=0, stdout=f"{LARGE_LINE_THRESHOLD + 1} /tmp/big.py\n")
        with patch("subprocess.run", return_value=mock_result):
            large = find_large_files(files)
        self.assertEqual(len(large), 1)
        self.assertEqual(large[0]["name"], "big.py")
        self.assertTrue(any("lines" in r for r in large[0]["reasons"]))

    def test_large_by_size(self):
        files = [_make_file_record("huge.py", size=LARGE_SIZE_THRESHOLD + 1)]
        mock_result = MagicMock(returncode=0, stdout="10 /tmp/huge.py\n")
        with patch("subprocess.run", return_value=mock_result):
            large = find_large_files(files)
        self.assertEqual(len(large), 1)
        self.assertTrue(any("size" in r for r in large[0]["reasons"]))

    def test_normal_file_not_flagged(self):
        files = [_make_file_record("small.py", size=500)]
        mock_result = MagicMock(returncode=0, stdout="50 /tmp/small.py\n")
        with patch("subprocess.run", return_value=mock_result):
            large = find_large_files(files)
        self.assertEqual(large, [])

    def test_ignores_non_source(self):
        files = [_make_file_record("data.csv", category="data", size=LARGE_SIZE_THRESHOLD + 1)]
        large = find_large_files(files)
        self.assertEqual(large, [])

    def test_empty_input(self):
        self.assertEqual(find_large_files([]), [])


if __name__ == "__main__":
    unittest.main()
