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


# `<wid>` is a placeholder, not a redirect. Mask those before splitting on shell
# metacharacters, or the `>` inside one truncates the command -- which showed up
# as invented "missing required argument" failures against EVIDENCE-PACK.md.
ANGLE_PLACEHOLDER = re.compile(r"<[A-Za-z0-9_.:-]*>")
_MASK = "\x00PLACEHOLDER\x00"


def invocations(logical_line, known):
    """Every command in one logical line whose argv[0] is a CLI we own."""
    found = []
    masked = []

    def mask(m):
        masked.append(m.group(0))
        return f"{_MASK}{len(masked) - 1}{_MASK}"

    logical_line = ANGLE_PLACEHOLDER.sub(mask, logical_line)

    def unmask(tok):
        return re.sub(rf"{_MASK}(\d+){_MASK}",
                      lambda m: masked[int(m.group(1))], tok)

    for segment in SEGMENT_SPLIT.split(logical_line):
        segment = segment.strip()
        if not segment:
            continue
        # drop a leading `VAR=` assignment: `P=$(warrant …)` leaves `warrant …`
        segment = re.sub(r"^\w+=", "", segment).strip()
        try:
            argv = shlex.split(segment, comments=True)
        except ValueError:
            continue                      # unbalanced quotes: not a command
        argv = [unmask(a) for a in argv]
        if argv and argv[0] in known:
            found.append(argv)
    return found


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


def exact_flags(help_output):
    """Every option string the parser actually advertises."""
    return set(re.findall(r"(?<![\w-])(--?[A-Za-z0-9][A-Za-z0-9-]*)", help_output))


def abbreviations(argv, help_output):
    """Documented flags that only parse because argparse expands abbreviations.

    `--reas` works today: argparse's allow_abbrev turns it into `--reason`, so a
    dry-parse accepts it and the flag looks supported. It is still the wrong
    thing to publish. The day someone adds `--reassign`, every document using
    `--reas` breaks, and the breakage lands on readers rather than on CI. So the
    contract is the flag's REAL name, and an abbreviation is a finding even
    though the parser tolerates it.
    """
    known = exact_flags(help_output)
    if not known:
        return []
    out = []
    for tok in argv[1:]:
        if not tok.startswith("-") or tok == "--":
            continue
        flag = tok.split("=")[0]
        if flag in known:
            continue
        if any(k.startswith(flag) for k in known if k.startswith("--")):
            out.append(flag)
    return out


def help_of(runner, cli, sub=None, cache={}):
    """`--help` for a CLI, and for a subcommand when there is one."""
    out = ""
    for cmd in ([cli], [cli, sub] if sub else None):
        if not cmd:
            continue
        key = tuple(cmd)
        if key not in cache:
            try:
                r = subprocess.run(runner(cmd + ["--help"]), capture_output=True,
                                   text=True, timeout=60,
                                   env={**os.environ, "COLUMNS": "200"})
                cache[key] = r.stdout + r.stderr
            except (OSError, subprocess.TimeoutExpired):
                cache[key] = ""
        out += cache[key]
    return 0, out


def validate(runner, argv, timeout=20):
    """(ok, detail) — is this argv ACCEPTED by the real entry point?

    Deliberately not a help-text search. Presence of `--json` in help says
    nothing about `--json=true` (a store_true flag rejects an explicit value) or
    about `--store` appearing after the subcommand instead of before it. Only
    the parser knows, so the parser is asked.

    A command that parses and then fails on a missing file has still honoured
    the documented surface; only argparse's usage errors count against it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        try:
            p = subprocess.run(runner(argv), cwd=tmp, capture_output=True,
                               text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                               env={**os.environ, "COLUMNS": "200"})
        except subprocess.TimeoutExpired:
            return True, "timed out after parsing (accepted)"
        except OSError as e:
            return False, f"could not run: {e}"
        if p.returncode == 2:
            err = (p.stderr or p.stdout).lower()
            for marker in ARGPARSE_ERRORS:
                if marker in err:
                    line = next((l for l in (p.stderr or p.stdout).splitlines()
                                 if marker in l.lower()), marker)
                    return False, line.strip()
        return True, f"exit {p.returncode}"


def selftest():
    """Drive the real extraction and validation, not a paraphrase of them."""
    md = """
