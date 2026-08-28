#!/usr/bin/env python3
"""Every GitHub Actions workflow must PARSE as YAML.

The agent-gate workflow — the repository's own governance control plane — sat
broken for an unknown span with an unquoted `--only-binary :all:` that made the
file unparseable, so every run failed with no job and the gate silently did
nothing (Codex review, 2026-08-28). A governance gate that cannot be parsed is
the purest form of a control that does not control. This check makes that class
of defect impossible to reintroduce silently: a workflow that stops parsing
fails the suite instead of failing invisibly on GitHub.

It intentionally does NOT judge whether the gate is wired to block a merge
(branch protection, required checks) — that is repository configuration a file
cannot see. It checks the one thing a file can: the workflows are well-formed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows"


def main():
    try:
        import yaml
    except ImportError:
        print("LINT-WORKFLOWS: UNRUN — PyYAML not installed "
              "(pip install pyyaml)")
        sys.exit(3)

    files = sorted(WF.glob("*.yml")) + sorted(WF.glob("*.yaml"))
    if not files:
        print("LINT-WORKFLOWS: UNRUN — no workflow files found")
        sys.exit(3)

    bad = []
    for f in files:
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or "jobs" not in doc:
                bad.append((f.name, "parsed but has no `jobs:` mapping"))
        except yaml.YAMLError as exc:
            bad.append((f.name, str(exc).splitlines()[0]))

    if bad:
        print("LINT-WORKFLOWS: FAIL", file=sys.stderr)
        for name, why in bad:
            print(f"  {name}: {why}", file=sys.stderr)
        sys.exit(1)

    print(f"LINT-WORKFLOWS: PASS — {len(files)} workflow file(s) parse and "
          "declare jobs.")
    sys.exit(0)


if __name__ == "__main__":
    main()
