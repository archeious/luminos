"""AST structure extraction for Luminos using tree-sitter."""

import json
import os

import tree_sitter
import tree_sitter_python
import tree_sitter_javascript
import tree_sitter_rust
import tree_sitter_go

# Extension → (grammar_module, language_name)
_TS_LANGUAGES = {
    ".py": (tree_sitter_python, "python"),
    ".js": (tree_sitter_javascript, "javascript"),
    ".jsx": (tree_sitter_javascript, "javascript"),
    ".mjs": (tree_sitter_javascript, "javascript"),
    ".rs": (tree_sitter_rust, "rust"),
    ".go": (tree_sitter_go, "go"),
}

# Precomputed Language objects.
_TS_LANG_CACHE = {}


def _get_ts_parser(ext):
    """Return a (Parser, language_name) tuple for a file extension, or None."""
    entry = _TS_LANGUAGES.get(ext)
    if entry is None:
        return None
    module, lang_name = entry
    if lang_name not in _TS_LANG_CACHE:
        _TS_LANG_CACHE[lang_name] = tree_sitter.Language(module.language())
    lang = _TS_LANG_CACHE[lang_name]
    parser = tree_sitter.Parser(lang)
    return parser, lang_name


# ---------------------------------------------------------------------------
# Tree-sitter node helpers
# ---------------------------------------------------------------------------

def _child_by_type(node, *types):
    for c in node.children:
        if c.type in types:
            return c
    return None


def _text(node):
    return node.text.decode("utf-8", errors="replace") if node else ""


# ---------------------------------------------------------------------------
# Per-language handlers: (root_node, source_bytes) -> dict
# ---------------------------------------------------------------------------

def _parse_python(root, source):
    functions = []
    classes = []
    imports = []
    has_docstrings = False
    comment_lines = 0

    def _walk(node):
        nonlocal has_docstrings, comment_lines
        for child in node.children:
            ntype = child.type

            if ntype in ("comment", "line_comment", "block_comment"):
                comment_lines += child.text.decode("utf-8", errors="replace").count("\n") + 1

            if ntype == "function_definition":
                name = _text(_child_by_type(child, "identifier"))
                params = _text(_child_by_type(child, "parameters"))
                ret = _child_by_type(child, "type")
                sig = f"{name}{params}"
                if ret:
                    sig += f" -> {_text(ret)}"
                functions.append(sig)
            elif ntype == "class_definition":
                name = _text(_child_by_type(child, "identifier"))
                methods = []
                body = _child_by_type(child, "block")
                if body:
                    for c in body.children:
                        if c.type == "function_definition":
                            mname = _text(_child_by_type(c, "identifier"))
                            mparams = _text(_child_by_type(c, "parameters"))
                            mret = _child_by_type(c, "type")
                            msig = f"{mname}{mparams}"
                            if mret:
                                msig += f" -> {_text(mret)}"
                            methods.append(msig)
                classes.append({"name": name, "methods": methods[:20]})
            elif ntype in ("import_statement", "import_from_statement"):
                imports.append(child.text.decode("utf-8", errors="replace").strip())
            elif ntype == "expression_statement":
                first = child.children[0] if child.children else None
                if first and first.type == "string":
                    has_docstrings = True

            _walk(child)

    _walk(root)

    source_text = source.decode("utf-8", errors="replace")
    line_count = len(source_text.split("\n"))
    code_lines = max(1, line_count - comment_lines)

    return {
        "language": "python",
        "functions": functions[:50],
        "classes": classes[:30],
        "imports": imports[:30],
        "line_count": line_count,
        "has_docstrings": has_docstrings,
        "has_comments": comment_lines > 0,
        "comment_to_code_ratio": round(comment_lines / code_lines, 2),
    }


def _parse_javascript(root, source):
    functions = []
    classes = []
    imports = []
    comment_lines = 0

    def _walk(node):
        nonlocal comment_lines
        for child in node.children:
            ntype = child.type

            if ntype in ("comment", "line_comment", "block_comment"):
                comment_lines += child.text.decode("utf-8", errors="replace").count("\n") + 1

            if ntype in ("function_declaration", "arrow_function", "function"):
                name = _text(_child_by_type(child, "identifier"))
                params = _text(_child_by_type(child, "formal_parameters"))
                functions.append(f"{name}{params}" if name else f"(anonymous){params}")
            elif ntype == "class_declaration":
                name = _text(_child_by_type(child, "identifier"))
                methods = []
                body = _child_by_type(child, "class_body")
                if body:
                    for c in body.children:
                        if c.type == "method_definition":
                            mname = _text(_child_by_type(c, "property_identifier"))
                            mparams = _text(_child_by_type(c, "formal_parameters"))
                            methods.append(f"{mname}{mparams}")
                classes.append({"name": name, "methods": methods[:20]})
            elif ntype == "import_statement":
                imports.append(child.text.decode("utf-8", errors="replace").strip())

            _walk(child)

    _walk(root)

    source_text = source.decode("utf-8", errors="replace")
    line_count = len(source_text.split("\n"))
    code_lines = max(1, line_count - comment_lines)

    return {
        "language": "javascript",
        "functions": functions[:50],
        "classes": classes[:30],
        "imports": imports[:30],
        "line_count": line_count,
        "has_docstrings": False,
        "has_comments": comment_lines > 0,
        "comment_to_code_ratio": round(comment_lines / code_lines, 2),
    }


