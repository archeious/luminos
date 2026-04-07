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
    survey_signals,
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


class TestSurveySignals(unittest.TestCase):
    def _f(self, name, description="", category="source"):
        return {"name": name, "path": f"/x/{name}", "category": category,
                "size": 10, "description": description}

    def test_empty_input(self):
        s = survey_signals([])
        self.assertEqual(s["total_files"], 0)
        self.assertEqual(s["extension_histogram"], {})
        self.assertEqual(s["file_descriptions"], {})
        self.assertEqual(s["filename_samples"], [])

    def test_extension_histogram_uses_lowercase_and_keeps_none(self):
        files = [
            self._f("a.PY"), self._f("b.py"), self._f("c.py"),
            self._f("README"), self._f("Makefile"),
        ]
        s = survey_signals(files)
        self.assertEqual(s["extension_histogram"][".py"], 3)
        self.assertEqual(s["extension_histogram"]["(none)"], 2)

    def test_file_descriptions_aggregated_and_truncated(self):
        long_desc = "x" * 200
        files = [
            self._f("a.py", "Python script, ASCII text"),
            self._f("b.py", "Python script, ASCII text"),
            self._f("c.bin", long_desc),
        ]
        s = survey_signals(files)
        self.assertEqual(s["file_descriptions"]["Python script, ASCII text"], 2)
        # The long description was truncated and still counted once
        truncated_keys = [k for k in s["file_descriptions"] if k.startswith("xxx") and k.endswith("...")]
        self.assertEqual(len(truncated_keys), 1)
        self.assertLessEqual(len(truncated_keys[0]), 84)  # 80 + "..."

    def test_descriptions_skipped_when_empty(self):
        files = [self._f("a.py", ""), self._f("b.py", None)]
        s = survey_signals(files)
        self.assertEqual(s["file_descriptions"], {})

    def test_top_n_caps_at_20(self):
        files = [self._f(f"f{i}.ext{i}") for i in range(50)]
        s = survey_signals(files)
        self.assertEqual(len(s["extension_histogram"]), 20)

    def test_filename_samples_evenly_drawn(self):
        files = [self._f(f"file_{i:04d}.txt") for i in range(100)]
        s = survey_signals(files, max_samples=10)
        self.assertEqual(len(s["filename_samples"]), 10)
        # First sample is the first file (stride 10, index 0)
        self.assertEqual(s["filename_samples"][0], "file_0000.txt")
        # Last sample is around index 90, not 99
        self.assertTrue(s["filename_samples"][-1].startswith("file_009"))

    def test_filename_samples_returns_all_when_under_cap(self):
        files = [self._f(f"f{i}.txt") for i in range(5)]
        s = survey_signals(files, max_samples=20)
        self.assertEqual(len(s["filename_samples"]), 5)

    def test_total_files_matches_input(self):
        files = [self._f(f"f{i}.py") for i in range(7)]
        self.assertEqual(survey_signals(files)["total_files"], 7)


if __name__ == "__main__":
    unittest.main()
