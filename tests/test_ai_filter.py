"""Tests for the pure helpers in ai.py that don't require a live API."""

import unittest
from unittest.mock import MagicMock
import sys


def _import_ai():
    # Stub heavy/optional deps so ai.py imports cleanly in unit tests.
    for mod in ("anthropic", "magic"):
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()
    if "luminos_lib.ast_parser" not in sys.modules:
        stub = MagicMock()
        stub.parse_structure = MagicMock()
        sys.modules["luminos_lib.ast_parser"] = stub
    from luminos_lib import ai
    return ai


ai = _import_ai()


class FilterDirToolsTests(unittest.TestCase):
    def setUp(self):
        self.all_names = {t["name"] for t in ai._DIR_TOOLS}

    def _names(self, tools):
        return {t["name"] for t in tools}

    def test_none_survey_returns_full_list(self):
        self.assertEqual(self._names(ai._filter_dir_tools(None)), self.all_names)

    def test_low_confidence_returns_full_list(self):
        survey = {"confidence": 0.3, "skip_tools": ["run_command"]}
        self.assertEqual(self._names(ai._filter_dir_tools(survey)), self.all_names)

    def test_high_confidence_drops_skip_tools(self):
        survey = {"confidence": 0.9, "skip_tools": ["run_command"]}
        result = self._names(ai._filter_dir_tools(survey))
        self.assertNotIn("run_command", result)
        self.assertEqual(result, self.all_names - {"run_command"})

    def test_threshold_boundary_inclusive(self):
        survey = {"confidence": 0.5, "skip_tools": ["run_command"]}
        result = self._names(ai._filter_dir_tools(survey))
        self.assertNotIn("run_command", result)

    def test_protected_tool_never_dropped(self):
        survey = {"confidence": 1.0, "skip_tools": ["submit_report", "run_command"]}
        result = self._names(ai._filter_dir_tools(survey))
        self.assertIn("submit_report", result)
        self.assertNotIn("run_command", result)

    def test_unknown_tool_in_skip_is_ignored(self):
        survey = {"confidence": 0.9, "skip_tools": ["nonexistent_tool"]}
        self.assertEqual(self._names(ai._filter_dir_tools(survey)), self.all_names)

    def test_empty_skip_tools_returns_full_list(self):
        survey = {"confidence": 0.9, "skip_tools": []}
        self.assertEqual(self._names(ai._filter_dir_tools(survey)), self.all_names)

    def test_missing_confidence_treated_as_zero(self):
        survey = {"skip_tools": ["run_command"]}
        self.assertEqual(self._names(ai._filter_dir_tools(survey)), self.all_names)

    def test_garbage_confidence_treated_as_zero(self):
        survey = {"confidence": "not a number", "skip_tools": ["run_command"]}
        self.assertEqual(self._names(ai._filter_dir_tools(survey)), self.all_names)

    def test_multiple_skip_tools(self):
        survey = {
            "confidence": 0.9,
            "skip_tools": ["run_command", "parse_structure"],
        }
        result = self._names(ai._filter_dir_tools(survey))
        self.assertNotIn("run_command", result)
        self.assertNotIn("parse_structure", result)


class FormatSurveyBlockTests(unittest.TestCase):
    def test_none_returns_placeholder(self):
        self.assertIn("no survey", ai._format_survey_block(None).lower())

    def test_includes_description_and_approach(self):
        block = ai._format_survey_block({
            "description": "A Python lib", "approach": "read modules",
            "confidence": 0.9,
        })
        self.assertIn("A Python lib", block)
        self.assertIn("read modules", block)

    def test_includes_skip_tools_when_present(self):
        block = ai._format_survey_block({
            "description": "x", "approach": "y",
            "skip_tools": ["run_command"], "confidence": 0.9,
        })
        self.assertIn("run_command", block)

    def test_omits_empty_optional_fields(self):
        block = ai._format_survey_block({
            "description": "x", "approach": "y",
            "domain_notes": "", "relevant_tools": [], "skip_tools": [],
            "confidence": 0.9,
        })
        self.assertNotIn("Domain notes:", block)
        self.assertNotIn("Relevant tools", block)
        self.assertNotIn("Skip tools", block)


class TokenTrackerTests(unittest.TestCase):
    def _usage(self, inp, out):
        u = MagicMock()
        u.input_tokens = inp
        u.output_tokens = out
        return u

    def test_record_updates_cumulative_and_last(self):
        t = ai._TokenTracker()
        t.record(self._usage(100, 20))
        t.record(self._usage(200, 30))
        self.assertEqual(t.total_input, 300)
        self.assertEqual(t.total_output, 50)
        self.assertEqual(t.loop_input, 300)
        self.assertEqual(t.loop_output, 50)
        self.assertEqual(t.last_input, 200)  # last call only

    def test_budget_uses_last_input_not_sum(self):
        t = ai._TokenTracker()
        # Many small calls whose sum exceeds the budget but whose
        # last input is well under the budget should NOT trip.
        for _ in range(20):
            t.record(self._usage(10_000, 100))
        self.assertGreater(t.loop_input, ai.CONTEXT_BUDGET)
        self.assertLess(t.last_input, ai.CONTEXT_BUDGET)
        self.assertFalse(t.budget_exceeded())

    def test_budget_trips_when_last_input_over_threshold(self):
        t = ai._TokenTracker()
        t.record(self._usage(ai.CONTEXT_BUDGET + 1, 100))
        self.assertTrue(t.budget_exceeded())

    def test_reset_loop_clears_loop_and_last(self):
        t = ai._TokenTracker()
        t.record(self._usage(500, 50))
        t.reset_loop()
        self.assertEqual(t.loop_input, 0)
        self.assertEqual(t.loop_output, 0)
        self.assertEqual(t.last_input, 0)
        # Cumulative totals are NOT reset
        self.assertEqual(t.total_input, 500)
        self.assertEqual(t.total_output, 50)

    def test_loop_total_property_still_works(self):
        t = ai._TokenTracker()
        t.record(self._usage(100, 25))
        t.record(self._usage(200, 50))
        self.assertEqual(t.loop_total, 375)

    def test_max_context_is_sonnet_real_window(self):
        self.assertEqual(ai.MAX_CONTEXT, 200_000)


class DefaultSurveyTests(unittest.TestCase):
    def test_has_all_required_keys(self):
        survey = ai._default_survey()
        for key in ("description", "approach", "relevant_tools",
                    "skip_tools", "domain_notes", "confidence"):
            self.assertIn(key, survey)

    def test_confidence_below_filter_threshold(self):
        # Must be < _SURVEY_CONFIDENCE_THRESHOLD so _filter_dir_tools()
        # never enforces skip_tools from a synthetic survey.
        self.assertLess(
            ai._default_survey()["confidence"],
            ai._SURVEY_CONFIDENCE_THRESHOLD,
        )

    def test_filter_returns_full_toolbox_for_default(self):
        all_names = {t["name"] for t in ai._DIR_TOOLS}
        result = {t["name"] for t in ai._filter_dir_tools(ai._default_survey())}
        self.assertEqual(result, all_names)

    def test_skip_tools_is_empty(self):
        self.assertEqual(ai._default_survey()["skip_tools"], [])


if __name__ == "__main__":
    unittest.main()
