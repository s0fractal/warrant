"""The files of a repository that running one of its Python files loads, read from the source without running it.

`closure(root, start, searched)` follows every import statement, wherever in a file it stands (inside a function
too), and resolves each name with the import system itself: importlib's finders over the `searched` directories of
the repository, then this interpreter's own path. So a same-name package or an extension module the interpreter
would load is what the walk names, not the .py file of that name (Codex challenge of dda3ad65 on the gate's walk). A
module found outside the repository (the standard library, an installed package) is the environment, not named. A
directory without `__init__` is named with a trailing slash.

It also follows the programs a file starts by name: in a list or tuple literal, `"-m", "pkg.mod"` walks that module
(and `pkg/__main__.py` for a package) and `"-c", "<code>"` walks the imports of that code. A program a file starts by
a path it computes, one in another language, or a file it reads as data is not named: that is the walk's stated
limit, and what reads it names the limit with it.

It raises `Unreadable` when a file of the closure cannot be parsed: a closure that cannot be established is never a
partial one (warrant.claims accepts nothing on it). Nothing of `root` is imported or run."""
import ast
import importlib
import importlib.machinery
import os
import sys
from pathlib import Path, PurePosixPath


class Unreadable(Exception):
    """A file of the closure is not Python this interpreter parses (or not readable)."""


def _programs(tree):
    """[(flag, value)] of each `"-m", "x"` and `"-c", "x"` pair of string constants in a list or tuple literal."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.List, ast.Tuple)):
            elts = n.elts
            for a, b in zip(elts, elts[1:]):
                if (isinstance(a, ast.Constant) and a.value in ("-m", "-c") and isinstance(b, ast.Constant)
                        and isinstance(b.value, str)):
                    out.append((a.value, b.value))
    return out


def closure(root, start, searched=("",)):
    """The repository paths (POSIX, relative to `root`) that running `start` (a path relative to `root`) loads."""
    importlib.invalidate_caches()
    root = Path(os.path.realpath(root))
    here = [str(root / d) for d in searched]
    outside = [q for q in sys.path if q and root not in (Path(os.path.realpath(q)), *Path(os.path.realpath(q)).parents)]

    def find(name, where):
        """(repository file, the directories its submodules are searched in or None) of module `name` searched in
        `where` (None: a top-level name); (None, None) when the interpreter finds it outside `root`, or nowhere."""
        if where is None and (name in sys.builtin_module_names or importlib.machinery.FrozenImporter.find_spec(name)):
            return None, None
        try:
            spec = importlib.machinery.PathFinder.find_spec(name, here + outside if where is None else where)
        except (ImportError, ValueError):
            return None, None
        if spec is None:
            return None, None
        inner = list(spec.submodule_search_locations or []) or None
        at = Path(spec.origin if spec.has_location else inner[0])
        if root not in at.parents:
            return None, None
        return at.relative_to(root).as_posix() + ("" if spec.has_location else "/"), inner

    seen, todo = set(), [(start, PurePosixPath(start).parent.parts)]

    def load(parts):
        """Follow a dotted name from the top, queueing each repository file on the way; the directories the last
        one's submodules are searched in (None: it is a module, or outside)."""
        where = None
        for n, name in enumerate(parts):
            f, where = find(name, where)
            if f is None:
                return None
            todo.append((f, tuple(parts[:n + 1] if where else parts[:n])))
            if where is None:
                return None
        return where

    def imports(tree, package):
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    load(a.name.split("."))
            elif isinstance(n, ast.ImportFrom):
                up = list(package[:len(package) - n.level + 1]) if n.level else []
                where = load(up + (n.module.split(".") if n.module else []))
                for a in n.names if where else []:
                    sub, inner = find(a.name, where)
                    if sub:
                        todo.append((sub, tuple(up + (n.module.split(".") if n.module else []) + ([a.name] if inner else []))))

    while todo:
        f, package = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        if not f.endswith(".py"):
            continue
        try:
            tree = ast.parse((root / f).read_text(), filename=f)
        except (OSError, SyntaxError, ValueError, UnicodeDecodeError) as e:
            raise Unreadable(f"{f}: {type(e).__name__}") from None
        imports(tree, package)
        for flag, value in _programs(tree):
            if flag == "-m":
                where = load(value.split("."))
                if where:
                    main, _ = find("__main__", where)
                    if main:
                        todo.append((main, tuple(value.split("."))))
            else:
                try:
                    code = ast.parse(value)
                except (SyntaxError, ValueError):
                    continue                    # not Python: a string that only follows a "-c"
                imports(code, ())
    return seen
