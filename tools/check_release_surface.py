#!/usr/bin/env python3
"""Fail when the docs promise a CLI surface the built artifact does not have.

WHY THIS EXISTS
---------------
`verify --store-mode --json` landed on master while the newest published release
(0.4.0) predated it, and the README documented it as *the* machine boundary. For
a stranger doing exactly what the README said, the documented surface did not
exist:

    error: unrecognized arguments: --store-mode --json

CI installs from the checkout; the sibling repo curls impl/warrant.py at a pinned
commit. Neither path touches the published artifact, so nothing could catch it.

WHAT IT CHECKS, AND HOW — the part that took two rounds to get honest
--------------------------------------------------------------------
Earlier versions extracted one physical line at a time and asked whether the
flag's TEXT appeared in `--help`. Three things were wrong with that, all found
by an independent gate:

  * a documented invocation spanning lines, or wrapped in `$( … )`, was not read
    at all — so `P=$(warrant propose … \\` + `--reas …)` stayed green with a
    flag that does not exist, and almost every `warrant-mcp` flag went unchecked;
  * presence in help text is not argv validity. `verify --json=true` and
    `verify --store ./pack --store-mode` both appear "supported" by that rule and
    both make the real CLI exit 2. Flag FORM and flag SCOPE are part of the
    contract;
  * discovery was an allowlist of directories, so a new `guides/` was invisible.

So there is now ONE place that turns documented shell into ordered argv
(`invocations()`), and ONE place that decides whether an argv is accepted
(`validate()`), which runs the real entry point and classifies argparse's own
usage errors. The selftest drives those same two functions. A rule that lives in
one place is the only kind that can be checked.

    python3 tools/check_release_surface.py                      # this checkout
    python3 tools/check_release_surface.py --bin /tmp/venv/bin  # a built wheel
    python3 tools/check_release_surface.py --selftest           # rejection matrix

Exit 0 = every documented invocation is accepted by the binaries under test.

THREAT MODEL, AND WHERE IT STOPS
--------------------------------
Declared: the wheel is the provenance root; the installation must match it; the
console wrappers must be pip's minimal dispatch shape; documented argv must be
accepted by the CLI's own parser and post-parse invariants. Within that, the
checker executes nothing but a parser.

Outside it, and NOT claimed: a venv whose `.pth` runs code at interpreter
startup; a compromised Python; a wheel that is itself malicious and honestly
described. Those are a different problem than "do the docs match the artifact",
and pretending otherwise would make this file's guarantee vaguer, not stronger.
"""
import argparse
import ast
import base64
import zipfile
import hashlib
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Discovery is `rglob("*.md")` minus an explicit exclusion set: an allowlist of
# directories silently stops covering anything added outside it, which is the
# same rot this gate exists to prevent.
#
# Excluded on purpose, with reasons:
#   reviews/    external reviewers quote commands that may never have existed
#   proposals/  design documents describe surfaces that deliberately do not exist
#   briefs/     instructions to reviewers, same reason
#   archive/    historical, by definition about older surfaces
DOC_EXCLUDE = {"reviews", "proposals", "briefs", "archive", "scratchpad",
               "build", "dist", ".git", "node_modules", ".venv", "venv",
               "target", "__pycache__", ".pytest_cache", "site-packages"}

# The contract is the WHEEL's entry points. `warrant-go` is a Go binary that
# ships from source, not from the package; it is validated only when a built
# binary is available, and its absence is announced rather than skipped
# silently (see `report_scope`).
WHEEL_CLIS = {"warrant", "warrant-mcp", "warrant-anchor"}
SOURCE_CLIS = {"warrant-go"}

# Shell metacharacters that end one command and begin another. `$(` and `)` are
# included so a command substitution's contents become a segment of their own --
# that is how `P=$(warrant propose …)` gets read.
# NB: `<` is NOT a splitter. Documentation writes placeholders as `<wid>`, and
# treating it as input redirection silently truncated the argv -- which showed up
# as four invented "missing required argument" failures the first time this ran.
SEGMENT_SPLIT = re.compile(r"\$\(|\)|\|\||\||&&|;|>>|>")

# Argparse's own vocabulary for "this argv is not valid". Anything else the
# command says is its business: a missing file or an empty store is a runtime
# outcome, not a broken documented surface.
ARGPARSE_ERRORS = (
    "unrecognized arguments",
    "invalid choice",
    "expected one argument",
    "expected at least one argument",
    "the following arguments are required",
    "ignored explicit argument",
    "not allowed with argument",
    "argument --",
    "invalid int value",
)

PLACEHOLDER = re.compile(r"^<.*>$|^\$\{?\w+\}?$|^\.\.\.$")


def logical_lines(text):
    """Yield (lineno, logical_line) for fenced shell, joining continuations.

    Two joins matter: a trailing backslash, and an unclosed `$(`. Both appear in
    this repo's own README, and a physical-line reader misses every flag after
    the break.
    """
    out, buf, start, depth, in_fence = [], "", None, 0, False
    for n, raw in enumerate(text.splitlines(), 1):
        if raw.lstrip().startswith("```"):
            if buf:
                out.append((start, buf))
                buf, depth = "", 0
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        line = raw.strip()
        if not buf:
            start = n
        cont = line.endswith("\\")
        buf = (buf + " " + (line[:-1] if cont else line)).strip()
        depth += buf.count("$(") - buf.count(")") - depth  # recompute from whole buf
        depth = max(0, buf.count("$(") - buf.count(")"))
        if cont or depth > 0:
            continue
        if buf:
            out.append((start, buf))
        buf, depth = "", 0
    if buf:
        out.append((start, buf))
    return out


ANGLE_PLACEHOLDER = re.compile(r"<[A-Za-z0-9_.:| -]*>")
OPERATORS = {"|", "||", "&&", ";", ">", ">>", "<", "(", ")", "&"}


