#!/usr/bin/env python3
"""One command a reviewer can run on an agent's change, and one artifact to read.

The parts already exist — a policy language that compiles to a re-executable
`ski@v1` term, a record format that pins the policy bytes, a verifier that
re-runs the reason. What did not exist is the thing a reviewer actually wants:

    what changed, who proposed it, which policy was in force, what was checked,
    which reason can be re-run, and what exactly would flip the verdict.

The last one is the point. A gate that says "rejected" and stops is a wall; a
gate that says which fact is one step from the boundary is a review.

    python3 tools/gate.py --base origin/master --policy .warrant/gate.wpl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "impl"))

import policy_lang as WPL           # noqa: E402
import warrant as W                 # noqa: E402

AGENT_TRAILERS = ("Co-Authored-By: Claude", "Co-Authored-By: Codex",
                  "Co-Authored-By: GPT", "Co-Authored-By: Gemini",
                  "Generated with", "Claude-Session:")


def git(*arguments: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *arguments],
                          capture_output=True, text=True, check=True).stdout


def facts_from_change(base: str, head: str) -> dict:
    """Measured where the facts are: WPL refuses arithmetic on purpose, so the
    counting happens here and the results are pinned into the policy."""
    numstat = git("diff", "--numstat", f"{base}...{head}").strip().splitlines()
    added = removed = 0
    paths = []
    for line in numstat:
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        plus, minus, path = parts
        added += int(plus) if plus.isdigit() else 0
        removed += int(minus) if minus.isdigit() else 0
        paths.append(path)

    log = git("log", "--format=%B", f"{base}..{head}")
    return {
        "files_changed": len(paths),
        "lines_added": added,
        "lines_removed": removed,
        "touches_ci": any(p.startswith(".github/workflows/") for p in paths),
        "touches_deps": any(p.endswith(("Cargo.lock", "uv.lock", "poetry.lock",
                                        "package-lock.json", "requirements.txt"))
                            for p in paths),
        "touches_tests": any("test" in p for p in paths),
        "proposed_by_agent": any(marker in log for marker in AGENT_TRAILERS),
    }, paths


def render_policy(template: Path, facts: dict) -> str:
    """The template declares the rule; the measured facts are substituted in.

    A fact the template does not declare is refused rather than ignored — a
    policy silently evaluated against facts it never mentioned is the shape of
    check this project exists to distrust."""
    source = template.read_text()
    rendered, seen = [], set()
    for line in source.splitlines():
        if line.startswith("fact ") and "= {{" in line:
            name = line.split()[1].rstrip(":")
            if name not in facts:
                raise SystemExit(f"{template}: declares fact {name!r}, which this "
                                 "gate does not measure")
            value = facts[name]
            literal = ("true" if value else "false") if isinstance(value, bool) else (
                str(value) if isinstance(value, int) else json.dumps(value))
            rendered.append(line.split("= {{")[0] + "= " + literal)
            seen.add(name)
        else:
            rendered.append(line)
    unused = sorted(set(facts) - seen)
    return "\n".join(rendered) + "\n", unused


def _verdict_with(source: str, facts: dict, name: str, value) -> bool | None:
    probe = dict(facts)
    probe[name] = value
    rendered, _ = render_policy_from_facts(source, probe)
    try:
        return WPL.evaluate(WPL.parse(rendered))
    except Exception:
        return None


def flip_analysis(source: str, facts: dict, verdict: bool) -> list[str]:
    """What would change the answer, fact by fact — and for a number, by how much.

    Recomputed with the reference interpreter rather than reasoned about. For an
    integer the boundary is found by bisection instead of by probing a few
    deltas, because "somewhere under 510" is not review information and "at 300"
    is. This is the part a reviewer reads first: it says how close the change is
    to the line, and which line.
    """
    findings = []
    for name, value in sorted(facts.items()):
        if isinstance(value, bool):
            if _verdict_with(source, facts, name, not value) is (not verdict):
                findings.append(f"`{name}`: {value} → {not value} flips it")
            continue
        if not isinstance(value, int):
            continue
        low, high = 0, max(value * 4, value + 1000)
        if _verdict_with(source, facts, name, low) is verdict and \
           _verdict_with(source, facts, name, high) is verdict:
            continue                       # no boundary in reach either way
        # bisect towards the nearest value that changes the answer
        for lo, hi in ((low, value), (value, high)):
            if _verdict_with(source, facts, name, lo) is _verdict_with(source, facts, name, hi):
                continue
            a, b = lo, hi
            while b - a > 1:
                mid = (a + b) // 2
                if _verdict_with(source, facts, name, mid) is _verdict_with(source, facts, name, a):
                    a = mid
                else:
                    b = mid
            edge = a if _verdict_with(source, facts, name, a) is (not verdict) else b
            direction = "down to" if edge < value else "up to"
            findings.append(f"`{name}`: {value} → {direction} {edge} flips it")
    return findings


def render_policy_from_facts(rendered_source: str, facts: dict) -> tuple[str, list]:
    """Re-render an already-rendered policy with different fact values."""
    out = []
    for line in rendered_source.splitlines():
        if line.startswith("fact "):
            name = line.split()[1].rstrip(":")
            if name in facts:
                value = facts[name]
                literal = ("true" if value else "false") if isinstance(value, bool) else (
                    str(value) if isinstance(value, int) else json.dumps(value))
                out.append(line.split("=")[0] + "= " + literal)
                continue
        out.append(line)
    return "\n".join(out) + "\n", []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="origin/master")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--policy", default=".warrant/gate.wpl")
    parser.add_argument("--store", default=".warrant/store",
                        help="where the gate writes its own check blobs; not the repository's record store, which belongs to the repository")
    parser.add_argument("--actor", default="gate@local")
    parser.add_argument("--key", help="Ed25519 seed; omit to check without filing")
    parser.add_argument("--out", default="gate-report.md")
    arguments = parser.parse_args()

    template = ROOT / arguments.policy
    if not template.is_file():
        raise SystemExit(f"no policy at {arguments.policy}; this gate has no opinion "
                         "of its own and refuses to invent one")

    facts, paths = facts_from_change(arguments.base, arguments.head)
    source, unused = render_policy(template, facts)
    program = WPL.parse(source)
    verdict = WPL.evaluate(program)
    collected, collecting = [], False
    for line in source.splitlines():
        if line.startswith("check"):
            collecting = True
            collected.append(line.split("check", 1)[1].strip())
        elif collecting and line[:1].isspace() and line.strip():
            collected.append(line.strip())
        elif collecting:
            break
    formula = " ".join(collected) or "see the policy"

    store_path = ROOT / arguments.store
    if not (store_path / "blobs").is_dir():
        # The gate keeps its own store so a check it compiles never lands in the
        # repository's record store, which belongs to the repository.
        (store_path / "blobs").mkdir(parents=True, exist_ok=True)
        (store_path / "records").mkdir(parents=True, exist_ok=True)
    store = W.Store(store_path)
    compiled = WPL.compile_source(source, put=store.put_blob, name=template.name)
    doc, check_hash = compiled.doc, compiled.blob
    if compiled.result != verdict:
        raise SystemExit("the compiled term disagrees with the reference "
                         "interpreter — refusing to report either")

    diff_bytes = git("diff", f"{arguments.base}...{arguments.head}").encode()
    subject = hashlib.sha256(diff_bytes).hexdigest()
    policy_hash = store.put_blob(source.encode())
    flips = flip_analysis(source, facts, verdict)

    report = [
        f"# Gate report — {'ACCEPT' if verdict else 'REJECT'}",
        "",
        f"Change `{arguments.base}...{arguments.head}`, {len(paths)} file(s), "
        f"+{facts['lines_added']}/-{facts['lines_removed']}.",
        "",
        "| | |", "| --- | --- |",
        f"| what changed | `{subject[:16]}…` — sha256 of the diff |",
        f"| who proposed it | {'an agent (commit trailers)' if facts['proposed_by_agent'] else 'a human, by the same evidence'} |",
        f"| policy in force | `{policy_hash[:16]}…` — the bytes of `{arguments.policy}`, pinned |",
        f"| what was checked | `{formula}` |",
        f"| reason you can re-run | `warrant --store {arguments.store} check {check_hash[:16]}…` |",
        f"| cost of re-running it | {doc['atp']:,} ATP, fixed in the check |",
        "",
        "## The facts it was decided on",
        "", "| fact | value |", "| --- | --- |",
    ]
    for name, value in sorted(facts.items()):
        report.append(f"| `{name}` | `{value}` |")
    report += ["", "## What would flip this verdict", ""]
    report += [f"- {line}" for line in flips] or ["- nothing within the probed range"]
    if unused:
        report += ["", f"Measured but not used by this policy: {', '.join(unused)}."]
    report += [
        "", "## What this does not say", "",
        "It does not say the change is correct, safe, or wanted. It says a stated "
        "rule was applied to measured facts, that the rule's bytes are pinned, and "
        "that anyone can re-run the reason and get the same answer.", ""]

    Path(ROOT / arguments.out).write_text("\n".join(report))
    print("\n".join(report[:14]))
    print(f"\nwritten: {arguments.out}")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
