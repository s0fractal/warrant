#!/usr/bin/env python3
"""One command a reviewer can run on an agent's change, and one artifact to read.

The parts already existed — a policy language that compiles to a re-executable
`ski@v1` term, a record format that pins the policy bytes, a verifier that
re-runs the reason. What did not exist is the thing a reviewer actually opens:

    what changed, who proposed it, which policy was in force, what was checked,
    which reason can be re-run, and what exactly would flip the verdict.

The last one is the point. A gate that says "rejected" and stops is a wall; a
gate that says which fact is one step from the boundary is a review.

    python3 tools/gate.py --base origin/master

Exit status is 0 for accept and 1 for reject. Whether that blocks a merge is a
policy decision for whoever installs it, and this repository deliberately does
not: the report is posted and the merge is left to people. A gate that hijacks
merges on its first day gets switched off on its second.

TRUST BOUNDARY, which is not optional
-------------------------------------
This program, the policy it reads and the implementation it imports must come
from a revision the change under review cannot edit. Run it from the proposed
change and the change can rewrite its own rule into a tautology and award itself
an ACCEPT — reproduced, and now guarded by `tests/gate_isolation.py`. The head
revision is *data*: it is diffed, never executed, and never consulted for the
rule. `--policy-from` names the revision the rule is read from and appears in the
report, so a reader can see which bytes decided.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "impl"))

import policy_lang as WPL           # noqa: E402
import warrant as W                 # noqa: E402

AGENT_TRAILERS = ("Co-Authored-By: Claude", "Co-Authored-By: Codex",
                  "Co-Authored-By: GPT", "Co-Authored-By: Gemini",
                  "Generated with", "Claude-Session:")
LOCKFILES = ("Cargo.lock", "uv.lock", "poetry.lock", "package-lock.json",
             "requirements.txt")
SAFE_REV = re.compile(r"^[A-Za-z0-9_./\-~^@{}]+$")
FACT = "fact "
SAFE_PATH = re.compile(r"^[A-Za-z0-9_./-]+$")


def git(*arguments: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *arguments],
                          capture_output=True, text=True, check=True).stdout


def resolve(rev: str) -> str:
    """Turn a caller-supplied revision into a commit id, or refuse it.

    The revision arrives from a command line and is then handed to git, so it is
    checked before it can be read as an option: a value starting with `-` is an
    option, not a revision, whatever it was meant to be."""
    if rev.startswith("-") or not SAFE_REV.match(rev):
        raise SystemExit(f"refusing {rev!r} as a revision")
    try:
        return git("rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}").strip()
    except subprocess.CalledProcessError:
        raise SystemExit(f"{rev!r} does not name a commit in this repository")


def literal(value) -> str:
    """A fact value as WPL source."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(value)


def measure(base: str, head: str) -> tuple[dict, list[str]]:
    """Facts, measured where the facts are.

    WPL refuses arithmetic on purpose — every operand must be a literal or a
    pinned fact, so the verifier re-executes each step instead of trusting a
    number a compiler worked out. The counting therefore happens here."""
    added = removed = 0
    paths: list[str] = []
    for line in git("diff", "--numstat", f"{base}...{head}").splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        plus, minus, path = parts
        added += int(plus) if plus.isdigit() else 0
        removed += int(minus) if minus.isdigit() else 0
        paths.append(path)

    log = git("log", "--format=%B", f"{base}..{head}")
    facts = {
        "files_changed": len(paths),
        "lines_added": added,
        "lines_removed": removed,
        "touches_ci": any(p.startswith(".github/workflows/") for p in paths),
        "touches_deps": any(p.endswith(LOCKFILES) for p in paths),
        "touches_tests": any("test" in p for p in paths),
        "proposed_by_agent": any(marker in log for marker in AGENT_TRAILERS),
    }
    return facts, paths