def invocations(logical_line, known):
    """Every command in one logical line whose argv[0] is a CLI we own.

    Tokenising BEFORE segmentation is the whole point. A regex that split on
    shell metacharacters first could not tell an operator from the same
    character inside quotes, so `--reason "utility | fns" --not-a-real-flag`
    was cut in half and the tail never checked (Codex release-surface re-gate).
    shlex with punctuation_chars emits operators as their own tokens and leaves
    quoted text intact, which makes the split quote-aware by construction.

    Returns (invocations, error). A line that mentions a CLI we own but cannot
    be tokenised is an ERROR, not a silent skip -- unparseable documentation is
    a finding.
    """
    # `<wid>` is a placeholder, not a redirect. Mask before tokenising, or shlex
    # emits `<`, `wid`, `>` as three tokens and the command is truncated at the
    # first one -- which produced three invented "missing required argument"
    # findings the first time this ran.
    masked = []

    def mask(m):
        masked.append(m.group(0))
        return f"__PLACEHOLDER{len(masked) - 1}__"

    def unmask(tok):
        return re.sub(r"__PLACEHOLDER(\d+)__",
                      lambda m: masked[int(m.group(1))], tok)

    logical_line = ANGLE_PLACEHOLDER.sub(mask, logical_line)

    lx = shlex.shlex(logical_line, posix=True, punctuation_chars=True)
    lx.whitespace_split = True
    try:
        tokens = [unmask(x) for x in lx]
    except ValueError as e:
        if any(c in logical_line for c in known):
            return [], f"cannot tokenise (quoting?): {e}"
        return [], None

    found, current = [], []
    for tok in tokens + ["|"]:
        if tok in OPERATORS:
            if current:
                argv = list(current)
                argv[0] = re.sub(r"^\w+=\$?$", "", argv[0]) or (argv[1] if len(argv) > 1 else "")
                if argv[0] == "" and len(argv) > 1:
                    argv = argv[1:]
                # Match on BASENAME: `/tmp/tv/bin/warrant selftest` is our CLI
                # and PUBLISHING.md documents exactly that form, which an
                # exact-name match ignored entirely (Codex re-gate 2).
                if argv and Path(argv[0]).name in known:
                    argv = [Path(argv[0]).name] + argv[1:]
                    found.append(argv)
            current = []
            continue
        current.append(tok)
    return found, None


def concretise(argv, workdir):
    """Replace documentation placeholders with values that parse.

    Only the VALUES are invented. Flag names, their form (`--x=v` vs `--x v`)
    and their position are exactly as documented, because those are the parts
    under test.
    """
    out = []
    for tok in argv[1:]:
        if tok.startswith("-"):
            out.append(tok)
        elif PLACEHOLDER.match(tok):
            out.append("0" * 64)
        else:
            out.append(tok)
    return [argv[0]] + out


MODULES = {"warrant": "warrant", "warrant-mcp": "warrant_mcp",
           "warrant-anchor": "warrant_anchor"}

# Parse the argv with the CLI's own parser and NOTHING ELSE. No dispatch, no
# filesystem, no subprocess, no network.
# Parse the argv with the CLI's own parser and post-parse invariants, and
# NOTHING ELSE. No dispatch, no filesystem, no subprocess, no network.
#
# The module reports where it was imported FROM, because otherwise the gate can
# be told a lie about which artifact it checked: with PYTHONPATH pointing at a
# new checkout, the OLD 0.4.0 wheel "passed" 24/24 using the new parser (Codex
# release-surface re-gate 2). The interpreter is run with -I (isolated: no
# PYTHONPATH, no user site) and the caller verifies the origin it prints.
PARSE_SNIPPET = """
import sys
extra, modpath = sys.argv[1], sys.argv[3]
if modpath:
    import importlib.util
    spec = importlib.util.spec_from_file_location(sys.argv[2], modpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[sys.argv[2]] = mod
    spec.loader.exec_module(mod)
else:
    if extra:
        sys.path.insert(0, extra)
    mod = __import__(sys.argv[2])
sys.stderr.write("MODULE-ORIGIN " + (getattr(mod, "__file__", "") or "?") + "\\n")
if not hasattr(mod, "parse_cli"):
    raise SystemExit(3)
try:
    mod.parse_cli(sys.argv[4:])
except SystemExit as e:
    raise SystemExit(2 if e.code else 0)
raise SystemExit(0)
"""


DIST_NAME = "warrant-verify"


def _canon_dist(name):
    """PEP 503 canonical form, so `warrant-verify-evil` cannot pass as ours."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def inspect_distribution(binroot):
    """Decide what this artifact IS, using only the filesystem. No code runs.

    Every earlier version asked the module to describe itself, which is
    backwards: a hand-written module printed `MODULE-DIST warrant-verify 9.9` on
    its own stderr and the gate believed it, because the last line won (Codex
    release-surface re-gate 4). A subject cannot be its own provenance. The
    distribution is identified HERE, by reading dist-info, before the target
    interpreter is started at all.
    """
    problems = []
    venv = Path(binroot).resolve().parent
    site = sorted(venv.glob("lib/python*/site-packages")) or sorted(
        venv.glob("Lib/site-packages"))
    if not site:
        return None, [f"no site-packages under {venv}"]
    site = site[0]

    cands = [d for d in site.glob("*.dist-info")
             if _canon_dist(d.name.rsplit("-", 2)[0]) == _canon_dist(DIST_NAME)]
    if not cands:
        return None, [f"no `{DIST_NAME}` distribution is installed in {site} — "
                      f"whatever this environment provides, it is not the package "
                      f"under test"]
    info_dir = cands[0]

    meta_path = info_dir / "METADATA"
    meta = meta_path.read_text(errors="replace") if meta_path.exists() else ""
    name = next((l.split(":", 1)[1].strip() for l in meta.splitlines()
                 if l.lower().startswith("name:")), "")
    if _canon_dist(name) != _canon_dist(DIST_NAME):
        problems.append(f"dist-info declares Name: {name!r}, which is not "
                        f"`{DIST_NAME}` (exact canonical match required)")
    version = next((l.split(":", 1)[1].strip() for l in meta.splitlines()
                    if l.lower().startswith("version:")), "?")

    record = {}
    rec = info_dir / "RECORD"
    if not rec.exists():
        problems.append("dist-info has no RECORD; the installed files cannot be "
                        "attributed to the distribution")
    else:
        for line in rec.read_text(errors="replace").splitlines():
            parts = line.rsplit(",", 2)
            if len(parts) == 3 and parts[1].startswith("sha256="):
                record[parts[0]] = parts[1][len("sha256="):]

    eps, section = {}, ""
    ep = info_dir / "entry_points.txt"
    if not ep.exists():
        problems.append("dist-info has no entry_points.txt; the console commands "
                        "the documentation names are not declared by this package")
    else:
        for line in ep.read_text(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("["):
                section = line.strip("[]")
            elif "=" in line and section == "console_scripts":
                k, v = (x.strip() for x in line.split("=", 1))
                eps[k] = v

    return {"name": name, "version": version, "site": site, "record": record,
            "eps": eps, "info_dir": info_dir}, problems


def _attr_chain(node):
    """`sys.exit` -> ("sys", "exit"); anything not a plain dotted name -> None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return tuple(reversed(parts))


