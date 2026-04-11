"""Tests for pure helpers in luminos_lib/ai.py.

ai.py is exempt from end-to-end testing because the dir loop and synthesis
pass require a live Anthropic API. But several helpers in the module are
pure functions with no API dependency, and they are the kind of thing
that breaks silently. This file covers them.
"""

import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace

from luminos_lib.ai import (
    _DIR_TOOLS,
    _PROTECTED_DIR_TOOLS,
    _SURVEY_CONFIDENCE_THRESHOLD,
    _block_to_dict,
    _default_survey,
    _filter_dir_tools,
    _flush_partial_dir_entry,
    _format_survey_block,
    _format_survey_signals,
    _path_is_safe,
    _should_skip_dir,
)
from luminos_lib.cache import _CacheManager


def _make_manager(root):
    """Build a _CacheManager rooted in *root* without touching CACHE_ROOT.

    Mirrors the pattern used in tests/test_cache.py so the test cache
    lives entirely in the supplied tempdir.
    """
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


# ---------------------------------------------------------------------------
# _should_skip_dir
# ---------------------------------------------------------------------------

class TestShouldSkipDir(unittest.TestCase):
    def test_exact_match_dotdir(self):
        self.assertTrue(_should_skip_dir(".git"))

    def test_exact_match_pycache(self):
        self.assertTrue(_should_skip_dir("__pycache__"))

    def test_exact_match_node_modules(self):
        self.assertTrue(_should_skip_dir("node_modules"))

    def test_glob_match_egg_info(self):
        self.assertTrue(_should_skip_dir("luminos.egg-info"))
        self.assertTrue(_should_skip_dir("foo.egg-info"))

    def test_no_match_normal_dir(self):
        self.assertFalse(_should_skip_dir("src"))
        self.assertFalse(_should_skip_dir("tests"))

    def test_no_match_egg_info_without_dot(self):
        self.assertFalse(_should_skip_dir("egg-info"))

    def test_no_match_empty_string(self):
        self.assertFalse(_should_skip_dir(""))


# ---------------------------------------------------------------------------
# _path_is_safe
# ---------------------------------------------------------------------------

class TestPathIsSafe(unittest.TestCase):
    def setUp(self):
        self.target = tempfile.mkdtemp(prefix="luminos-test-")

    def tearDown(self):
        shutil.rmtree(self.target, ignore_errors=True)

    def test_path_inside(self):
        inside = os.path.join(self.target, "file.txt")
        self.assertTrue(_path_is_safe(inside, self.target))

    def test_path_inside_nested(self):
        inside = os.path.join(self.target, "a", "b", "c.txt")
        self.assertTrue(_path_is_safe(inside, self.target))

    def test_path_equals_target(self):
        self.assertTrue(_path_is_safe(self.target, self.target))

    def test_path_outside(self):
        self.assertFalse(_path_is_safe("/etc/passwd", self.target))

    def test_path_traversal_escapes(self):
        traversal = os.path.join(self.target, "..", "..", "etc", "passwd")
        self.assertFalse(_path_is_safe(traversal, self.target))

    def test_sibling_with_target_prefix_rejected(self):
        # /tmp/foo and /tmp/foo_sibling: prefix match without separator
        # must NOT be considered "inside".
        sibling = self.target + "_sibling"
        self.assertFalse(_path_is_safe(sibling, self.target))


# ---------------------------------------------------------------------------
# _default_survey
# ---------------------------------------------------------------------------

class TestDefaultSurvey(unittest.TestCase):
    def test_required_fields_present(self):
        s = _default_survey()
        for key in ("description", "approach", "relevant_tools",
                    "skip_tools", "domain_notes", "confidence"):
            self.assertIn(key, s)

    def test_empty_skip_and_relevant(self):
        s = _default_survey()
        self.assertEqual(s["relevant_tools"], [])
        self.assertEqual(s["skip_tools"], [])

    def test_confidence_zero(self):
        # Critical: zero confidence ensures _filter_dir_tools never enforces
        # skip_tools based on the synthetic survey.
        self.assertEqual(_default_survey()["confidence"], 0.0)

    def test_default_survey_passes_through_filter_unchanged(self):
        result = _filter_dir_tools(_default_survey())
        self.assertEqual(len(result), len(_DIR_TOOLS))


# ---------------------------------------------------------------------------
# _format_survey_block
# ---------------------------------------------------------------------------

