#!/usr/bin/env python3
"""The public surface of warrant-graph as checks: what the core package may import, and what
the distribution ships. The repository's machinery (tools/, the review loop, the waker, the
gate) is evidence behind the package, never part of it.

B1 reads the AST of every module of warrant/ (no import, no grep): each import names the
standard library (sys.stdlib_module_names), `cryptography` or warrant itself, and a relative
import stays inside the package. A call that loads code by a computed name is refused,
since the AST cannot name what it loads: the builtins __import__, exec, eval and compile,
and any .import_module, .exec_module, .load_module or .__import__ (re.compile is neither).

W1-W4 and S1 read a wheel and an sdist: the ones named on the command line (release.yml
passes the artifacts it publishes), or ones built here from a copy of this tree with
setuptools' own PEP 517 hooks (no network, no build isolation; the running interpreter
needs setuptools>=61). The copy takes pyproject.toml, warrant/ and warrant_agent/ from
WARRANT_IMPL where it has them, so a mutant of pyproject.toml is built.

    python3 tests/boundary_test.py
    python3 tests/boundary_test.py --wheel dist/W.whl --sdist dist/S.tar.gz
"""
import argparse
import ast
import email.parser
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

from world import ROOT, check, finish

# The public surface. Changing it is a release decision, made here and in pyproject.toml.
DIST = "warrant-graph"
PUBLIC = ("warrant", "warrant_agent")
SCRIPTS = {"warrant": "warrant.cli:main", "warrant-agent": "warrant_agent.cli:main",
           "warrant-agent-mcp": "warrant_agent.mcp_server:main"}
REQUIRES = ["cryptography>=41"]
EXTRAS = {"pilot", "mcp"}
CORE_DEPS = {"cryptography"}
# Directories of the repository that no artifact may carry, at any depth.
INTERNAL = {"tools", "tests", ".warrant", ".github", "examples", "integrations", "work", "warrant_pilot",
            "third_party", "trust", "scratchpad"}
SDIST_TOP = {"PKG-INFO", "README.md", "LICENSE", "pyproject.toml", "setup.cfg", "warrant", "warrant_agent",
             "warrant_graph.egg-info"}
# Builtins called by name, and loader methods called on anything (re.compile is neither).
DYNAMIC_NAMES = {"__import__", "exec", "eval", "compile"}
DYNAMIC_ATTRS = {"__import__", "import_module", "exec_module", "load_module"}


def impl_or_root(rel):
    """The copy under test (WARRANT_IMPL) where it has `rel`, else this checkout's."""
    impl = os.environ.get("WARRANT_IMPL")
    if impl and (Path(impl) / rel).exists():
        return Path(impl) / rel
    return ROOT / rel


def boundary_problems(modules):
    """[(module, line, problem)] for {package-relative path: source} of warrant/."""
    allowed = set(sys.stdlib_module_names) | CORE_DEPS | {"warrant"}
    out = []
    for rel, src in sorted(modules.items()):
        depth = len(PurePosixPath(rel).parts)       # warrant/x.py may go up 1 level, warrant/a/x.py 2
        for node in ast.walk(ast.parse(src, rel)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level > depth:
                    out.append((rel, node.lineno, f"relative import of level {node.level} leaves the package"))
                elif node.level == 0:
                    names = [node.module]
            elif isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name) and f.id in DYNAMIC_NAMES or isinstance(f, ast.Attribute) and f.attr in DYNAMIC_ATTRS:
                    out.append((rel, node.lineno, f"{ast.unparse(f)}() loads code the AST cannot name"))
            out += [(rel, node.lineno, f"imports {n}") for n in names if n.split(".")[0] not in allowed]
    return out


def core_modules(wheel):
    """{path relative to warrant/: source}: from the wheel when one is named, else the source."""
    if wheel:
        with zipfile.ZipFile(wheel) as z:
            return {n[len("warrant/"):]: z.read(n).decode() for n in z.namelist()
                    if n.startswith("warrant/") and n.endswith(".py")}
    d = impl_or_root("warrant")
    return {p.relative_to(d).as_posix(): p.read_text() for p in sorted(d.rglob("*.py")) if "__pycache__" not in p.parts}