def _is_main_guard(node):
    return (isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
            and len(node.test.comparators) == 1
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value == "__main__"
            and not node.orelse)


def _is_argv0(node):
    return (isinstance(node, ast.Subscript)
            and _attr_chain(node.value) == ("sys", "argv")
            and isinstance(node.slice, ast.Constant) and node.slice.value == 0)


def _is_argv0_normalisation(stmt):
    """The `sys.argv[0] = …` line pip emits, in either shape it uses.

    Bounded on purpose: the value must be `re.sub(<const>, <const>, argv0)` or
    `argv0.removesuffix(<const>)`. Constants and argv[0] only -- no other name
    may appear, so this cannot become a hiding place.
    """
    if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
            and _is_argv0(stmt.targets[0])
            and isinstance(stmt.value, ast.Call)):
        return False
    call = stmt.value
    chain = _attr_chain(call.func)
    if chain == ("re", "sub"):
        args = call.args
        return (len(args) == 3 and all(isinstance(a, ast.Constant) for a in args[:2])
                and _is_argv0(args[2]) and not call.keywords)
    if isinstance(call.func, ast.Attribute) and call.func.attr == "removesuffix" \
            and _is_argv0(call.func.value):
        return (len(call.args) == 1 and isinstance(call.args[0], ast.Constant)
                and not call.keywords)
    return False


def _is_dispatch(stmt, func):
    """Exactly `sys.exit(<func>())`, with no arguments to either call."""
    if isinstance(stmt, ast.Expr):
        call = stmt.value
    elif isinstance(stmt, ast.Return):
        return False
    else:
        return False
    return (isinstance(call, ast.Call) and _attr_chain(call.func) == ("sys", "exit")
            and len(call.args) == 1 and not call.keywords
            and isinstance(call.args[0], ast.Call)
            and isinstance(call.args[0].func, ast.Name)
            and call.args[0].func.id == func
            and not call.args[0].args and not call.args[0].keywords)


def check_wrapper(text, module, func, venv):
    """Verify a console wrapper STATICALLY. Nothing here executes it.

    The previous version ran `<script> --help` and accepted exit 0. Two things
    were wrong with that (Codex release-surface re-gate 6). It does not prove
    dispatch -- a script that prints `usage: warrant-mcp` and exits 0 satisfies
    it while calling nothing -- and `--help` is only safe once argparse is
    reached, so a hostile wrapper's own statements run first. The gate itself
    created a file that way.

    So the wrapper is parsed, not run, and must be pip's minimal shape and
    nothing more:

        #!<the venv's python>
        import sys                      # and optionally `re`
        from <module> import <func>
        if __name__ == '__main__':
            sys.argv[0] = ...           # optional
            sys.exit(<func>())

    Any other statement, import, or call is a rejection. A wrapper that does
    more than dispatch is not the command the wheel declared.
    """
    problems = []
    lines = text.splitlines()
    if not lines or not lines[0].startswith("#!"):
        return [f"has no shebang"]
    interp = lines[0][2:].strip().split()[0]
    # Compare the interpreter's DIRECTORY, without following the interpreter
    # itself: a venv's `python3.x` is a symlink to the system interpreter, so
    # resolving it walks straight out of the venv and every wrapper looks wrong.
    interp_dir = os.path.realpath(os.path.dirname(interp))
    inside = (interp_dir + os.sep).startswith(os.path.realpath(venv) + os.sep)
    if not inside:
        problems.append(f"its shebang points at {interp}, outside {venv} — it "
                        f"would run a different interpreter than the one verified")

    body = "\n".join(lines[1:])
    try:
        tree = ast.parse(body)
    except SyntaxError as e:
        return problems + [f"is not valid Python ({e.msg}) — pip's wrapper is"]

    imported, dispatches = False, False
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue                                   # docstring / encoding
        if isinstance(node, ast.Import):
            if all(a.name in ("sys", "re") for a in node.names):
                continue
            return problems + [f"imports {', '.join(a.name for a in node.names)}; "
                               f"a dispatch wrapper imports only sys/re and the "
                               f"entry point"]
        if isinstance(node, ast.ImportFrom):
            if node.module == module and any(a.name == func for a in node.names):
                imported = True
                continue
            return problems + [f"imports from `{node.module}`, not the declared "
                               f"entry point `{module}`"]
        if isinstance(node, ast.If):
            # STRUCTURE, not a walk. ast.walk() visits nodes and asks whether
            # any of them looks wrong, which is a filter, not a shape: it
            # accepted `sys.modules["os"].system("touch marker")` sitting beside
            # the dispatch, because that call's func is an Attribute rather than
            # a Name (Codex final bounded re-gate). The guard body is now
            # matched statement by statement against the only two shapes pip
            # emits, and anything else is a rejection.
            if not _is_main_guard(node):
                return problems + ["has a top-level `if` that is not "
                                   "`if __name__ == '__main__':`"]
            seen_exit = 0
            for stmt in node.body:
                if _is_argv0_normalisation(stmt):
                    continue
                if _is_dispatch(stmt, func):
                    seen_exit += 1
                    continue
                return problems + [
                    f"has `{ast.unparse(stmt).splitlines()[0][:60]}` in its "
                    f"__main__ guard; pip's wrapper contains only the optional "
                    f"argv[0] normalisation and `sys.exit({func}())`"]
            if seen_exit != 1:
                return problems + [f"calls `sys.exit({func}())` {seen_exit} times; "
                                   f"pip's wrapper calls it exactly once"]
            dispatches = True
            continue
        return problems + [f"contains a top-level {type(node).__name__}; pip's "
                           f"wrapper has only imports and the __main__ guard"]

    if not imported:
        problems.append(f"never imports `{func}` from `{module}` — it cannot "
                        f"dispatch to the entry point the wheel declares")
    if not dispatches:
        problems.append(f"never calls `{func}()` — printing a usage line is not "
                        f"running the command")
    return problems