def _parse_rust(root, source):
    functions = []
    classes = []
    imports = []
    comment_lines = 0

    def _walk(node):
        nonlocal comment_lines
        for child in node.children:
            ntype = child.type

            if ntype in ("comment", "line_comment", "block_comment"):
                comment_lines += child.text.decode("utf-8", errors="replace").count("\n") + 1

            if ntype == "function_item":
                name = _text(_child_by_type(child, "identifier"))
                params = _text(_child_by_type(child, "parameters"))
                ret = _child_by_type(child, "type_identifier", "generic_type",
                                     "reference_type", "scoped_type_identifier")
                sig = f"{name}{params}"
                if ret:
                    sig += f" -> {_text(ret)}"
                functions.append(sig)
            elif ntype in ("struct_item", "enum_item", "impl_item"):
                name = _text(_child_by_type(child, "type_identifier"))
                classes.append({"name": name or _text(child)[:60], "methods": []})
            elif ntype == "use_declaration":
                imports.append(child.text.decode("utf-8", errors="replace").strip())

            _walk(child)

    _walk(root)

    source_text = source.decode("utf-8", errors="replace")
    line_count = len(source_text.split("\n"))
    code_lines = max(1, line_count - comment_lines)

    return {
        "language": "rust",
        "functions": functions[:50],
        "classes": classes[:30],
        "imports": imports[:30],
        "line_count": line_count,
        "has_docstrings": False,
        "has_comments": comment_lines > 0,
        "comment_to_code_ratio": round(comment_lines / code_lines, 2),
    }


def _parse_go(root, source):
    functions = []
    classes = []
    imports = []
    comment_lines = 0

    def _walk(node):
        nonlocal comment_lines
        for child in node.children:
            ntype = child.type

            if ntype in ("comment", "line_comment", "block_comment"):
                comment_lines += child.text.decode("utf-8", errors="replace").count("\n") + 1

            if ntype == "function_declaration":
                name = _text(_child_by_type(child, "identifier"))
                params = _text(_child_by_type(child, "parameter_list"))
                functions.append(f"{name}{params}")
            elif ntype == "type_declaration":
                spec = _child_by_type(child, "type_spec")
                name = _text(_child_by_type(spec, "type_identifier")) if spec else ""
                classes.append({"name": name or _text(child)[:60], "methods": []})
            elif ntype == "import_declaration":
                imports.append(child.text.decode("utf-8", errors="replace").strip())

            _walk(child)

    _walk(root)

    source_text = source.decode("utf-8", errors="replace")
    line_count = len(source_text.split("\n"))
    code_lines = max(1, line_count - comment_lines)

    return {
        "language": "go",
        "functions": functions[:50],
        "classes": classes[:30],
        "imports": imports[:30],
        "line_count": line_count,
        "has_docstrings": False,
        "has_comments": comment_lines > 0,
        "comment_to_code_ratio": round(comment_lines / code_lines, 2),
    }


# ---------------------------------------------------------------------------
# Language handler registry
# ---------------------------------------------------------------------------

_LANGUAGE_HANDLERS = {
    "python": _parse_python,
    "javascript": _parse_javascript,
    "rust": _parse_rust,
    "go": _parse_go,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_structure(path):
    """Parse a source file and return its structural skeleton as a JSON string.

    Takes an absolute path. Returns a JSON string of the structure dict,
    or an error string if parsing fails or the language is unsupported.
    """
    if not os.path.isfile(path):
        return f"Error: '{path}' is not a file."

    ext = os.path.splitext(path)[1].lower()
    ts = _get_ts_parser(ext)
    if ts is None:
        return (f"Error: no grammar for extension '{ext}'. "
                f"Supported: {', '.join(sorted(_TS_LANGUAGES.keys()))}")

    parser, lang_name = ts

    handler = _LANGUAGE_HANDLERS.get(lang_name)
    if handler is None:
        return f"Error: no handler for language '{lang_name}'."

    try:
        with open(path, "rb") as f:
            source = f.read()
    except OSError as e:
        return f"Error reading file: {e}"

    tree = parser.parse(source)
    result = handler(tree.root_node, source)
    return json.dumps(result, indent=2)
