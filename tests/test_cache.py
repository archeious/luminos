"""Tests for luminos_lib/cache.py"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from luminos_lib.cache import (
    _CacheManager,
    _sha256_path,
    _get_investigation_id,
    CACHE_ROOT,
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _make_manager(root):
    cm = _CacheManager.__new__(_CacheManager)
    cm.investigation_id = "test-id"
    cm.target = root
    cm.root = os.path.join(root, "cache")
    cm.files_dir = os.path.join(cm.root, "files")
    cm.dirs_dir = os.path.join(cm.root, "dirs")
    cm.log_path = os.path.join(cm.root, "investigation.log")
    cm.meta_path = os.path.join(cm.root, "meta.json")
    os.makedirs(cm.files_dir, exist_ok=True)
    os.makedirs(cm.dirs_dir, exist_ok=True)
    return cm


def _file_entry(**overrides):
    base = {
        "path": "/tmp/foo.py",
        "relative_path": "foo.py",
        "summary": "A Python file.",
        "cached_at": _now(),
        "size_bytes": 128,
        "category": "source",
    }
    base.update(overrides)
    return base


def _dir_entry(**overrides):
    base = {
        "path": "/tmp/mydir",
        "relative_path": "mydir",
        "summary": "A directory.",
        "cached_at": _now(),
        "child_count": 3,
        "dominant_category": "source",
    }
    base.update(overrides)
    return base


class TestSha256Path(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(_sha256_path("/foo/bar"), _sha256_path("/foo/bar"))

    def test_different_paths_differ(self):
        self.assertNotEqual(_sha256_path("/foo/bar"), _sha256_path("/foo/baz"))

    def test_returns_hex_string(self):
        result = _sha256_path("/foo")
        self.assertIsInstance(result, str)
        self.assertEqual(len(result), 64)


class TestWriteEntry(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cm = _make_manager(self.tmpdir)

    def test_valid_file_entry(self):
        result = self.cm.write_entry("file", "/tmp/foo.py", _file_entry())
        self.assertEqual(result, "ok")

    def test_valid_dir_entry(self):
        result = self.cm.write_entry("dir", "/tmp/mydir", _dir_entry())
        self.assertEqual(result, "ok")

    def test_missing_required_field_file(self):
        entry = _file_entry()
        del entry["summary"]
        result = self.cm.write_entry("file", "/tmp/foo.py", entry)
        self.assertIn("Error", result)
        self.assertIn("summary", result)

    def test_missing_required_field_dir(self):
        entry = _dir_entry()
        del entry["child_count"]
        result = self.cm.write_entry("dir", "/tmp/mydir", entry)
        self.assertIn("Error", result)
        self.assertIn("child_count", result)

    def test_raw_content_rejected(self):
        entry = _file_entry(content="raw file data")
        result = self.cm.write_entry("file", "/tmp/foo.py", entry)
        self.assertIn("Error", result)

    def test_valid_confidence(self):
        entry = _file_entry(confidence=0.85, confidence_reason="")
        result = self.cm.write_entry("file", "/tmp/foo.py", entry)
        self.assertEqual(result, "ok")

    def test_confidence_zero(self):
        entry = _file_entry(confidence=0.0, confidence_reason="completely unknown")
        result = self.cm.write_entry("file", "/tmp/foo.py", entry)
        self.assertEqual(result, "ok")

    def test_confidence_one(self):
        entry = _file_entry(confidence=1.0)
        result = self.cm.write_entry("file", "/tmp/foo.py", entry)
        self.assertEqual(result, "ok")

    def test_confidence_out_of_range_high(self):
        entry = _file_entry(confidence=1.5)
        result = self.cm.write_entry("file", "/tmp/foo.py", entry)
        self.assertIn("Error", result)
        self.assertIn("confidence", result)

    def test_confidence_out_of_range_low(self):
        entry = _file_entry(confidence=-0.1)
        result = self.cm.write_entry("file", "/tmp/foo.py", entry)
        self.assertIn("Error", result)

    def test_confidence_wrong_type(self):
        entry = _file_entry(confidence="high")
        result = self.cm.write_entry("file", "/tmp/foo.py", entry)
        self.assertIn("Error", result)

    def test_confidence_reason_wrong_type(self):
        entry = _file_entry(confidence=0.5, confidence_reason=42)
        result = self.cm.write_entry("file", "/tmp/foo.py", entry)
        self.assertIn("Error", result)

    def test_confidence_without_reason_is_ok(self):
        entry = _file_entry(confidence=0.9)
        result = self.cm.write_entry("file", "/tmp/foo.py", entry)
        self.assertEqual(result, "ok")

    def test_written_file_is_valid_json(self):
        entry = _file_entry()
        self.cm.write_entry("file", "/tmp/foo.py", entry)
        stored = self.cm.read_entry("file", "/tmp/foo.py")
        self.assertIsNotNone(stored)
        self.assertEqual(stored["summary"], "A Python file.")


class TestReadEntry(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cm = _make_manager(self.tmpdir)

    def test_read_after_write(self):
        entry = _file_entry(summary="Hello world")
        self.cm.write_entry("file", "/tmp/foo.py", entry)
        result = self.cm.read_entry("file", "/tmp/foo.py")
        self.assertEqual(result["summary"], "Hello world")

    def test_read_missing_returns_none(self):
        result = self.cm.read_entry("file", "/tmp/nonexistent.py")
        self.assertIsNone(result)

    def test_has_entry_true(self):
        self.cm.write_entry("file", "/tmp/foo.py", _file_entry())
        self.assertTrue(self.cm.has_entry("file", "/tmp/foo.py"))

    def test_has_entry_false(self):
        self.assertFalse(self.cm.has_entry("file", "/tmp/missing.py"))


class TestListEntries(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cm = _make_manager(self.tmpdir)

    def test_empty(self):
        self.assertEqual(self.cm.list_entries("file"), [])

    def test_lists_relative_paths(self):
        self.cm.write_entry("file", "/tmp/a.py", _file_entry(path="/tmp/a.py", relative_path="a.py"))
        self.cm.write_entry("file", "/tmp/b.py", _file_entry(path="/tmp/b.py", relative_path="b.py"))
        entries = self.cm.list_entries("file")
        self.assertIn("a.py", entries)
        self.assertIn("b.py", entries)

    def test_read_all_entries_returns_dicts(self):
        self.cm.write_entry("file", "/tmp/a.py", _file_entry(path="/tmp/a.py", relative_path="a.py"))
        result = self.cm.read_all_entries("file")
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], dict)


class TestLowConfidenceEntries(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cm = _make_manager(self.tmpdir)

    def test_returns_entries_below_threshold(self):
        self.cm.write_entry("file", "/tmp/a.py", _file_entry(path="/tmp/a.py", relative_path="a.py", confidence=0.4))
        self.cm.write_entry("file", "/tmp/b.py", _file_entry(path="/tmp/b.py", relative_path="b.py", confidence=0.9))
        result = self.cm.low_confidence_entries()
        paths = [e["relative_path"] for e in result]
        self.assertIn("a.py", paths)
        self.assertNotIn("b.py", paths)

    def test_excludes_entries_at_threshold(self):
        self.cm.write_entry("file", "/tmp/c.py", _file_entry(path="/tmp/c.py", relative_path="c.py", confidence=0.7))
        result = self.cm.low_confidence_entries()
        self.assertEqual(result, [])

    def test_includes_entries_missing_confidence(self):
        self.cm.write_entry("file", "/tmp/d.py", _file_entry(path="/tmp/d.py", relative_path="d.py"))
        result = self.cm.low_confidence_entries()
        paths = [e["relative_path"] for e in result]
        self.assertIn("d.py", paths)

    def test_includes_dir_entries(self):
        self.cm.write_entry("dir", "/tmp/mydir", _dir_entry(path="/tmp/mydir", relative_path="mydir", confidence=0.3))
        result = self.cm.low_confidence_entries()
        paths = [e["relative_path"] for e in result]
        self.assertIn("mydir", paths)

    def test_sorted_ascending_by_confidence(self):
        self.cm.write_entry("file", "/tmp/e.py", _file_entry(path="/tmp/e.py", relative_path="e.py", confidence=0.6))
        self.cm.write_entry("file", "/tmp/f.py", _file_entry(path="/tmp/f.py", relative_path="f.py", confidence=0.2))
        self.cm.write_entry("file", "/tmp/g.py", _file_entry(path="/tmp/g.py", relative_path="g.py", confidence=0.4))
        result = self.cm.low_confidence_entries()
        scores = [e["confidence"] for e in result]
        self.assertEqual(scores, sorted(scores))

    def test_custom_threshold(self):
        self.cm.write_entry("file", "/tmp/h.py", _file_entry(path="/tmp/h.py", relative_path="h.py", confidence=0.5))
        self.cm.write_entry("file", "/tmp/i.py", _file_entry(path="/tmp/i.py", relative_path="i.py", confidence=0.8))
        result = self.cm.low_confidence_entries(threshold=0.6)
        paths = [e["relative_path"] for e in result]
        self.assertIn("h.py", paths)
        self.assertNotIn("i.py", paths)

    def test_empty_cache_returns_empty_list(self):
        self.assertEqual(self.cm.low_confidence_entries(), [])


class TestGetInvestigationId(unittest.TestCase):
    def test_same_target_same_id(self):
        with tempfile.TemporaryDirectory() as d:
            from luminos_lib import cache as c
            orig_root, orig_path = c.CACHE_ROOT, c.INVESTIGATIONS_PATH
            c.CACHE_ROOT = d
            c.INVESTIGATIONS_PATH = os.path.join(d, "investigations.json")
            try:
                id1, _ = _get_investigation_id(d)
                # _get_investigation_id checks the cache dir exists before reusing
                os.makedirs(os.path.join(d, id1), exist_ok=True)
                id2, new = _get_investigation_id(d)
                self.assertEqual(id1, id2)
                self.assertFalse(new)
            finally:
                c.CACHE_ROOT = orig_root
                c.INVESTIGATIONS_PATH = orig_path

    def test_fresh_flag_creates_new_id(self):
        with tempfile.TemporaryDirectory() as d:
            from luminos_lib import cache as c
            orig_root = c.CACHE_ROOT
            orig_path = c.INVESTIGATIONS_PATH
            c.CACHE_ROOT = d
            c.INVESTIGATIONS_PATH = os.path.join(d, "investigations.json")
            try:
                os.makedirs(os.path.join(d, "someid"), exist_ok=True)
                id1, _ = _get_investigation_id(d)
                os.makedirs(os.path.join(d, id1), exist_ok=True)
                id2, new = _get_investigation_id(d, fresh=True)
                self.assertNotEqual(id1, id2)
                self.assertTrue(new)
            finally:
                c.CACHE_ROOT = orig_root
                c.INVESTIGATIONS_PATH = orig_path


if __name__ == "__main__":
    unittest.main()