def inspect_wheel(wheel):
    """The PROVENANCE ROOT: the wheel file itself, read as a zip. No code runs.

    An installed venv cannot be its own root of trust. Editing a module AND its
    digest in the installed RECORD produced a clean pass, because RECORD lives
    inside the very thing it vouches for (Codex release-surface re-gate 5). The
    artifact you publish is the wheel; that is what must vouch for what is
    installed.

    Returns (info, problems) with the canonical name, version, the module
    digests taken FROM THE WHEEL, and the declared console-script targets in
    full `module:function` form.
    """
    problems = []
    try:
        z = zipfile.ZipFile(wheel)
    except (OSError, zipfile.BadZipFile) as e:
        return None, [f"{wheel} is not a readable wheel: {e}"]

    dist_info = sorted({n.split("/")[0] for n in z.namelist()
                        if n.endswith(".dist-info/METADATA")
                        or "/.dist-info/" in n or n.split("/")[0].endswith(".dist-info")})
    dist_info = [d for d in dist_info if d.endswith(".dist-info")]
    if not dist_info:
        return None, [f"{wheel} contains no .dist-info"]
    di = dist_info[0]

    meta = z.read(f"{di}/METADATA").decode(errors="replace")
    name = next((l.split(":", 1)[1].strip() for l in meta.splitlines()
                 if l.lower().startswith("name:")), "")
    version = next((l.split(":", 1)[1].strip() for l in meta.splitlines()
                    if l.lower().startswith("version:")), "?")
    if _canon_dist(name) != _canon_dist(DIST_NAME):
        problems.append(f"the wheel declares Name: {name!r}, not `{DIST_NAME}`")

    digests = {}
    for mod in MODULES.values():
        member = f"{mod}.py"
        if member not in z.namelist():
            problems.append(f"the wheel does not contain `{member}`")
            continue
        digests[member] = hashlib.sha256(z.read(member)).hexdigest()

    eps, section = {}, ""
    try:
        for line in z.read(f"{di}/entry_points.txt").decode(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("["):
                section = line.strip("[]")
            elif "=" in line and section == "console_scripts":
                k, v = (x.strip() for x in line.split("=", 1))
                eps[k] = v
    except KeyError:
        problems.append("the wheel declares no console scripts")

    return {"name": name, "version": version, "digests": digests, "eps": eps,
            "wheel": str(wheel)}, problems


def check_installation(binroot, wheel_info, problems):
    """The installation must match the WHEEL, and its commands must actually run."""
    binroot = Path(binroot).resolve()
    venv = binroot.parent
    site = sorted(venv.glob("lib/python*/site-packages")) or sorted(
        venv.glob("Lib/site-packages"))
    if not site:
        return problems + [f"no site-packages under {venv}"]
    site = site[0]

    for cli, mod in MODULES.items():
        member = f"{mod}.py"
        installed = site / member
        want = wheel_info["digests"].get(member)
        if want is None:
            continue                                   # already reported
        if not installed.exists():
            problems.append(f"`{member}` from the wheel is not installed in {site}")
        else:
            got = hashlib.sha256(installed.read_bytes()).hexdigest()
            if got != want:
                problems.append(
                    f"installed `{member}` does not match the WHEEL "
                    f"(wheel {want[:12]}…, installed {got[:12]}…). The installed "
                    f"RECORD is not consulted: it lives inside the thing it "
                    f"vouches for.")

        declared = wheel_info["eps"].get(cli)
        if declared is None:
            problems.append(f"the wheel does not declare a `{cli}` console script")
        elif declared != f"{mod}:main":
            problems.append(f"the wheel declares `{cli} = {declared}`, not "
                            f"`{mod}:main` — the target FUNCTION is part of the "
                            f"contract, not just the module")

        script = binroot / cli
        if not script.exists():
            problems.append(f"console script `{cli}` is missing from {binroot}")
            continue
        if not os.access(script, os.X_OK):
            problems.append(f"console script `{cli}` is not executable")
            continue
        # STATIC. The wrapper is never executed: see check_wrapper.
        try:
            text = script.read_text(errors="replace")
        except OSError as e:
            problems.append(f"console script `{cli}` is unreadable: {e}")
            continue
        func = (declared or f"{mod}:main").split(":")[-1]
        for issue in check_wrapper(text, mod, func, venv):
            problems.append(f"console script `{cli}` {issue}")
    return problems


def _record_digest(info, path):
    """(recorded, actual) sha256 for a file, as RECORD spells them."""
    site = info["site"].resolve()
    target = Path(path).resolve()
    actual = base64.urlsafe_b64encode(
        hashlib.sha256(target.read_bytes()).digest()).decode().rstrip("=")
    for key, want in info["record"].items():
        try:
            if (site / key).resolve() == target:
                return want, actual
        except (OSError, ValueError):
            continue
    return None, actual


def check_artifact(binroot, info, problems):
    """The wheel must OWN its modules and INSTALL its commands, verifiably."""
    site = info["site"]
    for cli, mod in MODULES.items():
        modfile = site / f"{mod}.py"
        if not modfile.exists():
            problems.append(f"`{mod}.py` is not in {site} — this environment does "
                            f"not contain the package's own module")
        else:
            want, got = _record_digest(info, modfile)
            if want is None:
                problems.append(f"`{mod}.py` is not listed in the distribution's "
                                f"RECORD — it is not a file this package installed")
            elif want != got:
                problems.append(f"`{mod}.py` does not match RECORD (recorded "
                                f"{want[:12]}…, found {got[:12]}…) — replaced since "
                                f"installation")

        declared = info["eps"].get(cli)
        if declared is None:
            problems.append(f"`{cli}` is not declared as a console script by the "
                            f"distribution")
        elif declared.split(":")[0] != mod:
            problems.append(f"`{cli}` is declared to dispatch to `{declared}`, "
                            f"not `{mod}`")

        script = Path(binroot) / cli
        if not script.exists():
            problems.append(f"console script `{cli}` is missing from {binroot}")
            continue
        if not os.access(script, os.X_OK):
            problems.append(f"console script `{cli}` is not executable — a file "
                            f"that cannot be run is not a command")
        elif script.read_bytes()[:2] != b"#!":
            problems.append(f"console script `{cli}` has no shebang — a text file "
                            f"containing the right words is not a command")
    return problems




def validate(python, extra_path, cli, argv, timeout=30, expect_origin=None,
             modroot=None):
    """(ok, detail) — does the CLI's OWN parser+invariants accept this argv?

    Parser-only, and that is not a detail. An earlier version RAN the command to
    find out whether it parsed, so checking a documented
    `warrant keygen --out <path>` created a key file outside the temp directory.
    Nothing here executes a command.

    FAIL-CLOSED everywhere: timeouts, unreachable interpreters, a module without
    `parse_cli`, an unexpected exit code, and an import whose origin is not the
    artifact under test are all failures.
    """
    mod = MODULES.get(Path(cli).name)
    if mod is None:
        return False, f"no parser-only entry point known for `{cli}`"
    # -I isolates the interpreter: no PYTHONPATH, no user site-packages. Without
    # it the environment decides which parser answers, and the answer is about
    # some other artifact.
    # When the artifact has been vetted, load THAT EXACT FILE by path rather
    # than importing by name: a .pth or a stray sys.path entry can otherwise
    # decide which module answers, and the answer would be about something else.
    modpath = str(Path(modroot) / f"{mod}.py") if modroot else ""
    cmd = ([python, "-I", "-c", PARSE_SNIPPET, extra_path or "", mod, modpath]
           + argv[1:])
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, f"parser did not answer within {timeout}s (fail-closed)"
    except OSError as e:
        return False, f"could not run the parser: {e}"

    origin, dist = "", ""
    for ln in (p.stderr or "").splitlines():
        if ln.startswith("MODULE-ORIGIN "):
            origin = ln[len("MODULE-ORIGIN "):].strip()
        elif ln.startswith("MODULE-DIST "):
            dist = ln[len("MODULE-DIST "):].strip()

    if expect_origin is not None:
        if not origin:
            return False, "the parser did not report where it was imported from"
        if not str(Path(origin).resolve()).startswith(str(Path(expect_origin).resolve())):
            return False, (f"imported the parser from {origin}, which is NOT inside "
                           f"{expect_origin} — this run would be about a different "
                           f"artifact")

    if p.returncode == 0:
        return True, "accepted"
    if p.returncode == 3:
        return False, (f"`{mod}` has no parse_cli(); this artifact predates the "
                       f"parser-only entry point and cannot be validated")
    if p.returncode == 2:
        err = [l for l in (p.stderr or p.stdout).strip().splitlines()
               if not l.startswith("MODULE-ORIGIN")]
        return False, (err[-1] if err else "rejected by the CLI")
    return False, f"parser exited {p.returncode} (fail-closed)"


def _artifact_checks():
    """Permanent cases for the TRUSTED preflight, built as real little venv trees.

    All four of these were demonstrated by hand once. A demonstration is
    evidence about the day it ran (Codex release-surface re-gate 4, P2), so they
    live here now, in the same function the gate calls.
    """
    out = []
    root = Path(tempfile.mkdtemp())

    def venv(name, dist="warrant-verify", version="1.0", eps=True,
             record=True, executable=True, shebang=True, tamper=False):
        v = root / name
        site = v / "lib" / "python3.99" / "site-packages"
        site.mkdir(parents=True)
        (v / "bin").mkdir(parents=True)
        body = "def parse_cli(argv=None):\n    return None\n"
        digests = {}
        for mod in MODULES.values():
            f = site / f"{mod}.py"
            f.write_text(body)
            digests[f"{mod}.py"] = base64.urlsafe_b64encode(
                hashlib.sha256(f.read_bytes()).digest()).decode().rstrip("=")
            if tamper and mod == "warrant_anchor":
                f.write_text(body + "# changed after install\n")
        d = site / f"{_canon_dist(dist).replace('-', '_')}-{version}.dist-info"
        d.mkdir()
        (d / "METADATA").write_text(f"Name: {dist}\nVersion: {version}\n")
        if record:
            (d / "RECORD").write_text(
                "\n".join(f"{k},sha256={h}," for k, h in digests.items()))
        if eps:
            (d / "entry_points.txt").write_text(
                "[console_scripts]\n" +
                "".join(f"{c} = {m}:main\n" for c, m in MODULES.items()))
        for c in MODULES:
            s = v / "bin" / c
            s.write_text("#!/bin/sh\nexit 0\n" if shebang else "not a script\n")
            if executable:
                s.chmod(0o755)
        return v / "bin"

    def clean(binroot):
        info, probs = inspect_distribution(binroot)
        if info is not None:
            probs = check_artifact(binroot, info, probs)
        return not probs

    out.append(("a well-formed artifact passes the preflight", clean(venv("good"))))
    out.append(("a venv with no such distribution is rejected",
                not clean(venv("nodist", dist="something-else"))))
    out.append(("`warrant-verify-evil` is not `warrant-verify`",
                not clean(venv("evil", dist="warrant-verify-evil"))))
    out.append(("a module changed after install is rejected (RECORD)",
                not clean(venv("tampered", tamper=True))))
    out.append(("a non-executable console script is rejected",
                not clean(venv("noexec", executable=False))))
    out.append(("a console script with no shebang is rejected",
                not clean(venv("noshebang", shebang=False))))
    out.append(("undeclared console scripts are rejected",
                not clean(venv("noeps", eps=False))))
    out.append(("a distribution with no RECORD is rejected",
                not clean(venv("norecord", record=False))))
    return out


def _wheel_root_checks():
    """The wheel is the root; the installation is checked against it.

    Built as a real wheel plus a real installation, so these exercise
    inspect_wheel/check_installation exactly as the gate does.
    """
    out = []
    root = Path(tempfile.mkdtemp())
    body = b"def main():\n    return 0\n\n\ndef parse_cli(argv=None):\n    return None\n"

    def build(name="warrant-verify", version="1.0", eps_func="main", modbody=body):
        w = root / f"{name.replace('-', '_')}-{version}.whl"
        di = f"{name.replace('-', '_')}-{version}.dist-info"
        with zipfile.ZipFile(w, "w") as z:
            z.writestr(f"{di}/METADATA", f"Name: {name}\nVersion: {version}\n")
            z.writestr(f"{di}/entry_points.txt", "[console_scripts]\n" + "".join(
                f"{c} = {m}:{eps_func}\n" for c, m in MODULES.items()))
            for m in MODULES.values():
                z.writestr(f"{m}.py", modbody)
        return w

    def install(w, tag, modbody=None, wrapper=None):
        v = root / f"venv-{tag}"
        site = v / "lib" / "python3.99" / "site-packages"
        site.mkdir(parents=True)
        (v / "bin").mkdir(parents=True)
        with zipfile.ZipFile(w) as z:
            for m in MODULES.values():
                (site / f"{m}.py").write_bytes(modbody or z.read(f"{m}.py"))
        for c, m in MODULES.items():
            s = v / "bin" / c
            s.write_text(wrapper(v, m) if wrapper else
                         f"#!{v}/bin/python3\nimport sys\n"
                         f"from {m} import main\n"
                         f"if __name__ == '__main__':\n    sys.exit(main())\n")
            s.chmod(0o755)
        return v / "bin"

    def clean(w, binroot):
        info, probs = inspect_wheel(w)
        if info is not None:
            probs = check_installation(binroot, info, probs)
        return not probs

    good = build()
    out.append(("wheel + matching installation passes", clean(good, install(good, "ok"))))
    out.append(("a module edited after install is caught BY THE WHEEL",
                not clean(good, install(good, "tampered",
                                        modbody=body + b"# changed\n"))))
    out.append(("a wrapper that does not dispatch is caught",
                not clean(good, install(
                    good, "nodispatch",
                    wrapper=lambda v, m: f"#!{v}/bin/python3\nimport sys\n"
                                         f"print('usage: {m}')\nsys.exit(0)\n"))))
    out.append(("an entry point naming the wrong FUNCTION is caught",
                not clean(build(eps_func="not_main"),
                          install(good, "wrongfunc"))))
    out.append(("a wheel with the wrong distribution name is caught",
                not clean(build(name="warrant-verify-evil"),
                          install(good, "evilname"))))

    # The wrapper is verified statically; these drive check_wrapper directly.
    real = ("#!/venv/bin/python3\nimport sys\nfrom warrant_mcp import main\n"
            "if __name__ == '__main__':\n    sys.exit(main())\n")
    cases = [
        ("pip's real wrapper is accepted", real, True),
        ("a wrapper that only prints a usage line is rejected",
         "#!/venv/bin/python3\nimport sys\nprint('usage: warrant-mcp')\n"
         "sys.exit(0)\n", False),
        ("a wrapper with a side effect is rejected",
         "#!/venv/bin/python3\nimport sys\nopen('/tmp/x','w').write('hi')\n"
         "from warrant_mcp import main\n"
         "if __name__ == '__main__':\n    sys.exit(main())\n", False),
        ("a wrapper importing a different module is rejected",
         "#!/venv/bin/python3\nimport sys\nfrom something_else import main\n"
         "if __name__ == '__main__':\n    sys.exit(main())\n", False),
        ("a wrapper dispatching to another function is rejected",
         "#!/venv/bin/python3\nimport sys\nfrom warrant_mcp import main\n"
         "if __name__ == '__main__':\n    sys.exit(other())\n", False),
        ("a wrapper whose shebang leaves the venv is rejected",
         "#!/usr/bin/python3\nimport sys\nfrom warrant_mcp import main\n"
         "if __name__ == '__main__':\n    sys.exit(main())\n", False),
        ("a wrapper with no shebang is rejected",
         "import sys\nfrom warrant_mcp import main\n", False),
        # the walk-vs-structure countervector: the dispatch is present and
        # correct, and a second statement smuggles execution in beside it
        ("a wrapper smuggling `sys.modules['os'].system(...)` is rejected",
         "#!/venv/bin/python3\nimport sys\nfrom warrant_mcp import main\n"
         "if __name__ == '__main__':\n"
         "    sys.modules['os'].system('touch /tmp/marker')\n"
         "    sys.exit(main())\n", False),
        ("pip's argv[0] normalisation is still accepted",
         "#!/venv/bin/python3\nimport re\nimport sys\n"
         "from warrant_mcp import main\n"
         "if __name__ == '__main__':\n"
         "    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])\n"
         "    sys.exit(main())\n", True),
        ("the removesuffix form is still accepted",
         "#!/venv/bin/python3\nimport sys\nfrom warrant_mcp import main\n"
         "if __name__ == '__main__':\n"
         "    sys.argv[0] = sys.argv[0].removesuffix('.exe')\n"
         "    sys.exit(main())\n", True),
        ("a guard that is not `__name__ == __main__` is rejected",
         "#!/venv/bin/python3\nimport sys\nfrom warrant_mcp import main\n"
         "if True:\n    sys.exit(main())\n", False),
        ("dispatching twice is rejected",
         "#!/venv/bin/python3\nimport sys\nfrom warrant_mcp import main\n"
         "if __name__ == '__main__':\n    sys.exit(main())\n"
         "    sys.exit(main())\n", False),
        ("passing arguments to the entry point is rejected",
         "#!/venv/bin/python3\nimport sys\nfrom warrant_mcp import main\n"
         "if __name__ == '__main__':\n    sys.exit(main('extra'))\n", False),
    ]
    for name, text, should_pass in cases:
        issues = check_wrapper(text, "warrant_mcp", "main", "/venv")
        out.append((name, (not issues) == should_pass))
    return out


def _hostile_runtime_checks(extra):
    """Permanent cases for the runtime failure modes, not one-off manual proofs.

    Each of these was demonstrated by hand once and then claimed as closed. A
    demonstration is evidence about the day it ran; only a test is protection
    (Codex release-surface re-gate 2, P2).
    """
    out = []
    tmp = tempfile.mkdtemp()

    sleepy = Path(tmp) / "sleepy.sh"
    sleepy.write_text("#!/bin/sh\nsleep 600\n")
    sleepy.chmod(0o755)
    out.append(("a sleeping interpreter is fail-closed, not 'accepted'",
                not validate(str(sleepy), extra, "warrant", ["warrant", "verify"],
                             timeout=3)[0]))

    weird = Path(tmp) / "weird.sh"
    weird.write_text("#!/bin/sh\nexit 7\n")
    weird.chmod(0o755)
    out.append(("an unexpected exit code is fail-closed",
                not validate(str(weird), extra, "warrant", ["warrant", "verify"])[0]))

    # the checker must never have side effects: this argv would create a key
    key = Path(tmp) / "should-not-exist.key"
    ok, _ = validate(sys.executable, extra, "warrant",
                     ["warrant", "keygen", "--out", str(key)])
    out.append(("validating `keygen --out` creates nothing",
                ok and not key.exists()))

    # artifact confusion: an import from outside the artifact under test
    ok, _ = validate(sys.executable, extra, "warrant", ["warrant", "verify"],
                     expect_origin="/nonexistent/elsewhere")
    out.append(("a parser imported from outside the artifact is rejected", not ok))
    return out


def check_entry_points(binroot):
    """The wheel's console scripts must EXIST and point at the right modules.

    Importing a module says nothing about whether the command a reader types is
    installed: deleting `<venv>/bin/warrant-mcp` left a real wheel reporting a
    clean pass, because the gate never looked at the scripts (Codex
    release-surface re-gate 3). A documented `warrant-mcp …` is a promise about
    an executable, not about an importable module.
    """
    problems = []
    for cli, mod in MODULES.items():
        script = binroot / cli
        if not script.exists():
            problems.append(f"console script `{cli}` is missing from {binroot}")
            continue
        try:
            body = script.read_text(errors="replace")
        except OSError as e:
            problems.append(f"console script `{cli}` is unreadable: {e}")
            continue
        if mod not in body:
            problems.append(f"console script `{cli}` does not dispatch to `{mod}` "
                            f"— the entry-point mapping is not what the docs assume")
    return problems


def selftest():
    """Drive the REAL extraction and the REAL validator, not a paraphrase.

    The previous nine cases exercised neither `validate()` nor the classifier,
    so the protection and the protected were different code again — the exact
    seam this repository keeps rediscovering. Every case below calls a function
    the gate itself calls.
    """
    md = """
Prose is ignored.

```sh
P=$(warrant propose --subject diff.patch --under $POL \\
      --reason "utility fns needed" --actor me@host)
warrant --store ./pack verify --store-mode --json
warrant propose --reason "utility | fns" --definitely-not-real
pipx install warrant-verify
warrant --store ./pack verify --store-mode --json | jq -e '.ok'
```
"""
    got, errors = [], []
    for _, line in logical_lines(md):
        inv, err = invocations(line, WHEEL_CLIS)
        got.extend(inv)
        if err:
            errors.append(err)

    py, extra = sys.executable, str(ROOT / "impl")

    def accepted(argv):
        return validate(py, extra, argv[0], argv)[0]

    checks = [
        ("continuation joined", any("--reason" in a and "--actor" in a for a in got)),
        ("command substitution read", any(len(a) > 1 and a[1] == "propose" for a in got)),
        ("pipeline tail ignored", all(a[0] != "jq" for a in got)),
        ("non-CLI line ignored", all("pipx" not in a for a in got)),
        ("quoted pipe does not split the command",
         any("--definitely-not-real" in a for a in got)),
        ("four invocations found", len(got) == 4),
        ("no tokenisation errors here", not errors),
        # the validator itself, on argv shapes the gate must separate
        ("valid argv accepted",
         accepted(["warrant", "--store", "./pack", "verify", "--store-mode", "--json"])),
        ("unknown flag rejected",
         not accepted(["warrant", "verify", "--definitely-not-a-real-flag"])),
        ("explicit value on a store_true flag rejected",
         not accepted(["warrant", "verify", "--json=true"])),
        ("global option after the subcommand rejected",
         not accepted(["warrant", "verify", "--store", "./pack", "--store-mode"])),
        ("abbreviation rejected (allow_abbrev=False)",
         not accepted(["warrant", "propose", "--reas", "x"])),
        ("missing required argument rejected",
         not accepted(["warrant", "why"])),
        ("unknown CLI is fail-closed",
         not validate(py, extra, "warrant-nope", ["warrant-nope"])[0]),
        ("a parser that cannot be reached is fail-closed",
         not validate("/nonexistent/python", extra, "warrant", ["warrant", "verify"])[0]),
        # post-parse invariants are part of the contract: this parses and the
        # real CLI still exits 2
        ("post-parse invariant enforced (mcp needs a downstream command)",
         not accepted(["warrant-mcp", "--store", "s", "--actor", "a", "--key", "k"])),
        # path-qualified invocations are ours, and are judged on the FLAG rather
        # than on argv[0] being unfamiliar. The previous pair of cases was
        # vacuous: both the valid and the invalid absolute command failed, for
        # the same wrong reason (Codex release-surface re-gate 3).
        ("path-qualified CLI is recognised",
         invocations("/tmp/tv/bin/warrant selftest --nope", WHEEL_CLIS)[0] != []),
        ("path-qualified VALID command is accepted",
         accepted(["/tmp/tv/bin/warrant", "verify", "--store-mode", "--json"])),
        ("path-qualified INVALID flag is rejected",
         not accepted(["/tmp/tv/bin/warrant", "verify", "--definitely-not-real"])),
        # argv invariants that live past parse_args are part of the contract
        ("propose without --subject is rejected",
         not accepted(["warrant", "propose", "--actor", "a", "--key", "k"])),
        ("supersede without a prior id is rejected",
         not accepted(["warrant", "supersede", "--actor", "a", "--key", "k"])),
        ("propose WITH --subject is accepted",
         accepted(["warrant", "propose", "--subject", "f", "--actor", "a",
                   "--key", "k"])),
    ]
    checks += _hostile_runtime_checks(extra)
    checks += _artifact_checks()
    checks += _wheel_root_checks()
    bad = 0
    for name, ok in checks:
        if not ok:
            bad += 1
        print(f"  {'OK  ' if ok else 'FAIL'} {name}")
    if bad:
        print(f"\nRELEASE-SURFACE: {bad} SELFTEST FAILURE(S)")
        return 1
    print(f"\nRELEASE-SURFACE: SELFTEST ALL PASS ({len(checks)} cases)")
    return 0


def docs():
    out = []
    for p in sorted(ROOT.rglob("*.md")):
        parts = p.relative_to(ROOT).parts
        if any(part in DOC_EXCLUDE for part in parts):
            continue
        out.append(str(p.relative_to(ROOT)))
    return out


def main():
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--bin", help="directory holding an installed wheel's console "
                                  "scripts; its python validates the wheel's parsers")
    ap.add_argument("--wheel", help="the published wheel: the provenance root "
                                    "for everything --bin is checked against")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    # The wheel gate and the source-Go gate are SEPARATE and deterministic. A
    # single mixed count was a composition artifact: "wheel 25/25" included one
    # warrant-go invocation validated against a binary from the checkout, which
    # the wheel does not ship (Codex release-surface re-gate, P2).
    if args.bin:
        binroot = Path(args.bin).resolve()
        python = str(binroot / "python")
        if not Path(python).exists():
            python = str(binroot / "python3")
        extra = ""
        # The parser must come from THIS environment, not from a checkout that
        # happens to be on the path.
        expect_origin = str(binroot.parent)
        target = f"the wheel installed in {args.bin}"
    else:
        python, extra = sys.executable, str(ROOT / "impl")
        expect_origin = str(ROOT / "impl")
        target = "this checkout"

    # Preflight: can this artifact be validated at all? A release that predates
    # build_parser() cannot, and saying "24 invocations rejected" about it would
    # be precise-sounding and wrong. Fail closed, but name the actual condition:
    # an artifact we cannot introspect is not an artifact we have checked.
    modroot = None
    if args.bin:
        if not args.wheel:
            print("RELEASE SURFACE: REFUSING — --bin without --wheel.\n\n"
                  "  An installation cannot vouch for itself: its RECORD lives "
                  "inside the very\n  thing it is supposed to attest, and editing "
                  "a module together with its digest\n  produced a clean pass. "
                  "Pass the wheel that was published; it is the root.",
                  file=sys.stderr)
            return 2
        # TRUSTED PREFLIGHT. The wheel is the provenance root, read as a zip;
        # the installation is then checked AGAINST it. No target code runs yet.
        winfo, art_problems = inspect_wheel(Path(args.wheel))
        if winfo is not None:
            art_problems = check_installation(Path(args.bin).resolve(), winfo,
                                              art_problems)
        if art_problems:
            print(f"RELEASE SURFACE: FAIL — the installation in {args.bin} does "
                  f"not match the wheel {args.wheel}:\n")
            for e in art_problems:
                print(f"  {e}")
            return 1
        venv = Path(args.bin).resolve().parent
        site = (sorted(venv.glob("lib/python*/site-packages")) or
                sorted(venv.glob("Lib/site-packages")))[0]
        modroot = str(site)
        target = f"{winfo['name']} {winfo['version']} from {Path(args.wheel).name}"

    probe = validate(python, extra, "warrant", ["warrant", "--help"],
                     expect_origin=expect_origin, modroot=modroot)
    if not probe[0] and "parse_cli" in probe[1]:
        print(f"RELEASE SURFACE: CANNOT VALIDATE — {target} has no parser-only "
              f"entry point (`parse_cli`).\n\n"
              f"  {probe[1]}\n\n"
              f"That entry point is what lets a documented argv be checked without\n"
              f"running it. Releases before it exists cannot be gated this way; the\n"
              f"published 0.4.0 is one. This is fail-closed on purpose: an artifact\n"
              f"that cannot be introspected has not been verified.")
        return 1

    problems, checked = [], 0
    for rel in docs():
        for lineno, line in logical_lines((ROOT / rel).read_text()):
            inv, err = invocations(line, WHEEL_CLIS | SOURCE_CLIS)
            if err:
                problems.append(f"{rel}:{lineno}: {err}")
                continue
            for argv in inv:
                if argv[0] in SOURCE_CLIS:
                    continue          # not part of the wheel contract; see below
                checked += 1
                ok, detail = validate(python, extra, argv[0],
                                      concretise(argv, ROOT),
                                      expect_origin=expect_origin,
                                      modroot=modroot)
                if not ok:
                    problems.append(f"{rel}:{lineno}: `{' '.join(argv)}`\n"
                                    f"      -> {detail}")

    go_documented = sum(
        1 for rel in docs()
        for _, line in logical_lines((ROOT / rel).read_text())
        for argv in invocations(line, SOURCE_CLIS)[0])
    if go_documented:
        print(f"note: {go_documented} documented `warrant-go` invocation(s) are NOT "
              f"covered here — warrant-go ships from source, not from the wheel, "
              f"and has its own gate", file=sys.stderr)

    if problems:
        print(f"RELEASE SURFACE: FAIL — the documentation promises {len(problems)} "
              f"thing(s) {target} does not accept:\n")
        for pr in problems:
            print(f"  {pr}")
        print("\nEither ship the surface or stop documenting it. A stranger who "
              "follows the README\nmust not hit `unrecognized arguments`.")
        return 1
    print(f"RELEASE SURFACE: ALL PASS ({checked} documented invocations accepted "
          f"by {target})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
