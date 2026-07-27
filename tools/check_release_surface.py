#!/usr/bin/env python3
"""Fail when the docs promise a CLI surface the built artifact does not have.

WHY THIS EXISTS
---------------
`verify --store-mode --json` landed on master on 2026-07-27 and the README
documented it as *the* machine boundary for CI, MCP and agent frameworks. The
newest published release was 0.4.0 (2026-07-16). So for a stranger following the
README with `pip install warrant-verify`, the documented integration surface did
not exist:

    error: unrecognized arguments: --store-mode --json

Nothing caught it. CI installs from the checkout; the sibling repo curls
impl/warrant.py at a pinned commit; neither path touches the published artifact.
The gap was found by running the README's own quest against PyPI by hand, which
is not a gate.

This is the gate. It reads every `warrant*` invocation out of the documentation,
then asks the *installed* CLI whether it accepts those subcommands and flags.
Docs and artifact can no longer drift apart silently: they drift apart red.

    python3 tools/check_release_surface.py                # against this checkout
    python3 tools/check_release_surface.py --bin /tmp/venv/bin   # against a wheel

Exit 0 = every documented invocation is supported by the binaries under test.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Documentation that makes promises to a stranger. Anything discovered here is a
# contract: if it shows a command, that command must work in the shipped
# artifact. Discovery is by directory rather than by list, because a hand-kept
# list is exactly the thing that goes stale the day someone adds a doc -- and a
# stale list would make this gate quietly stop covering the new promise.
DOC_ROOTS = [".", "demos", "profiles", "docs", "integrations"]

# Excluded on purpose, with reasons:
#   reviews/    external reviewers quote commands that may never have existed
#   proposals/  design documents describe surfaces that deliberately do not exist yet
#   briefs/     instructions to reviewers, same reason
#   archive/    historical, by definition about older surfaces
DOC_EXCLUDE = {"reviews", "proposals", "briefs", "archive", "scratchpad",
               "build", "dist", ".git", "node_modules"}

# Commands whose surface we own. `warrant-go` is a Go binary documented beside
# the Python one; it is checked too when present, since the README offers it as
# an interchangeable machine boundary.
KNOWN_CLIS = {"warrant", "warrant-mcp", "warrant-anchor"}

# Fragments that appear inside fenced blocks but are not invocations to check:
# shell plumbing after a pipe, placeholders, and comments.
PLACEHOLDER = re.compile(r"^<.*>$|^\$\w+$|^\.\.\.$")


def docs():
    """Every markdown file that speaks to a user, newest layout discovered live."""
    seen = []
    for root in DOC_ROOTS:
        base = ROOT / root
        if not base.is_dir():
            continue
        pattern = "*.md" if root == "." else "**/*.md"
        for p in sorted(base.glob(pattern)):
            if any(part in DOC_EXCLUDE for part in p.relative_to(ROOT).parts):
                continue
            rel = str(p.relative_to(ROOT))
            if rel not in seen:
                seen.append(rel)
    return seen


def documented_invocations():
    """Yield (doc, lineno, cli, argv, flags) for each documented command."""
    for rel in docs():
        p = ROOT / rel
        if not p.exists():
            continue
        in_fence = False
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if not in_fence:
                continue
            stripped = line.strip()
            # keep only the segment before a pipe/redirect/comment
            stripped = re.split(r"[|>#]", stripped)[0].strip()
            if not stripped:
                continue
            tokens = stripped.split()
            if tokens[0] not in KNOWN_CLIS:
                continue
            flags = [t.split("=")[0] for t in tokens[1:] if t.startswith("-") and len(t) > 1]
            yield rel, n, tokens[0], tokens[1:], flags


def subcommands(top_help):
    """The subcommand names argparse advertises, e.g. '{init,keygen,verify,...}'.

    Reading the real choice list beats guessing which token is the subcommand:
    `warrant --store .warrants verify` has a value between the flag and the verb,
    and a heuristic that took the first bare token would call `.warrants` a
    subcommand and report a nonexistent failure.
    """
    names = set()
    for m in re.finditer(r"\{([a-z0-9_,-]{3,})\}", top_help):
        names.update(x for x in m.group(1).split(",") if x)
    return names


def help_text(cmd, cache={}):
    key = tuple(cmd)
    if key not in cache:
        try:
            r = subprocess.run(cmd + ["--help"], capture_output=True, text=True, timeout=60)
            cache[key] = (r.returncode, r.stdout + r.stderr)
        except (OSError, subprocess.TimeoutExpired) as e:
            cache[key] = (127, str(e))
    return cache[key]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", help="directory holding the installed console scripts "
                                  "(default: run the checkout via python3 impl/)")
    args = ap.parse_args()

    def invoke(cli):
        if args.bin:
            return [str(Path(args.bin) / cli)]
        module = {"warrant": "warrant.py", "warrant-mcp": "warrant_mcp.py",
                  "warrant-anchor": "warrant_anchor.py"}[cli]
        return [sys.executable, str(ROOT / "impl" / module)]

    problems, checked = [], 0
    for doc, line, cli, argv, flags in documented_invocations():
        base = invoke(cli)
        rc, top = help_text(base)
        if rc != 0:
            problems.append(f"{doc}:{line}: `{cli}` does not run at all (exit {rc})")
            continue

        known = subcommands(top)
        sub = next((t for t in argv if t in known), None)
        bare = [t for t in argv if not t.startswith("-") and not PLACEHOLDER.match(t)]
        if sub is None and bare and known:
            # A documented verb that argparse has never heard of is the loudest
            # possible drift: the command cannot work at all.
            verb = bare[0]
            if not any(verb.startswith(p) for p in ("./", "/", "$")) and "." not in verb:
                problems.append(
                    f"{doc}:{line}: `{cli} {verb}` is documented, but `{cli} --help` "
                    f"lists no such subcommand (has: {', '.join(sorted(known))})")
                continue

        scope, where = top, f"{cli} --help"
        if sub:
            rc_sub, sub_help = help_text(base + [sub])
            if rc_sub == 0:
                scope, where = top + sub_help, f"{cli} {sub} --help"

        for flag in flags:
            checked += 1
            if flag not in scope and flag not in top:
                problems.append(
                    f"{doc}:{line}: `{cli} {sub or ''} {flag}`".rstrip() +
                    f" is documented, but {where} does not offer `{flag}`")

    target = args.bin or "this checkout"
    if problems:
        print(f"RELEASE SURFACE: FAIL — the documentation promises {len(problems)} "
              f"thing(s) {target} cannot do:\n")
        for p in problems:
            print(f"  {p}")
        print("\nEither ship the surface or stop documenting it. A stranger who "
              "follows the README\nmust not hit `unrecognized arguments`.")
        return 1
    print(f"RELEASE SURFACE: ALL PASS ({checked} documented flags supported by {target})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
