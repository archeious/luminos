"""Tests for luminos_lib/filetypes.py"""

import os
import tempfile
import unittest
from unittest.mock import patch

from luminos_lib.filetypes import (
    EXTENSION_MAP,
    _classify_one,
    classify_files,
    summarize_categories,
)


class TestExtensionMap(unittest.TestCase):
    def test_python_is_source(self):
        self.assertEqual(EXTENSION_MAP[".py"], "source")

    def test_json_is_config(self):
        self.assertEqual(EXTENSION_MAP[".json"], "config")

    def test_csv_is_data(self):
        self.assertEqual(EXTENSION_MAP[".csv"], "data")

    def test_png_is_media(self):
        self.assertEqual(EXTENSION_MAP[".png"], "media")

    def test_md_is_document(self):
        self.assertEqual(EXTENSION_MAP[".md"], "document")

    def test_zip_is_archive(self):
        self.assertEqual(EXTENSION_MAP[".zip"], "archive")


class TestClassifyOne(unittest.TestCase):
    def test_known_extension(self):
        category, desc = _classify_one("script.py")
        self.assertEqual(category, "source")
        self.assertIsNone(desc)

    def test_known_extension_case_insensitive(self):
        category, desc = _classify_one("image.PNG")
        self.assertEqual(category, "media")
        self.assertIsNone(desc)

    def test_unknown_extension_falls_back_to_file_command(self):
        with patch("luminos_lib.filetypes._file_command", return_value="ASCII text"):
            category, desc = _classify_one("README")
            self.assertEqual(category, "source")
            self.assertEqual(desc, "ASCII text")

    def test_unknown_extension_unrecognized_file_output(self):
        with patch("luminos_lib.filetypes._file_command", return_value="data"):
            category, desc = _classify_one("somefile.xyz")
            self.assertEqual(category, "unknown")

    def test_file_command_timeout_returns_unknown(self):
        with patch("luminos_lib.filetypes._file_command", return_value=""):
            category, desc = _classify_one("oddfile")
            self.assertEqual(category, "unknown")


class TestSummarizeCategories(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(summarize_categories([]), {})

    def test_single_category(self):
        files = [{"category": "source"}, {"category": "source"}]
        result = summarize_categories(files)
        self.assertEqual(result, {"source": 2})

    def test_multiple_categories(self):
        files = [
            {"category": "source"},
            {"category": "config"},
            {"category": "source"},
            {"category": "media"},
        ]
        result = summarize_categories(files)
        self.assertEqual(result["source"], 2)
        self.assertEqual(result["config"], 1)
        self.assertEqual(result["media"], 1)


class TestClassifyFiles(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _make_file(self, name, content=""):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_classifies_python_file(self):
        self._make_file("script.py", "print('hello')")
        results = classify_files(self.tmpdir)
        names = [r["name"] for r in results]
        self.assertIn("script.py", names)
        py = next(r for r in results if r["name"] == "script.py")
        self.assertEqual(py["category"], "source")

    def test_excludes_hidden_files_by_default(self):
        self._make_file(".hidden.py")
        self._make_file("visible.py")
        results = classify_files(self.tmpdir)
        names = [r["name"] for r in results]
        self.assertNotIn(".hidden.py", names)
        self.assertIn("visible.py", names)

    def test_includes_hidden_files_when_requested(self):
        self._make_file(".hidden.py")
        results = classify_files(self.tmpdir, show_hidden=True)
        names = [r["name"] for r in results]
        self.assertIn(".hidden.py", names)

    def test_excludes_directories(self):
        excluded_dir = os.path.join(self.tmpdir, "node_modules")
        os.makedirs(excluded_dir)
        with open(os.path.join(excluded_dir, "pkg.js"), "w") as f:
            f.write("")
        self._make_file("main.py")
        results = classify_files(self.tmpdir, exclude=["node_modules"])
        names = [r["name"] for r in results]
        self.assertNotIn("pkg.js", names)
        self.assertIn("main.py", names)

    def test_on_file_callback(self):
        self._make_file("a.py")
        self._make_file("b.py")
        seen = []
        classify_files(self.tmpdir, on_file=seen.append)
        self.assertEqual(len(seen), 2)

    def test_size_is_populated(self):
        self._make_file("data.json", '{"key": "value"}')
        results = classify_files(self.tmpdir)
        item = next(r for r in results if r["name"] == "data.json")
        self.assertGreater(item["size"], 0)


if __name__ == "__main__":
    unittest.main()
