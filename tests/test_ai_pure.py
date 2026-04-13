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
    CONTEXT_BUDGET,
    _DEFAULT_TURNS,
    _DIR_TOOLS,
    _MAX_TURNS_CEILING,
    _PLANNING_TOOLS,
    _PROTECTED_DIR_TOOLS,
    _SHALLOW_TURNS,
    _SURVEY_CONFIDENCE_THRESHOLD,
    _TokenTracker,
    _apply_plan,
    _block_to_dict,
    _default_plan,
    _default_survey,
    _discover_directories,
    _filter_dir_tools,
    _flush_partial_dir_entry,
    _format_survey_block,
    _format_survey_signals,
    _get_child_summaries,
    _path_is_safe,
    _should_skip_dir,
    _synthesize_from_cache,
    _write_plan_evaluation,
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


# ---------------------------------------------------------------------------
# _TokenTracker (added by #70)
# ---------------------------------------------------------------------------

def _usage(input_tokens=0, output_tokens=0):
    """Build a fake Anthropic SDK usage object for the tracker tests."""
    return SimpleNamespace(
        input_tokens=input_tokens, output_tokens=output_tokens,
    )


class TestTokenTracker(unittest.TestCase):
    def test_initial_state_is_zero(self):
        t = _TokenTracker()
        self.assertEqual(t.total_input, 0)
        self.assertEqual(t.total_output, 0)
        self.assertEqual(t.loop_input, 0)
        self.assertEqual(t.loop_output, 0)
        self.assertEqual(t.last_input, 0)
        self.assertEqual(t.loop_total, 0)
        self.assertFalse(t.budget_exceeded())

    def test_record_updates_all_counters(self):
        t = _TokenTracker()
        t.record(_usage(input_tokens=1000, output_tokens=200))
        self.assertEqual(t.total_input, 1000)
        self.assertEqual(t.total_output, 200)
        self.assertEqual(t.loop_input, 1000)
        self.assertEqual(t.loop_output, 200)
        self.assertEqual(t.last_input, 1000)

    def test_loop_total_property(self):
        t = _TokenTracker()
        t.record(_usage(input_tokens=300, output_tokens=70))
        self.assertEqual(t.loop_total, 370)

    def test_record_with_missing_attrs_defaults_to_zero(self):
        t = _TokenTracker()
        t.record(SimpleNamespace())
        self.assertEqual(t.total_input, 0)
        self.assertEqual(t.total_output, 0)
        self.assertEqual(t.last_input, 0)

    def test_multiple_records_accumulate(self):
        t = _TokenTracker()
        t.record(_usage(input_tokens=500, output_tokens=100))
        t.record(_usage(input_tokens=700, output_tokens=200))
        self.assertEqual(t.total_input, 1200)
        self.assertEqual(t.total_output, 300)
        # last_input is the most recent call, NOT the cumulative sum.
        self.assertEqual(t.last_input, 700)

    def test_reset_loop_zeros_loop_counters_preserves_totals(self):
        t = _TokenTracker()
        t.record(_usage(input_tokens=500, output_tokens=100))
        t.record(_usage(input_tokens=300, output_tokens=50))
        t.reset_loop()
        # Loop counters cleared.
        self.assertEqual(t.loop_input, 0)
        self.assertEqual(t.loop_output, 0)
        self.assertEqual(t.last_input, 0)
        # Cumulative totals preserved.
        self.assertEqual(t.total_input, 800)
        self.assertEqual(t.total_output, 150)

    def test_grand_totals_accumulate_across_loops(self):
        t = _TokenTracker()
        t.record(_usage(input_tokens=500, output_tokens=100))
        t.reset_loop()
        t.record(_usage(input_tokens=400, output_tokens=80))
        t.reset_loop()
        t.record(_usage(input_tokens=200, output_tokens=40))
        self.assertEqual(t.total_input, 1100)
        self.assertEqual(t.total_output, 220)

    def test_budget_exceeded_uses_last_input_not_cumulative(self):
        # The load-bearing #44 fix: cumulative is meaningless because
        # each turn's input_tokens already includes prior history.
        t = _TokenTracker()
        # Record many small calls whose CUMULATIVE input would exceed
        # the budget but whose individual last_input stays small.
        for _ in range(10):
            t.record(_usage(input_tokens=CONTEXT_BUDGET // 5, output_tokens=0))
        self.assertGreater(t.total_input, CONTEXT_BUDGET)
        # last_input is just the most recent call — well under budget.
        self.assertEqual(t.last_input, CONTEXT_BUDGET // 5)
        self.assertFalse(t.budget_exceeded())

    def test_budget_exceeded_strict_greater_than(self):
        # The gate is `>`, not `>=`. last_input == CONTEXT_BUDGET
        # should NOT trip the budget.
        t = _TokenTracker()
        t.record(_usage(input_tokens=CONTEXT_BUDGET, output_tokens=0))
        self.assertFalse(t.budget_exceeded())

    def test_budget_exceeded_one_over_trips(self):
        t = _TokenTracker()
        t.record(_usage(input_tokens=CONTEXT_BUDGET + 1, output_tokens=0))
        self.assertTrue(t.budget_exceeded())

    def test_summary_returns_nonempty_string(self):
        t = _TokenTracker()
        t.record(_usage(input_tokens=1000, output_tokens=500))
        out = t.summary()
        self.assertIsInstance(out, str)
        self.assertIn("1,000", out)
        self.assertIn("500", out)
        self.assertIn("$", out)


# ---------------------------------------------------------------------------
# _synthesize_from_cache (added by #70)
# ---------------------------------------------------------------------------

class TestSynthesizeFromCache(unittest.TestCase):
    def setUp(self):
        self.target = tempfile.mkdtemp(prefix="luminos-test-target-")
        self.cache = _make_manager(self.target)

    def tearDown(self):
        shutil.rmtree(self.target, ignore_errors=True)

    def test_empty_cache_returns_incomplete_message(self):
        brief, detailed = _synthesize_from_cache(self.cache)
        self.assertIn("incomplete", brief)
        self.assertEqual(detailed, "")

    def test_single_dir_entry(self):
        self.cache.write_entry("dir", "/x/auth", {
            "path": "/x/auth",
            "relative_path": "auth",
            "child_count": 3,
            "summary": "Authentication module.",
            "dominant_category": "code",
            "cached_at": "2026-04-11T00:00:00+00:00",
        })
        brief, detailed = _synthesize_from_cache(self.cache)
        self.assertEqual(brief, "Authentication module.")
        self.assertIn("**auth/**", detailed)
        self.assertIn("Authentication module.", detailed)

    def test_multiple_dir_entries_brief_is_first(self):
        for rel, summary in [
            ("auth", "Auth code."),
            ("db", "Database layer."),
            ("api", "HTTP API."),
        ]:
            self.cache.write_entry("dir", f"/x/{rel}", {
                "path": f"/x/{rel}",
                "relative_path": rel,
                "child_count": 1,
                "summary": summary,
                "dominant_category": "code",
                "cached_at": "2026-04-11T00:00:00+00:00",
            })
        brief, detailed = _synthesize_from_cache(self.cache)
        # Brief is the first dir entry's summary.
        self.assertIn(brief, {"Auth code.", "Database layer.", "HTTP API."})
        # Detailed includes all three with markdown formatting.
        self.assertIn("Auth code.", detailed)
        self.assertIn("Database layer.", detailed)
        self.assertIn("HTTP API.", detailed)
        self.assertIn("**auth/**", detailed)
        self.assertIn("**db/**", detailed)
        self.assertIn("**api/**", detailed)

    def test_dir_entries_with_empty_summary_are_skipped(self):
        self.cache.write_entry("dir", "/x/empty", {
            "path": "/x/empty",
            "relative_path": "empty",
            "child_count": 0,
            "summary": "",
            "dominant_category": "unknown",
            "cached_at": "2026-04-11T00:00:00+00:00",
        })
        self.cache.write_entry("dir", "/x/real", {
            "path": "/x/real",
            "relative_path": "real",
            "child_count": 1,
            "summary": "Real content.",
            "dominant_category": "code",
            "cached_at": "2026-04-11T00:00:00+00:00",
        })
        brief, detailed = _synthesize_from_cache(self.cache)
        self.assertEqual(brief, "Real content.")
        self.assertNotIn("**empty/**", detailed)
        self.assertIn("**real/**", detailed)

    def test_file_entries_alone_do_not_satisfy(self):
        # _synthesize_from_cache reads dir entries only. File entries
        # alone should produce the "incomplete" fallback.
        self.cache.write_entry("file", "/x/foo.py", {
            "path": "/x/foo.py",
            "relative_path": "foo.py",
            "size_bytes": 10,
            "category": "code",
            "summary": "A file.",
            "cached_at": "2026-04-11T00:00:00+00:00",
        })
        brief, detailed = _synthesize_from_cache(self.cache)
        self.assertIn("incomplete", brief)
        self.assertEqual(detailed, "")


# ---------------------------------------------------------------------------
# _discover_directories (added by #70)
# ---------------------------------------------------------------------------

class TestDiscoverDirectories(unittest.TestCase):
    def setUp(self):
        self.target = tempfile.mkdtemp(prefix="luminos-test-target-")

    def tearDown(self):
        shutil.rmtree(self.target, ignore_errors=True)

    def _mkdirs(self, *rels):
        for rel in rels:
            os.makedirs(os.path.join(self.target, rel), exist_ok=True)

    def test_empty_target_returns_target_only(self):
        result = _discover_directories(self.target)
        self.assertEqual(len(result), 1)
        self.assertEqual(os.path.realpath(result[0]),
                         os.path.realpath(self.target))

    def test_single_subdir(self):
        self._mkdirs("sub")
        result = _discover_directories(self.target)
        self.assertEqual(len(result), 2)
        # Leaf-first: "sub" (deeper) comes before target.
        self.assertTrue(result[0].endswith("sub"))

    def test_leaves_first_ordering(self):
        self._mkdirs("a/b/c", "a/d", "a/b/e")
        result = _discover_directories(self.target)
        # Compute depth (sep count) of each result.
        depths = [d.count(os.sep) for d in result]
        # Each successive entry should have depth <= the previous one.
        for i in range(len(depths) - 1):
            self.assertGreaterEqual(
                depths[i], depths[i + 1],
                f"Not leaves-first: {result}",
            )
        # Verify all expected dirs are present.
        rels = [os.path.relpath(d, self.target) for d in result]
        for expected in ["a/b/c", "a/b/e", "a/d", "a/b", "a", "."]:
            self.assertIn(expected, rels, f"missing {expected} from {rels}")

    def test_skip_dirs_excluded(self):
        self._mkdirs(".git", "__pycache__", "node_modules", "src")
        result = _discover_directories(self.target)
        rels = [os.path.relpath(d, self.target) for d in result]
        self.assertIn("src", rels)
        self.assertNotIn(".git", rels)
        self.assertNotIn("__pycache__", rels)
        self.assertNotIn("node_modules", rels)

    def test_egg_info_glob_excluded(self):
        self._mkdirs("luminos.egg-info", "src")
        result = _discover_directories(self.target)
        rels = [os.path.relpath(d, self.target) for d in result]
        self.assertNotIn("luminos.egg-info", rels)
        self.assertIn("src", rels)

    def test_custom_exclude_honored(self):
        self._mkdirs("vendor", "src")
        result = _discover_directories(self.target, exclude=["vendor"])
        rels = [os.path.relpath(d, self.target) for d in result]
        self.assertNotIn("vendor", rels)
        self.assertIn("src", rels)

    def test_hidden_dirs_excluded_by_default(self):
        self._mkdirs(".hidden_thing", "visible")
        result = _discover_directories(self.target)
        rels = [os.path.relpath(d, self.target) for d in result]
        self.assertNotIn(".hidden_thing", rels)
        self.assertIn("visible", rels)

    def test_show_hidden_includes_dotdirs(self):
        self._mkdirs(".hidden_thing", "visible")
        result = _discover_directories(self.target, show_hidden=True)
        rels = [os.path.relpath(d, self.target) for d in result]
        self.assertIn(".hidden_thing", rels)
        self.assertIn("visible", rels)

    def test_show_hidden_does_not_override_skip_list(self):
        # .git is in _SKIP_DIRS so even with show_hidden=True it stays out.
        self._mkdirs(".git")
        result = _discover_directories(self.target, show_hidden=True)
        rels = [os.path.relpath(d, self.target) for d in result]
        self.assertNotIn(".git", rels)


# ---------------------------------------------------------------------------
# _default_plan
# ---------------------------------------------------------------------------

class TestDefaultPlan(unittest.TestCase):
    def test_returns_empty_plan(self):
        plan = _default_plan()
        self.assertEqual(plan["priority_dirs"], [])
        self.assertEqual(plan["shallow_dirs"], [])
        self.assertEqual(plan["skip_dirs"], [])
        self.assertEqual(plan["investigation_order"], "leaf-first")
        self.assertEqual(plan["notes"], "")

    def test_returns_fresh_dict_each_call(self):
        a = _default_plan()
        b = _default_plan()
        self.assertIsNot(a, b)
        a["notes"] = "mutated"
        self.assertEqual(b["notes"], "")


# ---------------------------------------------------------------------------
# _apply_plan
# ---------------------------------------------------------------------------

class TestApplyPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.target = self.tmp
        # Create directories: a/x, a/y, b, c (leaves first in sorted order)
        for p in ["a/x", "a/y", "b", "c"]:
            os.makedirs(os.path.join(self.tmp, p), exist_ok=True)
        # all_dirs sorted leaf-first (deepest first, then alphabetical)
        self.all_dirs = [
            os.path.join(self.tmp, "a", "x"),
            os.path.join(self.tmp, "a", "y"),
            os.path.join(self.tmp, "a"),
            os.path.join(self.tmp, "b"),
            os.path.join(self.tmp, "c"),
            self.tmp,
        ]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_none_plan_returns_original_order(self):
        ordered, turn_map = _apply_plan(
            self.all_dirs, list(self.all_dirs), None, self.target,
        )
        self.assertEqual(ordered, self.all_dirs)
        self.assertEqual(turn_map, {})

    def test_default_plan_returns_original_order(self):
        plan = _default_plan()
        ordered, turn_map = _apply_plan(
            self.all_dirs, list(self.all_dirs), plan, self.target,
        )
        self.assertEqual(ordered, self.all_dirs)
        self.assertEqual(turn_map, {})

    def test_skip_dirs_removed(self):
        plan = _default_plan()
        plan["skip_dirs"] = [{"path": "b", "reason": "vendored"}]
        ordered, turn_map = _apply_plan(
            self.all_dirs, list(self.all_dirs), plan, self.target,
        )
        b_path = os.path.join(self.tmp, "b")
        self.assertNotIn(b_path, ordered)

    def test_priority_dirs_get_custom_turns(self):
        plan = _default_plan()
        plan["priority_dirs"] = [
            {"path": "a", "reason": "core", "suggested_turns": 18},
        ]
        ordered, turn_map = _apply_plan(
            self.all_dirs, list(self.all_dirs), plan, self.target,
        )
        a_path = os.path.join(self.tmp, "a")
        self.assertEqual(turn_map[a_path], 18)

    def test_priority_turns_capped_at_ceiling(self):
        plan = _default_plan()
        plan["priority_dirs"] = [
            {"path": "a", "reason": "core", "suggested_turns": 50},
        ]
        _, turn_map = _apply_plan(
            self.all_dirs, list(self.all_dirs), plan, self.target,
        )
        a_path = os.path.join(self.tmp, "a")
        self.assertEqual(turn_map[a_path], _MAX_TURNS_CEILING)

    def test_shallow_dirs_get_shallow_turns(self):
        plan = _default_plan()
        plan["shallow_dirs"] = [{"path": "c", "reason": "docs only"}]
        _, turn_map = _apply_plan(
            self.all_dirs, list(self.all_dirs), plan, self.target,
        )
        c_path = os.path.join(self.tmp, "c")
        self.assertEqual(turn_map[c_path], _SHALLOW_TURNS)

    def test_priority_first_reorders_bands(self):
        plan = _default_plan()
        plan["investigation_order"] = "priority-first"
        plan["priority_dirs"] = [
            {"path": "c", "reason": "entry point", "suggested_turns": 15},
        ]
        plan["shallow_dirs"] = [{"path": "b", "reason": "tests"}]
        ordered, _ = _apply_plan(
            self.all_dirs, list(self.all_dirs), plan, self.target,
        )
        c_path = os.path.join(self.tmp, "c")
        b_path = os.path.join(self.tmp, "b")
        # Priority dirs come before shallow dirs.
        self.assertLess(ordered.index(c_path), ordered.index(b_path))

    def test_leaf_first_preserved_within_priority_band(self):
        plan = _default_plan()
        plan["investigation_order"] = "priority-first"
        plan["priority_dirs"] = [
            {"path": os.path.join("a", "x"), "reason": "deep",
             "suggested_turns": 15},
            {"path": "a", "reason": "parent", "suggested_turns": 15},
        ]
        ordered, _ = _apply_plan(
            self.all_dirs, list(self.all_dirs), plan, self.target,
        )
        ax_path = os.path.join(self.tmp, "a", "x")
        a_path = os.path.join(self.tmp, "a")
        # a/x (leaf) comes before a (parent), preserving leaf-first.
        self.assertLess(ordered.index(ax_path), ordered.index(a_path))

    def test_unknown_paths_in_plan_ignored(self):
        plan = _default_plan()
        plan["skip_dirs"] = [{"path": "nonexistent", "reason": "gone"}]
        plan["priority_dirs"] = [
            {"path": "also_missing", "reason": "?", "suggested_turns": 20},
        ]
        ordered, turn_map = _apply_plan(
            self.all_dirs, list(self.all_dirs), plan, self.target,
        )
        # All original dirs still present, no crash.
        self.assertEqual(len(ordered), len(self.all_dirs))
        self.assertEqual(turn_map, {})

    def test_to_investigate_subset_respected(self):
        """Only dirs in to_investigate appear in output, even if plan mentions all."""
        plan = _default_plan()
        subset = self.all_dirs[:3]
        ordered, _ = _apply_plan(
            self.all_dirs, subset, plan, self.target,
        )
        self.assertEqual(len(ordered), len(subset))

    def test_target_root_matched_by_basename(self):
        """Plan can reference the target root by its basename, not just '.' (#76)."""
        plan = _default_plan()
        basename = os.path.basename(self.tmp)
        plan["priority_dirs"] = [
            {"path": basename, "reason": "root is important",
             "suggested_turns": 18},
        ]
        _, turn_map = _apply_plan(
            self.all_dirs, list(self.all_dirs), plan, self.target,
        )
        self.assertEqual(turn_map[self.tmp], 18)

    def test_target_root_matched_by_dot(self):
        """Plan can also reference the target root as '.'."""
        plan = _default_plan()
        plan["priority_dirs"] = [
            {"path": ".", "reason": "root", "suggested_turns": 16},
        ]
        _, turn_map = _apply_plan(
            self.all_dirs, list(self.all_dirs), plan, self.target,
        )
        self.assertEqual(turn_map[self.tmp], 16)


# ---------------------------------------------------------------------------
# _get_child_summaries (updated placeholder behavior)
# ---------------------------------------------------------------------------

class TestGetChildSummaries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache = _make_manager(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_leaf_directory_no_subdirs(self):
        leaf = os.path.join(self.tmp, "leaf")
        os.makedirs(leaf)
        result = _get_child_summaries(leaf, self.cache)
        self.assertIn("leaf directory", result)
        self.assertNotIn("not been investigated", result)

    def test_parent_with_uninvestigated_children(self):
        parent = os.path.join(self.tmp, "parent")
        child = os.path.join(parent, "child")
        os.makedirs(child)
        result = _get_child_summaries(parent, self.cache)
        self.assertIn("not been investigated", result)
        self.assertNotIn("leaf directory", result)

    def test_parent_with_cached_children(self):
        parent = os.path.join(self.tmp, "parent")
        child = os.path.join(parent, "child")
        os.makedirs(child)
        self.cache.write_entry("dir", child, {
            "path": child,
            "relative_path": "parent/child",
            "child_count": 0,
            "summary": "A child directory with stuff.",
            "dominant_category": "source",
            "notable_files": [],
            "cached_at": "2026-01-01T00:00:00+00:00",
        })
        result = _get_child_summaries(parent, self.cache)
        self.assertIn("parent/child/", result)
        self.assertIn("A child directory with stuff.", result)

    def test_hidden_dirs_ignored(self):
        parent = os.path.join(self.tmp, "parent")
        os.makedirs(os.path.join(parent, ".hidden"))
        result = _get_child_summaries(parent, self.cache)
        # .hidden is ignored, so this looks like a leaf.
        self.assertIn("leaf directory", result)


# ---------------------------------------------------------------------------
# _TokenTracker._loop_turns
# ---------------------------------------------------------------------------

class TestTokenTrackerLoopTurns(unittest.TestCase):
    def test_loop_turns_increments_on_record(self):
        t = _TokenTracker()
        self.assertEqual(t._loop_turns, 0)
        t.record(SimpleNamespace(input_tokens=100, output_tokens=50))
        self.assertEqual(t._loop_turns, 1)
        t.record(SimpleNamespace(input_tokens=200, output_tokens=75))
        self.assertEqual(t._loop_turns, 2)

    def test_loop_turns_reset(self):
        t = _TokenTracker()
        t.record(SimpleNamespace(input_tokens=100, output_tokens=50))
        t.record(SimpleNamespace(input_tokens=200, output_tokens=75))
        self.assertEqual(t._loop_turns, 2)
        t.reset_loop()
        self.assertEqual(t._loop_turns, 0)

    def test_loop_turns_independent_of_totals(self):
        t = _TokenTracker()
        t.record(SimpleNamespace(input_tokens=100, output_tokens=50))
        t.reset_loop()
        t.record(SimpleNamespace(input_tokens=300, output_tokens=100))
        self.assertEqual(t._loop_turns, 1)
        self.assertEqual(t.total_input, 400)


# ---------------------------------------------------------------------------
# _write_plan_evaluation
# ---------------------------------------------------------------------------

class TestWritePlanEvaluation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache = _make_manager(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_evaluation_file(self):
        plan = {
            "priority_dirs": [
                {"path": "src", "reason": "core", "suggested_turns": 18},
            ],
            "shallow_dirs": [
                {"path": "docs", "reason": "docs"},
            ],
            "skip_dirs": [],
            "investigation_order": "leaf-first",
            "notes": "",
        }
        utilization = [
            {"dir": "src", "turns_allocated": 18, "turns_used": 12,
             "completeness": 0.85},
            {"dir": "docs", "turns_allocated": 5, "turns_used": 3,
             "completeness": 0.7},
        ]
        _write_plan_evaluation(self.cache, plan, utilization)

        import json
        eval_path = os.path.join(self.cache.root, "plan_evaluation.json")
        self.assertTrue(os.path.exists(eval_path))
        with open(eval_path) as f:
            data = json.load(f)
        self.assertEqual(data["total_dirs_investigated"], 2)
        self.assertEqual(data["total_turns_allocated"], 23)
        self.assertEqual(data["total_turns_used"], 15)
        self.assertEqual(len(data["per_directory"]), 2)
        # Check that tier classification came through.
        src_entry = [d for d in data["per_directory"] if d["dir"] == "src"][0]
        self.assertEqual(src_entry["planned_tier"], "priority")
        self.assertEqual(src_entry["completeness"], 0.85)

    def test_handles_none_plan(self):
        utilization = [
            {"dir": "a", "turns_allocated": 10, "turns_used": 8},
        ]
        _write_plan_evaluation(self.cache, None, utilization)
        eval_path = os.path.join(self.cache.root, "plan_evaluation.json")
        self.assertTrue(os.path.exists(eval_path))

    def test_handles_empty_utilization(self):
        plan = _default_plan()
        _write_plan_evaluation(self.cache, plan, [])
        import json
        eval_path = os.path.join(self.cache.root, "plan_evaluation.json")
        with open(eval_path) as f:
            data = json.load(f)
        self.assertEqual(data["total_dirs_investigated"], 0)
        self.assertEqual(data["overall_utilization"], 0)

    def test_zero_allocated_turns_no_division_error(self):
        plan = _default_plan()
        utilization = [
            {"dir": "x", "turns_allocated": 0, "turns_used": 0},
        ]
        _write_plan_evaluation(self.cache, plan, utilization)
        import json
        eval_path = os.path.join(self.cache.root, "plan_evaluation.json")
        with open(eval_path) as f:
            data = json.load(f)
        self.assertEqual(data["per_directory"][0]["utilization"], 0)


# ---------------------------------------------------------------------------
# Planning tool registry
# ---------------------------------------------------------------------------

class TestPlanningToolRegistry(unittest.TestCase):
    def test_submit_plan_registered(self):
        names = [t["name"] for t in _PLANNING_TOOLS]
        self.assertIn("submit_plan", names)

    def test_submit_plan_has_required_fields(self):
        tool = [t for t in _PLANNING_TOOLS if t["name"] == "submit_plan"][0]
        required = tool["input_schema"]["required"]
        self.assertIn("priority_dirs", required)
        self.assertIn("shallow_dirs", required)
        self.assertIn("skip_dirs", required)
        self.assertIn("investigation_order", required)
        self.assertIn("notes", required)

    def test_submit_plan_order_enum(self):
        tool = [t for t in _PLANNING_TOOLS if t["name"] == "submit_plan"][0]
        order_prop = tool["input_schema"]["properties"]["investigation_order"]
        self.assertEqual(order_prop["enum"], ["leaf-first", "priority-first"])


if __name__ == "__main__":
    unittest.main()
