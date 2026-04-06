"""Tests for luminos_lib/report.py"""

import unittest

from luminos_lib.report import format_flags, format_report


class TestFormatFlags(unittest.TestCase):
    def test_empty_returns_empty_string(self):
        self.assertEqual(format_flags([]), "")
        self.assertEqual(format_flags(None), "")

    def test_single_flag(self):
        flags = [{"severity": "concern", "path": "main.py", "finding": "Hardcoded secret"}]
        result = format_flags(flags)
        self.assertIn("CONCERN", result)
        self.assertIn("main.py", result)
        self.assertIn("Hardcoded secret", result)

    def test_severity_ordering(self):
        flags = [
            {"severity": "info", "path": "a.py", "finding": "note"},
            {"severity": "critical", "path": "b.py", "finding": "bad"},
            {"severity": "concern", "path": "c.py", "finding": "watch"},
        ]
        result = format_flags(flags)
        critical_pos = result.index("CRITICAL")
        concern_pos = result.index("CONCERN")
        info_pos = result.index("INFO")
        self.assertLess(critical_pos, concern_pos)
        self.assertLess(concern_pos, info_pos)

    def test_unknown_severity_defaults_to_info_order(self):
        flags = [{"severity": "weird", "path": "x.py", "finding": "something"}]
        result = format_flags(flags)
        self.assertIn("WEIRD", result)

    def test_missing_path_defaults_to_general(self):
        flags = [{"severity": "info", "finding": "general note"}]
        result = format_flags(flags)
        self.assertIn("general", result)

    def test_flags_header_present(self):
        flags = [{"severity": "info", "path": "x.py", "finding": "ok"}]
        result = format_flags(flags)
        self.assertIn("FLAGS", result)


class TestFormatReport(unittest.TestCase):
    def _minimal_report(self):
        return {
            "tree_rendered": "mydir/\n  file.py",
            "file_categories": {"source": 2, "config": 1},
            "languages": ["Python"],
            "lines_of_code": {"Python": 150},
            "large_files": [],
            "recent_files": [
                {"modified_human": "2026-04-06 10:00:00", "name": "main.py", "path": "/tmp/main.py"}
            ],
            "top_directories": [
                {"size_human": "10.0 KB", "path": "/tmp/mydir"}
            ],
        }

    def test_header_contains_target(self):
        result = format_report(self._minimal_report(), "/tmp/mydir")
        self.assertIn("/tmp/mydir", result)

    def test_file_type_section(self):
        result = format_report(self._minimal_report(), "/tmp")
        self.assertIn("source", result)
        self.assertIn("config", result)

    def test_languages_section(self):
        result = format_report(self._minimal_report(), "/tmp")
        self.assertIn("Python", result)
        self.assertIn("150", result)

    def test_recent_files_section(self):
        result = format_report(self._minimal_report(), "/tmp")
        self.assertIn("main.py", result)
        self.assertIn("2026-04-06", result)

    def test_disk_usage_section(self):
        result = format_report(self._minimal_report(), "/tmp")
        self.assertIn("10.0 KB", result)

    def test_tree_rendered_included(self):
        result = format_report(self._minimal_report(), "/tmp")
        self.assertIn("mydir/", result)

    def test_no_source_files_message(self):
        report = self._minimal_report()
        report["languages"] = []
        report["lines_of_code"] = {}
        result = format_report(report, "/tmp")
        self.assertIn("No source code files detected", result)

    def test_no_recent_files_message(self):
        report = self._minimal_report()
        report["recent_files"] = []
        result = format_report(report, "/tmp")
        self.assertIn("No recent files found", result)

    def test_ai_brief_included_when_present(self):
        report = self._minimal_report()
        report["ai_brief"] = "This is a Python project."
        result = format_report(report, "/tmp")
        self.assertIn("This is a Python project.", result)
        self.assertIn("SUMMARY (AI)", result)

    def test_ai_detailed_included_when_present(self):
        report = self._minimal_report()
        report["ai_detailed"] = "Detailed breakdown here."
        result = format_report(report, "/tmp")
        self.assertIn("Detailed breakdown here.", result)
        self.assertIn("DETAILED AI ANALYSIS", result)

    def test_flags_included_when_provided(self):
        report = self._minimal_report()
        flags = [{"severity": "critical", "path": "secret.py", "finding": "API key exposed"}]
        result = format_report(report, "/tmp", flags=flags)
        self.assertIn("API key exposed", result)

    def test_large_files_section(self):
        report = self._minimal_report()
        report["large_files"] = [{"name": "big.py", "reasons": ["lines: 5000"]}]
        result = format_report(report, "/tmp")
        self.assertIn("big.py", result)
        self.assertIn("lines: 5000", result)

    def test_no_categories_message(self):
        report = self._minimal_report()
        report["file_categories"] = {}
        result = format_report(report, "/tmp")
        self.assertIn("No files found", result)

    def test_total_loc_shown(self):
        report = self._minimal_report()
        report["lines_of_code"] = {"Python": 100, "JavaScript": 50}
        result = format_report(report, "/tmp")
        self.assertIn("150", result)  # total

    def test_report_ends_with_footer(self):
        result = format_report(self._minimal_report(), "/tmp")
        self.assertIn("End of report.", result)


if __name__ == "__main__":
    unittest.main()
