"""Shared walking helpers for the repository static checks (see test_repo_static_checks.py)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Folders that are never scanned: version control, installs, caches, and the archived design notes.
SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
                       "design-archive"})


def iter_files(root, suffixes):
    """Every file under `root` whose name ends in one of `suffixes`, skipping SKIP_DIRS; sorted."""
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        found += [Path(folder) / f for f in files if f.endswith(tuple(suffixes))]
    return sorted(found)


def python_string_literals(source):
    """[(line, text)] for every string literal in Python `source`, except docstrings. Comments are not
    strings, so they never appear. The literal parts of an f-string are listed one by one."""
    import ast

    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    found = [(n.lineno, n.value) for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]
    return sorted(found, key=lambda item: item[0])


def strip_front_end_comments(text):
    """`text` of a .js/.css/.html file with its comments blanked out (`/* */`, `//` to end of line,
    `<!-- -->`), keeping every line break so line numbers still match. String-aware: a `//` inside a
    quoted string (a URL) is text, not a comment. A quote that is never closed ends at the end of its
    line, so an apostrophe in HTML text cannot swallow the rest of the file. Regex literals containing
    quotes are not understood (good enough for this repository; a false hit goes in an allowlist)."""
    import re

    text = re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group()), text, flags=re.S)
    out, i, quote = [], 0, None
    while i < len(text):
        c, two = text[i], text[i:i + 2]
        if quote:
            if c == "\\":
                out.append(text[i:i + 2]); i += 2; continue
            if c == quote or (c == "\n" and quote != "`"):
                quote = None
            out.append(c); i += 1
        elif two == "//":
            while i < len(text) and text[i] != "\n":
                out.append(" "); i += 1
        elif two == "/*":
            end = text.find("*/", i + 2)
            end = len(text) if end == -1 else end + 2
            out.append(re.sub(r"[^\n]", " ", text[i:end])); i = end
        else:
            if c in "\"'`":
                quote = c
            out.append(c); i += 1
    return "".join(out)


# One dictionary per scan (filled in by the tickets that add the scans): {"path or snippet": "why it is fine"}.
ALLOWLISTS = {}


def unreasoned(allowlist):
    """The allowlist keys that carry no reason (an empty or blank explanation)."""
    return sorted(key for key, reason in allowlist.items() if not str(reason).strip())


# ---- what ships: the scope of the leftover-string and gender scans ----
_SHIPPED_DIRS = ("companion", "static", "electron", "tools", "animation-tools", "docs", "clips", "fillers")
_SHIPPED_SUFFIXES = (".py", ".js", ".html", ".json", ".bat", ".md", ".txt", ".sh", ".yml", ".yaml")


def shipped_files(root=None):
    """Files a visitor of the repository can read: the program, its page, tools, documents. NOT the
    test folders' code (tests/, tests_js/ list the very strings the scans look for) — only the Markdown
    inside tests_electron/. `.scratch/` is not listed: it is development debris removed in ticket 11."""
    root = Path(root or ROOT)
    found = [p for p in root.iterdir() if p.is_file() and p.suffix in _SHIPPED_SUFFIXES]
    for name in _SHIPPED_DIRS:
        if (root / name).is_dir():
            found += iter_files(root / name, _SHIPPED_SUFFIXES)
    if (root / "tests_electron").is_dir():
        found += iter_files(root / "tests_electron", (".md",))
    return sorted(set(found))


# ---- files a document tells the reader to open or run ----
_FILE_TOKEN = None


def mentioned_files_that_do_not_exist(text, generated=frozenset(), root=None, search=("", "docs", "electron")):
    """Backticked file names in Markdown `text` (e.g. `run.bat`, `docs/x.md`) that are neither in the repository
    nor in `generated` (files the reader creates, or that an install produces). A bare name is also looked for
    under the `search` folders (docs/ and electron/ by default)."""
    import re

    global _FILE_TOKEN
    _FILE_TOKEN = _FILE_TOKEN or re.compile(r"`([\w./\\-]+\.(?:bat|py|md|json|txt))`")
    root = Path(root or ROOT)
    missing = []
    for token in _FILE_TOKEN.findall(text):
        name = token.replace("\\", "/")
        if name.split("/")[-1] in generated:
            continue
        if not any((root / folder / name).exists() for folder in search):
            missing.append(token)
    return missing


# ---- relative links between Markdown files ----

def broken_markdown_links(path):
    """Relative links `[text](target)` in the Markdown file `path` whose target does not exist. Skipped: web and mail
    links, links to a place in the same page (#...), and anything inside a code fence, inline code or an HTML comment
    (an example is not a link)."""
    import re

    text = Path(path).read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    broken = []
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        if not (Path(path).parent / target.split("#")[0]).exists():
            broken.append(target)
    return broken
