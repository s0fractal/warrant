#!/usr/bin/env python3
"""Every GitHub Actions workflow must PARSE as YAML and have a basic jobs shape.

The agent-gate workflow — the repository's own governance control plane — sat
broken for an unknown span with an unquoted `--only-binary :all:` that made the
file unparseable, so every run failed with no job and the gate silently did
nothing (Codex review, 2026-08-28). A governance gate that cannot be parsed is
the purest form of a control that does not control. This check makes that class
of defect impossible to reintroduce silently: a workflow that stops parsing, or
that parses into a shape GitHub Actions cannot run, fails the suite instead of
failing invisibly on GitHub.

SCOPE, stated so the check does not overclaim (Codex round 2): this is **YAML
parse plus a basic jobs shape** — the root is a mapping, `jobs` is a nonempty
mapping, and every job definition is itself a mapping. It is NOT full GitHub
Actions schema validation (it does not check `runs-on`, `steps`, action
versions, permissions, or event triggers), and it intentionally does not judge
whether the gate is wired to block a merge (branch protection, required checks)
— that is repository configuration a file cannot see.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows"


def shape_error(doc):
    """None if `doc` has a runnable basic jobs shape, else a reason string.
    Basic = root mapping, `jobs` a nonempty mapping, each job def a mapping.
    Deliberately NOT a full Actions schema check."""
    if not isinstance(doc, dict):
        return "top level is not a mapping"
    if "jobs" not in doc:
        return "no `jobs:` key"
    jobs = doc["jobs"]
    if not isinstance(jobs, dict):
        return "`jobs:` is not a mapping (e.g. null, a list, or a scalar)"
    if not jobs:
        return "`jobs:` is an empty mapping — no job would run"
    for jid, jdef in jobs.items():
        if not isinstance(jdef, dict):
            return f"job `{jid}` is not a mapping (its definition is unusable)"
    return None


def main():
    try:
        import yaml
    except ImportError:
        print("LINT-WORKFLOWS: UNRUN — PyYAML not installed "
              "(pip install pyyaml)")
        sys.exit(3)

    # Negative controls (Codex rounds 1–2): every known-bad shape MUST be
    # rejected — a linter that cannot be shown to reject the things it exists to
    # reject is decoration. A parse error OR a shape_error both count as caught.
    NEGATIVE = {
        "unquoted :all: (unparseable)":
            "jobs:\n  x:\n    steps:\n      - run: pip install :all: foo\n",
        "jobs: null": "jobs: null\n",
        "jobs: [] (a list)": "jobs: []\n",
        "root scalar": "just-a-scalar\n",
        "job def not a mapping": "jobs:\n  verdict: null\n",
        "empty jobs mapping": "jobs: {}\n",
    }
    for label, text in NEGATIVE.items():
        try:
            doc = yaml.safe_load(text)
            caught = shape_error(doc) is not None
        except yaml.YAMLError:
            caught = True
        if not caught:
            print(f"LINT-WORKFLOWS: FAIL — negative control '{label}' was "
                  "ACCEPTED; this linter cannot detect a defect it exists for.",
                  file=sys.stderr)
            sys.exit(1)

    files = sorted(WF.glob("*.yml")) + sorted(WF.glob("*.yaml"))
    if not files:
        print("LINT-WORKFLOWS: UNRUN — no workflow files found")
        sys.exit(3)

    bad = []
    for f in files:
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            bad.append((f.name, str(exc).splitlines()[0]))
            continue
        err = shape_error(doc)
        if err:
            bad.append((f.name, err))

    if bad:
        print("LINT-WORKFLOWS: FAIL", file=sys.stderr)
        for name, why in bad:
            print(f"  {name}: {why}", file=sys.stderr)
        sys.exit(1)

    print(f"LINT-WORKFLOWS: PASS — {len(files)} workflow file(s): YAML parses "
          "and each has a basic jobs shape (not full Actions schema validation).")
    sys.exit(0)


if __name__ == "__main__":
    main()