def substitute(source: str, facts: dict, placeholders_only: bool) -> tuple[str, set]:
    """Replace fact values in WPL source, returning the source and what was set."""
    out, seen = [], set()
    for line in source.splitlines():
        name = line.split()[1].rstrip(":") if line.startswith(FACT) else None
        wanted = name in facts and (not placeholders_only or "= {{" in line)
        if name and wanted:
            out.append(line.split("=")[0] + "= " + literal(facts[name]))
            seen.add(name)
        else:
            out.append(line)
    return "\n".join(out) + "\n", seen


def render_policy(template: Path, facts: dict) -> tuple[str, list[str]]:
    return render_policy_text(template.read_text(), str(template), facts)


def render_policy_text(source: str, name: str, facts: dict) -> tuple[str, list[str]]:
    """The template declares the rule; measured facts are substituted into it.

    A placeholder the gate does not measure is refused rather than left standing:
    a policy evaluated against facts it never received is the shape of check this
    project exists to distrust."""
    template = name
    declared = {line.split()[1].rstrip(":") for line in source.splitlines()
                if line.startswith(FACT) and "= {{" in line}
    missing = sorted(declared - set(facts))
    if missing:
        raise SystemExit(f"{template}: needs {', '.join(missing)}, which this gate "
                         "does not measure")
    rendered, seen = substitute(source, facts, placeholders_only=True)
    return rendered, sorted(set(facts) - seen)


def verdict_with(source: str, facts: dict, name: str, value) -> bool | None:
    probe = dict(facts)
    probe[name] = value
    rendered, _ = substitute(source, probe, placeholders_only=False)
    try:
        return WPL.evaluate(WPL.parse(rendered))
    except Exception:
        return None


def _bisect(source: str, facts: dict, name: str, low: int, high: int) -> int | None:
    """The nearest value between low and high at which the answer changes."""
    if verdict_with(source, facts, name, low) is verdict_with(source, facts, name, high):
        return None
    a, b = low, high
    while b - a > 1:
        mid = (a + b) // 2
        if verdict_with(source, facts, name, mid) is verdict_with(source, facts, name, a):
            a = mid
        else:
            b = mid
    return b if verdict_with(source, facts, name, a) is verdict_with(source, facts, name, low) else a


def flip_analysis(source: str, facts: dict, verdict: bool) -> list[str]:
    """What would change the answer, fact by fact — and for a number, by how much.

    Found by bisection with the reference interpreter rather than reasoned about,
    because "somewhere under 510" is not review information and "at 300" is."""
    findings = []
    for name, value in sorted(facts.items()):
        if isinstance(value, bool):
            if verdict_with(source, facts, name, not value) is (not verdict):
                findings.append(f"`{name}`: {value} → {not value} flips it")
            continue
        if isinstance(value, int):
            edge = _nearest_edge(source, facts, name, value)
            if edge is not None:
                where = "down to" if edge < value else "up to"
                findings.append(f"`{name}`: {value} → {where} {edge} flips it")
    return findings


def _nearest_edge(source: str, facts: dict, name: str, value: int) -> int | None:
    for low, high in ((0, value), (value, max(value * 4, value + 1000))):
        edge = _bisect(source, facts, name, low, high)
        if edge is not None:
            return edge
    return None