def build(out):
    """(wheel, sdist) built from a copy of this tree (what git tracks, and untracked files it does
    not ignore), with the copy under test laid over it."""
    stage = out / "src"
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                            capture_output=True, check=True).stdout.decode().split("\0")
    for rel in filter(None, listed):
        if (ROOT / rel).is_file() and not (ROOT / rel).is_symlink():
            (stage / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, stage / rel)
    for rel in ("pyproject.toml", *PUBLIC):
        src = impl_or_root(rel)
        if src != ROOT / rel:
            if src.is_dir():
                shutil.rmtree(stage / rel, ignore_errors=True)
                shutil.copytree(src, stage / rel, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(src, stage / rel)
    dist = out / "dist"
    dist.mkdir()
    built = []
    # One process per hook: setuptools keeps state between the two calls of one process, and
    # the second then writes its sdist elsewhere.
    for hook in ("build_wheel", "build_sdist"):
        code = f"import sys\nfrom setuptools import build_meta as b\nprint('\\nBUILT', b.{hook}(sys.argv[1]))\n"
        p = subprocess.run([sys.executable, "-c", code, str(dist)], cwd=stage, capture_output=True, text=True,
                           check=False, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        if p.returncode != 0:
            sys.exit(f"{hook} failed (needs setuptools>=61 in {sys.executable}):\n{p.stderr[-3000:]}")
        built.append(dist / p.stdout.splitlines()[-1].split()[1])     # the hook's own line, after setuptools' log
    return tuple(built)


def source_files(pkg, rel_root):
    """The Python files of package `pkg` in the tree the artifacts were built from, relative to `rel_root`."""
    d = impl_or_root(pkg)
    return {f"{rel_root}{pkg}/{p.relative_to(d).as_posix()}" for p in d.rglob("*.py") if "__pycache__" not in p.parts}


def internal(names):
    return sorted(n for n in names if INTERNAL & set(PurePosixPath(n).parts))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wheel")
    ap.add_argument("--sdist")
    a = ap.parse_args()
    if bool(a.wheel) != bool(a.sdist):
        sys.exit("name both --wheel and --sdist, or neither")

    modules = core_modules(a.wheel)
    found = boundary_problems(modules)
    check("B1", {"engine.py", "cli.py", "store.py", "keys.py"} <= set(modules) and not found,
          "warrant/ imports only the standard library, cryptography and itself; no import by a computed "
          "name; the scope holds the core's modules", found or sorted(modules))

    tmp = Path(tempfile.mkdtemp(prefix="warrant-boundary-"))
    try:
        wheel, sdist = (Path(a.wheel), Path(a.sdist)) if a.wheel else build(tmp)
        project = tomllib.loads(impl_or_root("pyproject.toml").read_text())
        declared = project["tool"]["setuptools"]["packages"]
        version = project["project"]["version"]
        info = f"{DIST.replace('-', '_')}-{version}.dist-info"

        with zipfile.ZipFile(wheel) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            meta = email.parser.Parser().parsestr(z.read(f"{info}/METADATA").decode()) if f"{info}/METADATA" in names else None
            entry = z.read(f"{info}/entry_points.txt").decode() if f"{info}/entry_points.txt" in names else ""
            init = z.read("warrant/__init__.py").decode() if "warrant/__init__.py" in names else ""
        top = {n.split("/")[0] for n in names}
        check("W1", declared == list(PUBLIC) and top == set(PUBLIC) | {info},
              f"the wheel holds exactly the declared packages {list(PUBLIC)} and its dist-info",
              f"declared {declared}, top level {sorted(top)}")
        check("W2", not internal(names), "no wheel member lies under tools/, tests/, .warrant/ or another "
              "repository directory", internal(names)[:10])
        want = set().union(*(source_files(p, "") for p in PUBLIC))
        got = {n for n in names if n.split("/")[0] in PUBLIC}
        check("W3", got == want, "each package ships exactly its source modules",
              {"missing": sorted(want - got)[:10], "extra": sorted(got - want)[:10]})

        scripts = {}
        section = None
        for line in entry.splitlines():
            if line.startswith("["):
                section = line.strip("[] ")
            elif "=" in line and section == "console_scripts":
                k, v = (s.strip() for s in line.split("=", 1))
                scripts[k] = v
        plain = sorted(r for r in (meta.get_all("Requires-Dist") or []) if "extra ==" not in r) if meta else None
        versions = [node.value.value for node in ast.parse(init).body if isinstance(node, ast.Assign)
                    and [t.id for t in node.targets if isinstance(t, ast.Name)] == ["__version__"]
                    and isinstance(node.value, ast.Constant)]
        got_meta = meta and (meta["Name"], meta["Version"], plain, set(meta.get_all("Provides-Extra") or []))
        check("W4", got_meta == (DIST, version, REQUIRES, EXTRAS) and scripts == SCRIPTS and versions == [version],
              f"metadata: {DIST} {version}, sole requirement {REQUIRES}, extras {sorted(EXTRAS)}, the three "
              "commands, and warrant.__version__ equal to the version",
              {"metadata": got_meta, "scripts": scripts, "__version__": versions})

        with tarfile.open(sdist) as t:
            members = [m.name for m in t.getmembers() if m.isfile()]
        root = f"{DIST.replace('-', '_')}-{version}/"
        inner = [m[len(root):] for m in members if m.startswith(root)]
        top = {m.split("/")[0] for m in inner}
        want = set().union(*(source_files(p, "") for p in PUBLIC))
        got = {m for m in inner if m.split("/")[0] in PUBLIC}
        check("S1", len(inner) == len(members) and top <= SDIST_TOP and not internal(inner) and got == want,
              "the sdist holds the packages' source modules, the project files and its own metadata, nothing "
              "of the repository's machinery",
              {"outside the root": len(members) - len(inner), "top": sorted(top - SDIST_TOP),
               "internal": internal(inner)[:10], "missing": sorted(want - got)[:5], "extra": sorted(got - want)[:5]})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return finish("boundary_test")


if __name__ == "__main__":
    sys.exit(main())
