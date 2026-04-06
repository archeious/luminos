"""Tests for luminos_lib/tree.py"""

import os
import tempfile
import unittest

from luminos_lib.tree import build_tree, render_tree, _human_size


class TestHumanSize(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(_human_size(0), "0 B")
        self.assertEqual(_human_size(512), "512 B")

    def test_kilobytes(self):
        self.assertEqual(_human_size(1024), "1.0 KB")

    def test_megabytes(self):
        self.assertEqual(_human_size(1024 * 1024), "1.0 MB")

    def test_fractional(self):
        self.assertEqual(_human_size(1536), "1.5 KB")


class TestBuildTree(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _create(self, structure):
        """Create files/dirs from a dict: {name: None=file, name: dict=dir}"""
        def _recurse(base, items):
            for name, content in items.items():
                path = os.path.join(base, name)
                if content is None:
                    with open(path, "w") as f:
                        f.write("x")
                else:
                    os.makedirs(path, exist_ok=True)
                    _recurse(path, content)
        _recurse(self.tmpdir, structure)

    def test_root_node_type(self):
        tree = build_tree(self.tmpdir)
        self.assertEqual(tree["type"], "directory")
        self.assertEqual(tree["path"], self.tmpdir)

    def test_lists_files(self):
        self._create({"a.py": None, "b.py": None})
        tree = build_tree(self.tmpdir)
        names = {c["name"] for c in tree["children"]}
        self.assertIn("a.py", names)
        self.assertIn("b.py", names)

    def test_file_node_has_size(self):
        self._create({"hello.txt": None})
        tree = build_tree(self.tmpdir)
        f = next(c for c in tree["children"] if c["name"] == "hello.txt")
        self.assertIn("size", f)
        self.assertGreater(f["size"], 0)

    def test_hidden_files_excluded_by_default(self):
        self._create({".hidden": None, "visible.py": None})
        tree = build_tree(self.tmpdir)
        names = {c["name"] for c in tree["children"]}
        self.assertNotIn(".hidden", names)
        self.assertIn("visible.py", names)

    def test_hidden_files_included_when_requested(self):
        self._create({".hidden": None})
        tree = build_tree(self.tmpdir, show_hidden=True)
        names = {c["name"] for c in tree["children"]}
        self.assertIn(".hidden", names)

    def test_exclude_directory(self):
        self._create({"node_modules": {"pkg.js": None}, "main.py": None})
        tree = build_tree(self.tmpdir, exclude=["node_modules"])
        names = {c["name"] for c in tree["children"]}
        self.assertNotIn("node_modules", names)
        self.assertIn("main.py", names)

    def test_max_depth_truncates(self):
        self._create({"a": {"b": {"c": {"deep.py": None}}}})
        tree = build_tree(self.tmpdir, max_depth=1)
        # depth 0 = root, depth 1 = "a", depth 2 would be "b" but truncated
        a = next(c for c in tree["children"] if c["name"] == "a")
        b = next(c for c in a["children"] if c["name"] == "b")
        self.assertTrue(b.get("truncated"))

    def test_nested_directory(self):
        self._create({"src": {"main.py": None}})
        tree = build_tree(self.tmpdir)
        src = next(c for c in tree["children"] if c["name"] == "src")
        self.assertEqual(src["type"], "directory")
        children = src["children"]
        self.assertTrue(any(c["name"] == "main.py" for c in children))


class TestRenderTree(unittest.TestCase):
    def _simple_tree(self):
        return {
            "name": "mydir",
            "type": "directory",
            "path": "/tmp/mydir",
            "children": [
                {"name": "file.py", "type": "file", "path": "/tmp/mydir/file.py", "size": 1024},
                {
                    "name": "subdir",
                    "type": "directory",
                    "path": "/tmp/mydir/subdir",
                    "children": [],
                },
            ],
        }

    def test_root_name_in_output(self):
        tree = self._simple_tree()
        rendered = render_tree(tree)
        self.assertIn("mydir/", rendered)

    def test_file_with_size_in_output(self):
        tree = self._simple_tree()
        rendered = render_tree(tree)
        self.assertIn("file.py", rendered)
        self.assertIn("1.0 KB", rendered)

    def test_subdir_has_slash(self):
        tree = self._simple_tree()
        rendered = render_tree(tree)
        self.assertIn("subdir/", rendered)

    def test_truncated_dir_shows_ellipsis(self):
        tree = {
            "name": "root",
            "type": "directory",
            "path": "/root",
            "children": [
                {"name": "deep", "type": "directory", "path": "/root/deep", "truncated": True},
            ],
        }
        rendered = render_tree(tree)
        self.assertIn("...", rendered)

    def test_permission_error_shown(self):
        tree = {
            "name": "root",
            "type": "directory",
            "path": "/root",
            "children": [
                {
                    "name": "locked",
                    "type": "directory",
                    "path": "/root/locked",
                    "error": "permission denied",
                    "children": [],
                }
            ],
        }
        rendered = render_tree(tree)
        self.assertIn("permission denied", rendered)


if __name__ == "__main__":
    unittest.main()