class TestFormatSurveyBlock(unittest.TestCase):
    def test_none(self):
        self.assertEqual(_format_survey_block(None), "(no survey available)")

    def test_empty_dict(self):
        self.assertEqual(_format_survey_block({}), "(no survey available)")

    def test_minimal_survey(self):
        out = _format_survey_block({"description": "X", "approach": "Y"})
        self.assertIn("Description: X", out)
        self.assertIn("Approach: Y", out)
        self.assertNotIn("Relevant tools", out)
        self.assertNotIn("Skip tools", out)
        self.assertNotIn("Domain notes", out)

    def test_with_relevant_tools(self):
        out = _format_survey_block({
            "description": "D",
            "approach": "A",
            "relevant_tools": ["read_file", "parse_structure"],
        })
        self.assertIn("Relevant tools (lean on these)", out)
        self.assertIn("read_file", out)
        self.assertIn("parse_structure", out)

    def test_with_skip_tools(self):
        out = _format_survey_block({
            "description": "D",
            "approach": "A",
            "skip_tools": ["run_command"],
        })
        self.assertIn("Skip tools", out)
        self.assertIn("run_command", out)

    def test_with_domain_notes(self):
        out = _format_survey_block({
            "description": "D",
            "approach": "A",
            "domain_notes": "this is special",
        })
        self.assertIn("Domain notes: this is special", out)

    def test_empty_lists_omitted(self):
        out = _format_survey_block({
            "description": "D",
            "approach": "A",
            "relevant_tools": [],
            "skip_tools": [],
            "domain_notes": "",
        })
        self.assertNotIn("Relevant tools", out)
        self.assertNotIn("Skip tools", out)
        self.assertNotIn("Domain notes", out)


# ---------------------------------------------------------------------------
# _filter_dir_tools
# ---------------------------------------------------------------------------

class TestFilterDirTools(unittest.TestCase):
    def test_none_survey_returns_full(self):
        result = _filter_dir_tools(None)
        self.assertEqual(len(result), len(_DIR_TOOLS))

    def test_empty_survey_returns_full(self):
        result = _filter_dir_tools({})
        self.assertEqual(len(result), len(_DIR_TOOLS))

    def test_low_confidence_returns_full_even_with_skip(self):
        survey = {
            "confidence": _SURVEY_CONFIDENCE_THRESHOLD - 0.1,
            "skip_tools": ["read_file"],
        }
        result = _filter_dir_tools(survey)
        self.assertEqual(len(result), len(_DIR_TOOLS))

    def test_high_confidence_filters_skip_tools(self):
        survey = {"confidence": 0.9, "skip_tools": ["run_command"]}
        result = _filter_dir_tools(survey)
        names = [t["name"] for t in result]
        self.assertNotIn("run_command", names)
        self.assertEqual(len(result), len(_DIR_TOOLS) - 1)

    def test_protected_tools_never_removed(self):
        survey = {
            "confidence": 0.95,
            "skip_tools": list(_PROTECTED_DIR_TOOLS),
        }
        result = _filter_dir_tools(survey)
        names = [t["name"] for t in result]
        for protected in _PROTECTED_DIR_TOOLS:
            self.assertIn(protected, names)

    def test_unknown_skip_tool_silently_ignored(self):
        survey = {"confidence": 0.9, "skip_tools": ["nonexistent_tool"]}
        result = _filter_dir_tools(survey)
        self.assertEqual(len(result), len(_DIR_TOOLS))

    def test_garbage_confidence_treated_as_zero(self):
        survey = {"confidence": "not a number", "skip_tools": ["read_file"]}
        result = _filter_dir_tools(survey)
        self.assertEqual(len(result), len(_DIR_TOOLS))

    def test_none_confidence_treated_as_zero(self):
        survey = {"confidence": None, "skip_tools": ["read_file"]}
        result = _filter_dir_tools(survey)
        self.assertEqual(len(result), len(_DIR_TOOLS))

    def test_threshold_boundary_inclusive(self):
        # confidence == threshold should pass the gate (not "<").
        survey = {
            "confidence": _SURVEY_CONFIDENCE_THRESHOLD,
            "skip_tools": ["run_command"],
        }
        result = _filter_dir_tools(survey)
        names = [t["name"] for t in result]
        self.assertNotIn("run_command", names)


# ---------------------------------------------------------------------------
# _format_survey_signals
# ---------------------------------------------------------------------------

class TestFormatSurveySignals(unittest.TestCase):
    def test_none(self):
        self.assertEqual(_format_survey_signals(None), "(no files classified)")

    def test_empty_dict(self):
        self.assertEqual(_format_survey_signals({}), "(no files classified)")

    def test_zero_total_files(self):
        self.assertEqual(
            _format_survey_signals({"total_files": 0}),
            "(no files classified)",
        )

    def test_full_signals(self):
        signals = {
            "total_files": 42,
            "extension_histogram": {".py": 30, ".md": 5},
            "file_descriptions": {"Python script": 30},
            "filename_samples": ["main.py", "README.md"],
        }
        out = _format_survey_signals(signals)
        self.assertIn("Total files: 42", out)
        self.assertIn(".py: 30", out)
        self.assertIn("Python script: 30", out)
        self.assertIn("main.py", out)
        self.assertIn("README.md", out)

    def test_only_extensions(self):
        signals = {
            "total_files": 5,
            "extension_histogram": {".py": 5},
        }
        out = _format_survey_signals(signals)
        self.assertIn("Total files: 5", out)
        self.assertIn(".py: 5", out)
        self.assertNotIn("file --brief", out)
        self.assertNotIn("Filename samples", out)