Prose is ignored.

```sh
P=$(warrant propose --subject diff.patch --under $POL \\
      --reason "utility fns needed" --actor me@host)
warrant --store ./pack verify --store-mode --json
warrant verify --json=true
pipx install warrant-verify
warrant --store ./pack verify --store-mode --json | jq -e '.ok'
```
"""
    got = []
    for _, line in logical_lines(md):
        got.extend(invocations(line, WHEEL_CLIS))

    checks = [
        ("continuation joined", any("--reason" in a and "--actor" in a for a in got)),
        ("command substitution read", any(a[1] == "propose" for a in got)),
        ("pipeline tail ignored", all(a[0] != "jq" for a in got)),
        ("non-CLI line ignored", all("pipx" not in a for a in got)),
        ("four invocations found", len(got) == 4),
    ]
    # placeholders become parseable values, flags survive untouched
    conc = concretise(["warrant", "why", "<hash>", "--json"], ".")
    checks.append(("placeholder concretised", conc[2] == "0" * 64))
    checks.append(("flag preserved verbatim", conc[3] == "--json"))
    # the classifier must distinguish argv rejection from runtime failure
    checks.append(("usage error detected",
                   any(m in "error: unrecognized arguments: --nope"
                       for m in ARGPARSE_ERRORS)))
    checks.append(("runtime failure is not a usage error",
                   not any(m in "error: no such store: ./pack"
                           for m in ARGPARSE_ERRORS)))

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
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", help="directory holding the installed console scripts "
                                  "(default: run the checkout via python3 impl/)")
    ap.add_argument("--selftest", action="store_true",
                    help="run the extraction/validation rules' own matrix and exit")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    go_bin = ROOT / "impl-go" / "warrant-go"
    known = set(WHEEL_CLIS)
    if go_bin.exists():
        known |= SOURCE_CLIS

    def runner(argv):
        cli = argv[0]
        if cli in SOURCE_CLIS:
            return [str(go_bin)] + argv[1:]
        if args.bin:
            return [str(Path(args.bin).resolve() / cli)] + argv[1:]
        module = {"warrant": "warrant.py", "warrant-mcp": "warrant_mcp.py",
                  "warrant-anchor": "warrant_anchor.py"}[cli]
        return [sys.executable, str(ROOT / "impl" / module)] + argv[1:]

    problems, checked = [], 0
    for rel in docs():
        for lineno, line in logical_lines((ROOT / rel).read_text()):
            for argv in invocations(line, known):
                checked += 1
                ok, detail = validate(runner, concretise(argv, ROOT))
                if not ok:
                    problems.append(f"{rel}:{lineno}: `{' '.join(argv)}`\n"
                                    f"      -> {detail}")
                    continue
                # Parsed -- but did it parse for the right reason? A flag that
                # only works as an abbreviation is a documented surface that a
                # future option name can take away.
                sub = next((a for a in argv[1:] if not a.startswith("-")), None)
                _, h = help_of(runner, argv[0], sub)
                for abbrev in abbreviations(argv, h):
                    problems.append(
                        f"{rel}:{lineno}: `{' '.join(argv)}`\n"
                        f"      -> `{abbrev}` is not a real flag; it parses only "
                        f"as an argparse abbreviation, and a future option name "
                        f"would break every reader following this line")

    target = args.bin or "this checkout"
    if not go_bin.exists():
        print("note: impl-go/warrant-go is not built, so documented `warrant-go` "
              "invocations are NOT checked in this run", file=sys.stderr)
    if problems:
        print(f"RELEASE SURFACE: FAIL — the documentation promises {len(problems)} "
              f"invocation(s) {target} does not accept:\n")
        for p in problems:
            print(f"  {p}")
        print("\nEither ship the surface or stop documenting it. A stranger who "
              "follows the README\nmust not hit `unrecognized arguments`.")
        return 1
    print(f"RELEASE SURFACE: ALL PASS ({checked} documented invocations accepted "
          f"by {target})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
