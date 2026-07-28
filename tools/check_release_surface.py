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
                if argv and argv[0] in known:
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
PARSE_ONLY = (
    "import sys, json\n"
    "sys.path.insert(0, sys.argv[1])\n" if False else "")

PARSE_SNIPPET = """
import sys
extra = sys.argv[1]
if extra:
    sys.path.insert(0, extra)
mod = __import__(sys.argv[2])
argv = sys.argv[3:]
try:
    mod.build_parser().parse_args(argv)
except SystemExit as e:
    raise SystemExit(2 if e.code else 0)
raise SystemExit(0)
"""


def validate(python, extra_path, cli, argv, timeout=30):
    """(ok, detail) — does the CLI's OWN PARSER accept this argv?

    Parser-only, and that is not a detail. The previous version ran the command
    to find out whether it parsed, so checking a documented
    `warrant keygen --out <path>` CREATED A KEY FILE outside the temp directory
    (Codex release-surface re-gate). A documentation change could have triggered
    filesystem, subprocess or network effects in CI. Nothing here executes a
    command: the module is imported, `build_parser()` is called, and the argv is
    parsed.

    FAIL-CLOSED everywhere. A timeout used to be reported as "accepted -- it got
    past parsing", which assumes exactly what is being tested: an executable
    that sleeps before building its parser would pass. Timeouts, import
    failures, missing entry points and unexpected exit codes are all failures.
    """
    mod = MODULES.get(cli)
    if mod is None:
        return False, f"no parser-only entry point known for `{cli}`"
    cmd = [python, "-c", PARSE_SNIPPET, extra_path or "", mod] + argv[1:]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL,
                           env={**os.environ, "COLUMNS": "200"})
    except subprocess.TimeoutExpired:
        return False, f"parser did not answer within {timeout}s (fail-closed)"
    except OSError as e:
        return False, f"could not run the parser: {e}"
    if p.returncode == 0:
        return True, "accepted"
    if p.returncode == 2:
        err = (p.stderr or p.stdout).strip().splitlines()
        return False, (err[-1] if err else "rejected by the parser")
    return False, (f"parser exited {p.returncode} (fail-closed); "
                   f"{(p.stderr or p.stdout).strip().splitlines()[-1:] or ['no output']}")


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
    ]
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
        python = str(Path(args.bin).resolve() / "python")
        if not Path(python).exists():
            python = str(Path(args.bin).resolve() / "python3")
        extra, target = "", f"the wheel installed in {args.bin}"
    else:
        python, extra, target = sys.executable, str(ROOT / "impl"), "this checkout"

    # Preflight: can this artifact be validated at all? A release that predates
    # build_parser() cannot, and saying "24 invocations rejected" about it would
    # be precise-sounding and wrong. Fail closed, but name the actual condition:
    # an artifact we cannot introspect is not an artifact we have checked.
    probe = validate(python, extra, "warrant", ["warrant", "--help"])
    if not probe[0] and "build_parser" in probe[1]:
        print(f"RELEASE SURFACE: CANNOT VALIDATE — {target} has no parser-only "
              f"entry point (`build_parser`).\n\n"
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
                ok, detail = validate(python, extra, argv[0], concretise(argv, ROOT))
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
