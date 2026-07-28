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
"""
import argparse
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
extra = sys.argv[1]
if extra:
    sys.path.insert(0, extra)
mod = __import__(sys.argv[2])
origin = getattr(mod, "__file__", "") or "?"
sys.stderr.write("MODULE-ORIGIN " + origin + "\\n")
if sys.argv[3] == "dist":
    # Which installed distribution OWNS this file? A directory match is not
    # ownership: an empty venv with a .pth and three hand-written modules
    # satisfied it (Codex release-surface re-gate 3). Ask the metadata.
    try:
        from importlib.metadata import distributions
        import os
        owner = ""
        want = os.path.realpath(origin)
        for d in distributions():
            for f in (d.files or []):
                try:
                    if os.path.realpath(str(d.locate_file(f))) == want:
                        owner = (d.metadata["Name"] or "") + " " + (d.version or "")
                        break
                except Exception:
                    pass
            if owner:
                break
        sys.stderr.write("MODULE-DIST " + (owner or "<none>") + "\\n")
    except Exception as e:
        sys.stderr.write("MODULE-DIST <error: " + str(e) + ">\\n")
if not hasattr(mod, "parse_cli"):
    raise SystemExit(3)
argv = sys.argv[4:]
try:
    mod.parse_cli(argv)
except SystemExit as e:
    raise SystemExit(2 if e.code else 0)
raise SystemExit(0)
"""

DIST_NAME = "warrant-verify"


def validate(python, extra_path, cli, argv, timeout=30, expect_origin=None,
             want_dist=False):
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
    cmd = ([python, "-I", "-c", PARSE_SNIPPET, extra_path or "", mod,
            "dist" if want_dist else "nodist"] + argv[1:])
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
    if want_dist and not dist.startswith(DIST_NAME):
        return False, (f"the parser at {origin} is not owned by an installed "
                       f"`{DIST_NAME}` distribution (owner: {dist or '<unknown>'}) "
                       f"— this is not the artifact it claims to be")
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
    if args.bin:
        ep_problems = check_entry_points(Path(args.bin).resolve())
        if ep_problems:
            print(f"RELEASE SURFACE: FAIL — {target} does not install the commands "
                  f"the documentation names:\n")
            for e in ep_problems:
                print(f"  {e}")
            return 1

    probe = validate(python, extra, "warrant", ["warrant", "--help"],
                     expect_origin=expect_origin, want_dist=bool(args.bin))
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
                                      want_dist=bool(args.bin))
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