def conjuncts(rule: str) -> list[str]:
    """Split a top-level `&&` chain, ignoring the ones inside brackets."""
    parts, depth, current = [], 0, ""
    index = 0
    while index < len(rule):
        char = rule[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if depth == 0 and rule[index:index + 2] == "&&":
            parts.append(current.strip())
            current, index = "", index + 2
            continue
        current += char
        index += 1
    parts.append(current.strip())
    return [part for part in parts if part]


def failing_clauses(source: str, rule: str) -> list[str]:
    """Which parts of the rule are false, evaluated one at a time.

    When two constraints fail at once, no single fact flips the verdict and a
    report that only says "nothing flips it" has told the reviewer nothing. Each
    clause is re-evaluated on its own — carrying only the facts it mentions,
    because WPL refuses a program that declares a fact it never uses."""
    declarations = {}
    for line in source.splitlines():
        if line.startswith(FACT):
            declarations[line.split()[1].rstrip(":")] = line
    failing = []
    for clause in conjuncts(rule):
        needed = [line for name, line in declarations.items()
                  if re.search(rf"\b{re.escape(name)}\b", clause)]
        program = "\n".join(needed) + f"\ncheck {clause}\n"
        try:
            if WPL.evaluate(WPL.parse(program)) is False:
                failing.append(clause)
        except Exception:
            continue
    return failing


def rule_of(source: str) -> str:
    collected, collecting = [], False
    for line in source.splitlines():
        if line.startswith("check"):
            collecting = True
            collected.append(line.split("check", 1)[1].strip())
        elif collecting and line[:1].isspace() and line.strip():
            collected.append(line.strip())
        elif collecting:
            break
    return " ".join(collected) or "see the policy"


def inside_repo(candidate: str) -> Path:
    """A path from the command line, resolved and required to stay in the repo.

    This tool writes files, so unlike a reader it does have a root: `--out` and
    `--store` name places inside the repository being gated, and a value that
    resolves outside it is refused rather than followed."""
    resolved = (ROOT / candidate).resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        raise SystemExit(f"refusing {candidate!r}: it resolves outside the repository")
    return resolved


def open_store(path: Path) -> "W.Store":
    """The gate keeps its own store: a tool's scratch output has no business in
    the store that holds the repository's records."""
    for directory in ("blobs", "records"):
        (path / directory).mkdir(parents=True, exist_ok=True)
    return W.Store(path)


class Decision:
    """Everything the report is written from, in one place rather than in a
    fourteen-argument signature."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


def report_lines(d: "Decision") -> list[str]:
    verdict, facts, flips, failing = d.verdict, d.facts, d.flips, d.failing
    base, head, paths = d.base, d.head, d.paths
    subject, policy_hash, rule, doc = d.subject, d.policy_hash, d.rule, d.doc
    unused = d.unused
    lines = [
        f"# Gate report — {'ACCEPT' if verdict else 'REJECT'}",
        "",
        f"Change `{d.base_sha[:12]}...{d.head_sha[:12]}`"
        + (f" (`{base}...{head}`)" if base != d.base_sha else "")
        + f", {len(paths)} file(s), "
        f"+{facts['lines_added']}/-{facts['lines_removed']}.",
        "",
        "| | |", "| --- | --- |",
        f"| what changed | `{subject[:16]}…` — sha256 of the diff |",
        f"| who proposed it | {'an agent, by its commit trailers' if facts['proposed_by_agent'] else 'no recognized agent marker — which is not evidence of a human'} |",
        f"| policy in force | `{policy_hash[:16]}…` — the pinned bytes of the rule, read from `{d.policy_source}` |",
        f"| what was checked | `{rule}` |",
        f"| reason you can re-run | {d.rerun} |",
        f"| cost of re-running it | {doc['atp']:,} ATP, fixed in the check |",
        "", "## The facts it was decided on", "",
        "| fact | value |", "| --- | --- |",
    ]
    lines += [f"| `{name}` | `{value}` |" for name, value in sorted(facts.items())]
    if failing:
        lines += ["", "## Why it says that", "",
                  "These parts of the rule are false:", ""]
        lines += [f"- `{clause}`" for clause in failing]
    lines += ["", "## What would flip this verdict", ""]
    lines += ([f"- {line}" for line in flips] or
              ["- no single fact flips it" + (" — more than one clause is failing"
                                              if len(failing) > 1 else "")])
    if unused:
        lines += ["", f"Measured but unused by this policy: {', '.join(unused)}."]
    lines += [
        "", "## What this does not say", "",
        "It does not say the change is correct, safe, or wanted, and it does not "
        "replace a reviewer. It says a stated rule was applied to measured facts, "
        "that the rule's bytes are pinned by hash, and that anyone can re-execute "
        "the reason and get the same verdict — including someone who does not "
        "trust the machine that produced it.", ""]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="origin/master")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--policy", default=".warrant/gate.wpl")
    parser.add_argument("--policy-from", default=None,
                        help="revision to read the policy from; defaults to the "
                             "working tree, and CI must pass the base revision so "
                             "the change under review cannot edit its own rule")
    parser.add_argument("--store", default=".warrant/store",
                        help="where the gate writes its own check blobs")
    parser.add_argument("--out", default="gate-report.md")
    parser.add_argument("--pack", default=None,
                        help="write the check blobs to this zip so a reader can "
                             "re-run the reason from the artifact alone")
    arguments = parser.parse_args()

    base, head = resolve(arguments.base), resolve(arguments.head)
    if arguments.policy_from:
        origin = resolve(arguments.policy_from)
        if not SAFE_PATH.match(arguments.policy):
            raise SystemExit(f"refusing {arguments.policy!r} as a policy path")
        try:
            template_text = git("show", "--end-of-options",
                                f"{origin}:{arguments.policy}")
        except subprocess.CalledProcessError:
            raise SystemExit(f"{arguments.policy} does not exist at "
                             f"{arguments.policy_from}")
        policy_source = f"{arguments.policy} at {origin[:12]}"
    else:
        template = inside_repo(arguments.policy)
        if not template.is_file():
            raise SystemExit(f"no policy at {arguments.policy}; this gate has no "
                             "opinion of its own and refuses to invent one")
        template_text = template.read_text()
        policy_source = f"{arguments.policy} in the working tree"

    facts, paths = measure(base, head)
    source, unused = render_policy_text(template_text, arguments.policy, facts)
    verdict = WPL.evaluate(WPL.parse(source))

    store = open_store(inside_repo(arguments.store))
    compiled = WPL.compile_source(source, put=store.put_blob,
                                  name=Path(arguments.policy).name)
    if compiled.result != verdict:
        raise SystemExit("the compiled term disagrees with the reference "
                         "interpreter — refusing to report either")

    subject = hashlib.sha256(git("diff", f"{base}...{head}").encode()).hexdigest()
    rule = rule_of(source)
    rerun = (f"`warrant --store {arguments.store} check {compiled.blob[:16]}…` — "
             "the blobs are in this run's `gate-store` artifact"
             if arguments.pack else
             f"regenerate the report and re-run `warrant --store {arguments.store} "
             f"check {compiled.blob[:16]}…`; the blobs are not published with it")
    lines = report_lines(Decision(
        verdict=verdict, base=arguments.base, head=arguments.head, paths=paths,
        base_sha=base, head_sha=head, policy_source=policy_source, rerun=rerun,
        facts=facts, subject=subject, policy_hash=store.put_blob(source.encode()),
        rule=rule, check_hash=compiled.blob, doc=compiled.doc,
        flips=flip_analysis(source, facts, verdict), unused=unused,
        failing=[] if verdict else failing_clauses(source, rule),
        store=arguments.store))

    inside_repo(arguments.out).write_text("\n".join(lines))
    if arguments.pack:
        pack = inside_repo(arguments.pack)
        with zipfile.ZipFile(pack, "w", zipfile.ZIP_DEFLATED) as archive:
            for blob in sorted((ROOT / arguments.store / "blobs").iterdir()):
                archive.write(blob, f"gate-store/blobs/{blob.name}")
            archive.writestr("gate-store/records/.keep", "")
            archive.writestr("README.txt",
                             "Unzip, then:\n"
                             f"  warrant --store gate-store check {compiled.blob}\n"
                             "Expect the verdict the report claims, for the ATP it "
                             "states. The blobs here are exactly what decided.\n")
    print("\n".join(lines[:14]))
    print(f"\nwritten: {arguments.out}")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