# ---------------------------------------------------------------------------
# _block_to_dict
# ---------------------------------------------------------------------------

class TestBlockToDict(unittest.TestCase):
    def test_text_block(self):
        block = SimpleNamespace(type="text", text="hello world")
        self.assertEqual(
            _block_to_dict(block),
            {"type": "text", "text": "hello world"},
        )

    def test_tool_use_block(self):
        block = SimpleNamespace(
            type="tool_use",
            id="t_1",
            name="read_file",
            input={"path": "x.py"},
        )
        self.assertEqual(
            _block_to_dict(block),
            {
                "type": "tool_use",
                "id": "t_1",
                "name": "read_file",
                "input": {"path": "x.py"},
            },
        )

    def test_unknown_block_type(self):
        block = SimpleNamespace(type="thinking")
        self.assertEqual(_block_to_dict(block), {"type": "thinking"})


# ---------------------------------------------------------------------------
# _flush_partial_dir_entry (added by #57)
# ---------------------------------------------------------------------------

class TestFlushPartialDirEntry(unittest.TestCase):
    def setUp(self):
        self.target = tempfile.mkdtemp(prefix="luminos-test-target-")
        self.dir_path = os.path.join(self.target, "subdir")
        os.makedirs(self.dir_path)
        self.cache = _make_manager(self.target)

    def tearDown(self):
        shutil.rmtree(self.target, ignore_errors=True)

    def test_idempotent_when_dir_entry_already_exists(self):
        self.cache.write_entry("dir", self.dir_path, {
            "path": self.dir_path,
            "relative_path": "subdir",
            "child_count": 0,
            "summary": "already cached",
            "dominant_category": "code",
            "cached_at": "2026-04-11T00:00:00+00:00",
        })
        result = _flush_partial_dir_entry(
            self.dir_path, self.target, self.cache,
        )
        self.assertEqual(result, "")
        # The existing entry must be untouched (no partial flag).
        entry = self.cache.read_entry("dir", self.dir_path)
        self.assertNotIn("partial", entry)
        self.assertEqual(entry["summary"], "already cached")

    def test_no_file_entries_writes_empty_stub(self):
        result = _flush_partial_dir_entry(
            self.dir_path, self.target, self.cache,
        )
        self.assertEqual(result, "")
        entry = self.cache.read_entry("dir", self.dir_path)
        self.assertIsNotNone(entry)
        self.assertTrue(entry["partial"])
        self.assertIn("before files processed", entry["partial_reason"])
        self.assertEqual(entry["dominant_category"], "unknown")

    def test_with_file_entries_synthesizes_summary(self):
        file_in_dir = os.path.join(self.dir_path, "thing.py")
        with open(file_in_dir, "w") as f:
            f.write("print('x')")
        self.cache.write_entry("file", file_in_dir, {
            "path": file_in_dir,
            "relative_path": "subdir/thing.py",
            "size_bytes": 10,
            "category": "code",
            "summary": "prints x",
            "cached_at": "2026-04-11T00:00:00+00:00",
        })
        result = _flush_partial_dir_entry(
            self.dir_path, self.target, self.cache,
        )
        self.assertIn("prints x", result)
        entry = self.cache.read_entry("dir", self.dir_path)
        self.assertTrue(entry["partial"])
        self.assertEqual(entry["partial_reason"], "context budget reached")
        self.assertIn("prints x", entry["summary"])

    def test_notable_files_collected(self):
        file_in_dir = os.path.join(self.dir_path, "important.py")
        with open(file_in_dir, "w") as f:
            f.write("x = 1")
        self.cache.write_entry("file", file_in_dir, {
            "path": file_in_dir,
            "relative_path": "subdir/important.py",
            "size_bytes": 5,
            "category": "code",
            "summary": "important thing",
            "notable": True,
            "cached_at": "2026-04-11T00:00:00+00:00",
        })
        _flush_partial_dir_entry(self.dir_path, self.target, self.cache)
        entry = self.cache.read_entry("dir", self.dir_path)
        self.assertIn("subdir/important.py", entry["notable_files"])


if __name__ == "__main__":
    unittest.main()
