"""Tests for luminos_lib/capabilities.py"""

import unittest
from unittest.mock import patch

from luminos_lib.capabilities import _check_package


class TestCheckPackage(unittest.TestCase):
    def test_importable_package(self):
        # json is always available in stdlib
        self.assertTrue(_check_package("json"))

    def test_missing_package(self):
        self.assertFalse(_check_package("_luminos_nonexistent_package_xyz"))

    def test_importable_returns_true(self):
        with patch("builtins.__import__", return_value=None):
            # patch doesn't work cleanly here; use a real stdlib module
            pass
        self.assertTrue(_check_package("os"))

    def test_import_error_returns_false(self):
        import builtins
        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "_fake_missing_module":
                raise ImportError("No module named '_fake_missing_module'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            self.assertFalse(_check_package("_fake_missing_module"))


if __name__ == "__main__":
    unittest.main()
